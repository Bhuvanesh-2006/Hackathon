"""Evidence attached to every executed answer, derived from the executed SQL and its results.

Nothing here is model-generated: filters and grouping come from the SQL syntax tree, the source
row count comes from a COUNT(*) query built from the same WHERE clause, and limitations are
rules triggered by the query and result.
"""
from __future__ import annotations

import logging
from typing import Any

import sqlglot
from sqlglot import exp

from app.agent.context import extract_filters, filter_labels
from app.database import connection
from app.security.sql_validator import SQLValidationError, validate_sql

log = logging.getLogger(__name__)
DATASET_START, DATASET_END = "2009-12-01", "2011-12-09"


def _group_by(tree: exp.Expression) -> list[str]:
    outer = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    for select in [outer, *tree.find_all(exp.Select)]:
        if select is None:
            continue
        group = select.args.get("group")
        if group:
            return [e.sql(dialect="duckdb") for e in group.expressions] or ["ALL"]
    return []


def _from(select: exp.Select) -> exp.From | None:
    node = select.args.get("from_") or select.args.get("from")  # key name differs across SQLGlot versions
    return node if isinstance(node, exp.From) else None


def _source_rows(tree: exp.Expression) -> tuple[int | None, str | None]:
    readers = [s for s in tree.find_all(exp.Select)
               if _from(s) is not None and isinstance(_from(s).this, exp.Table)
               and _from(s).this.name.lower() == "transactions" and not s.args.get("joins")]
    wheres = {(s.args.get("where").sql(dialect="duckdb") if s.args.get("where") else "") for s in readers}
    if len(readers) == 0 or len(wheres) != 1:
        return None, "Not computed: the query reads the table with more than one filter."
    where = wheres.pop()
    alias = _from(readers[0]).this.alias
    count_sql = f"SELECT COUNT(*) AS n FROM transactions{' AS ' + alias if alias else ''} {where}"
    try:
        v = validate_sql(count_sql)
        return int(connection.run_query(v.sql).rows[0][0]), None
    except (SQLValidationError, connection.QueryExecutionError, connection.QueryTimeoutError) as exc:
        log.info("source row count skipped: %s", exc)
        return None, "Not computed for this query shape."


def build_evidence(sql: str, columns: list[str], rows: list[list[Any]], truncated: bool,
                   rules: list[dict], retrieval: dict | None, comparison: dict | None) -> dict:
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        tree = None
    filters = extract_filters(sql)
    if comparison:
        filters.pop("date_from", None)
        filters.pop("date_to", None)
    date_range = (
        {"from": min(comparison["current"][0], comparison["previous"][0]),
         "to": max(comparison["current"][1], comparison["previous"][1]), "source": "comparison periods"}
        if comparison else
        {"from": filters.get("date_from", DATASET_START), "to": filters.get("date_to", DATASET_END), "source": "filter"}
        if ("date_from" in filters or "date_to" in filters) else
        {"from": f"{filters['year']}-01-01", "to": f"{filters['year']}-12-31", "source": "year filter"} if "year" in filters else
        {"from": DATASET_START, "to": DATASET_END, "source": "full dataset"}
    )
    source_rows, source_note = _source_rows(tree) if tree is not None else (None, "Not computed.")
    lowered = sql.lower()

    limitations = []
    if date_range["to"] >= "2011-12" or date_range["source"] == "full dataset" or filters.get("year") == 2011:
        limitations.append("December 2011 is partial: the data ends on 2011-12-09.")
    if "has_customer" in lowered or "customer_id" in columns:
        limitations.append("Lines without a customer ID (22.5% of lines) are excluded from customer-level figures.")
    if "cancellation" in lowered:
        limitations.append("'C' invoices mix order cancellations and returns; they cannot be told apart in this data.")
    if any(k in lowered for k in ("line_amount", "revenue")):
        limitations.append("Revenue is sales value, not profit: the data contains no costs.")
    if "date_trunc" in lowered or "invoice_date as date" in lowered:
        limitations.append("Per-day or per-week figures net cancellations on the day they were recorded, which can "
                           "differ from the day of the original sale.")
    if truncated:
        limitations.append("The result was truncated at the row limit.")

    return {
        "filters": filter_labels(filters),
        "date_range": date_range,
        "comparison": comparison,
        "grouping": _group_by(tree) if tree is not None else [],
        "source_row_count": source_rows,
        "source_row_note": source_note,
        "result_rows": len(rows),
        "metric_definitions": rules,
        "limitations": limitations,
        "verification": {
            "validated": True,
            "executed": True,
            "independently_verified": False,
            "note": "The query passed validation and ran on the dataset. Whether it matches your intent is not "
                    "independently verified; the Reliability Benchmark measures that for known question types.",
        },
        "retrieval": retrieval,
    }


def build_generic_evidence(ds: dict, sql: str, rows: list[list[Any]], truncated: bool) -> dict:
    """Evidence for imported datasets: no retail definitions apply."""
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        tree = None
    filters = []
    if tree is not None:
        for node in tree.find_all(exp.EQ, exp.In, exp.GT, exp.GTE, exp.LT, exp.LTE):
            parent, in_where = node.parent, False
            while parent is not None:
                if isinstance(parent, exp.Filter):
                    break
                if isinstance(parent, exp.Where):
                    in_where = True
                    break
                parent = parent.parent
            if in_where:
                filters.append({"field": "condition", "label": node.sql(dialect="duckdb")[:120]})
    rows_scanned, note = (None, "Not computed.")
    if tree is not None:
        readers = [s for s in tree.find_all(exp.Select) if _from(s) is not None and isinstance(_from(s).this, exp.Table)
                   and _from(s).this.name.lower() == ds["table"] and not s.args.get("joins")]
        wheres = {(s.args.get("where").sql(dialect="duckdb") if s.args.get("where") else "") for s in readers}
        if len(readers) >= 1 and len(wheres) == 1:
            from app.datasets import execution, registry

            try:
                v = execution.validate_for(ds, f"SELECT COUNT(*) AS n FROM {ds['table']} {wheres.pop()}")
                count = connection.run_query(v.sql, db_path=registry.storage_path(ds)).rows[0][0]
                rows_scanned, note = int(count), None
            except Exception:
                note = "Not computed for this query shape."
    limitations = ["Imported dataset: figures are computed directly from its columns. No business definitions "
                   "(such as revenue, returns or customers) are applied unless a column contains them."]
    limitations += [f for f in ds.get("findings", []) if "kept as text" in f or "ambiguous" in f][:3]
    if truncated:
        limitations.append("The result was truncated at the row limit.")
    return {
        "filters": filters[:8], "date_range": {"from": "", "to": "", "source": "all rows (no date filter applied)"} if not filters
        else {"from": "", "to": "", "source": "see conditions"},
        "comparison": None, "grouping": _group_by(tree) if tree is not None else [],
        "source_row_count": rows_scanned, "source_row_note": note, "result_rows": len(rows), "metric_definitions": [],
        "limitations": limitations,
        "verification": {"validated": True, "executed": True, "independently_verified": False,
                         "note": f"Validated against the schema of '{ds['name']}' and run on that dataset only. Whether it "
                                 "matches your intent is not independently verified."},
        "retrieval": None,
        "dataset": {"id": ds["id"], "name": ds["name"], "version": ds["version"]},
    }
