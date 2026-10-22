import pytest

from app.security.sql_validator import SQLValidationError, validate_sql

SAFE = [
    "SELECT country, SUM(line_amount) AS rev FROM transactions GROUP BY country ORDER BY rev DESC LIMIT 5",
    "WITH m AS (SELECT invoice_month, SUM(line_amount) AS rev FROM transactions GROUP BY 1) SELECT * FROM m ORDER BY 1",
    "SELECT t.stock_code, ANY_VALUE(t.description) AS d FROM transactions AS t WHERE t.item_type = 'PRODUCT' GROUP BY 1",
    "SELECT SUM(line_amount) FILTER (WHERE line_type = 'SALE') AS gross FROM transactions",
    "SELECT strftime(invoice_month, '%Y-%m') AS month FROM transactions GROUP BY ALL",
    "SELECT country FROM transactions WHERE line_type = 'SALE' UNION SELECT country FROM transactions WHERE line_type = 'CANCELLATION'",
    "SELECT x.c FROM (SELECT country AS c FROM transactions) AS x",
    "SELECT customer_id, RANK() OVER (ORDER BY SUM(line_amount) DESC) AS r FROM transactions GROUP BY customer_id",
]

UNSAFE = [
    ("DELETE FROM transactions", "read-only"),
    ("UPDATE transactions SET quantity = 0", "read-only"),
    ("INSERT INTO transactions SELECT * FROM transactions", "read-only"),
    ("DROP TABLE transactions", "read-only"),
    ("CREATE TABLE x AS SELECT * FROM transactions", "read-only"),
    ("SELECT 1 FROM transactions; DROP TABLE transactions", "one SQL statement"),
    ("SELECT * FROM dataset_metadata", "not allowed"),
    ("SELECT * FROM information_schema.tables", "not allowed"),
    ("SELECT * FROM read_csv('C:/secrets.csv')", "not allowed"),
    ("SELECT * FROM read_parquet('x.parquet')", "not allowed"),
    ("SELECT getenv('ANTHROPIC_API_KEY') FROM transactions", "not allowed"),
    ("SELECT * FROM duckdb_settings()", "not allowed"),
    ("SELECT password FROM transactions", "not an allowed column"),
    ("COPY transactions TO 'out.csv'", "read-only"),
    ("ATTACH 'other.db' AS o", "read-only"),
    ("PRAGMA database_list", "read-only"),
    ("SET enable_external_access = true", "read-only"),
    ("SELECT * INTO new_table FROM transactions", None),
    ("SELECT 1", "must read from the transactions table"),
    ("", "No SQL"),
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass(sql):
    v = validate_sql(sql)
    assert "transactions" in v.tables
    assert v.sql


@pytest.mark.parametrize("sql,fragment", UNSAFE)
def test_unsafe_queries_rejected(sql, fragment):
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql)
    if fragment:
        assert fragment.lower() in str(exc.value).lower()


def test_rendered_sql_is_what_was_validated():
    v = validate_sql("select   country from transactions  limit 3;")
    assert v.sql.startswith("SELECT")
    assert ";" not in v.sql
