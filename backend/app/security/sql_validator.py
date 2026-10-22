"""AST-level validation of model-generated SQL.

Safety does not rely on prompt instructions. Every query is parsed with SQLGlot and must:
  * be exactly one statement;
  * be a read-only SELECT (optionally with CTEs / set operations);
  * reference only allowlisted tables and columns;
  * call no file, network, settings or system functions.
The validated AST is re-rendered and that rendered SQL is what gets executed, so the text that
was checked is exactly the text that runs. The executor additionally uses a read-only DuckDB
connection with external access disabled (defence in depth).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.database.schema_catalog import ALLOWED_COLUMNS, ALLOWED_TABLES

MAX_SQL_LENGTH = 8000


class SQLValidationError(ValueError):
    """Raised when SQL is rejected. `message` is safe to show to users."""


@dataclass
class ValidatedSQL:
    sql: str
    tables: list[str]
    columns: list[str] = field(default_factory=list)


def _node_types(*names: str) -> tuple[type, ...]:
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


FORBIDDEN_NODES = _node_types(
    "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterColumn", "Command",
    "Copy", "Pragma", "Set", "SetItem", "Use", "Transaction", "Commit", "Rollback", "Attach",
    "Detach", "Install", "LoadData", "Describe", "Show", "Grant", "Revoke", "Analyze", "Into",
    "TruncateTable", "Export", "Summarize",
)

ALLOWED_ROOTS = _node_types("Select", "Union", "Intersect", "Except", "Subquery")

# Function names (lower case) that could reach files, network, settings or internals.
FORBIDDEN_FUNCTION_PATTERN = re.compile(
    r"^(read_\w*|glob|getenv|query|query_table|current_setting|set_config|duckdb_\w*|pragma_\w*|"
    r"sniff_csv|parquet_\w*|iceberg_\w*|delta_scan|sqlite_\w*|postgres_\w*|mysql_\w*|"
    r"httpfs\w*|load|install|system|shell|which_secret|enable_\w*|disable_\w*|checkpoint|"
    r"force_checkpoint|export_\w*|import_\w*|copy|attach|detach|make_timestamp_from_file|"
    r"json_execute_serialized_sql|\w*_scan)$"
)


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    try:
        return node.sql_name().lower()
    except Exception:  # pragma: no cover
        return type(node).__name__.lower()


def validate_sql(sql: str, allowed_tables: frozenset[str] | set[str] | None = None,
                 allowed_columns: frozenset[str] | set[str] | None = None) -> ValidatedSQL:
    """Validate against an allowlist. Defaults to the built-in dataset; imported datasets pass their own."""
    allowed_tables = frozenset(t.lower() for t in (allowed_tables if allowed_tables is not None else ALLOWED_TABLES))
    allowed_columns = frozenset(c.lower() for c in (allowed_columns if allowed_columns is not None else ALLOWED_COLUMNS))
    if not sql or not sql.strip():
        raise SQLValidationError("No SQL was generated.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SQLValidationError("SQL is too long.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError as exc:
        raise SQLValidationError(f"SQL could not be parsed: {str(exc).splitlines()[0][:200]}") from exc
    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, ALLOWED_ROOTS):
        raise SQLValidationError("Only read-only SELECT queries are allowed.")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLValidationError(f"Statement type '{type(node).__name__}' is not allowed.")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if FORBIDDEN_FUNCTION_PATTERN.match(name):
                raise SQLValidationError(f"Function '{name}' is not allowed.")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}

    # Names introduced by the query itself (aliases, CTE / derived-table column lists, lambdas).
    defined_names: set[str] = set()
    for alias in tree.find_all(exp.Alias):
        defined_names.add(alias.alias.lower())
    for table_alias in tree.find_all(exp.TableAlias):
        if table_alias.name:
            defined_names.add(table_alias.name.lower())
        for col in table_alias.columns:
            defined_names.add(col.name.lower())
    for lam in tree.find_all(exp.Lambda):
        for param in lam.expressions:
            defined_names.add(param.name.lower())

    tables: set[str] = set()
    table_aliases: set[str] = set(cte_names)
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SQLValidationError("Table functions are not allowed in FROM.")
        name = table.name.lower()
        if table.catalog or (table.db and table.db.lower() != "main"):
            raise SQLValidationError("Schema- or catalog-qualified tables are not allowed.")
        if name in cte_names:
            if table.alias:  # e.g. FROM daily AS d
                table_aliases.add(table.alias.lower())
            continue
        if name not in allowed_tables:
            raise SQLValidationError(f"Table '{table.name}' is not allowed. Allowed: {', '.join(sorted(allowed_tables))}.")
        tables.add(name)
        table_aliases.add(name)
        if table.alias:
            table_aliases.add(table.alias.lower())
    for sub in tree.find_all(exp.Subquery):
        if sub.alias:
            table_aliases.add(sub.alias.lower())

    if not tables:
        raise SQLValidationError(f"The query must read from the {' or '.join(sorted(allowed_tables))} table.")

    columns: set[str] = set()
    for column in tree.find_all(exp.Column):
        if isinstance(column.this, exp.Star):
            continue
        col_name = column.name.lower()
        qualifier = column.table.lower() if column.table else ""
        if qualifier and qualifier not in table_aliases:
            raise SQLValidationError(f"Unknown table reference '{column.table}'.")
        if col_name not in allowed_columns and col_name not in defined_names:
            raise SQLValidationError(f"Column '{column.name}' is not an allowed column.")
        columns.add(col_name)

    rendered = tree.sql(dialect="duckdb", pretty=True)
    # Round-trip check: the rendered SQL must itself parse to a single statement.
    try:
        if len(sqlglot.parse(rendered, read="duckdb")) != 1:
            raise SQLValidationError("SQL normalisation failed.")
    except ParseError as exc:
        raise SQLValidationError("SQL normalisation failed.") from exc
    return ValidatedSQL(sql=rendered, tables=sorted(tables), columns=sorted(columns))
