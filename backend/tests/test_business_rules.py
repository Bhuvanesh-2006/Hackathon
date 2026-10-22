import pytest

from app.agent.ambiguity import check_ambiguity
from app.database.business_rules import classify_item_type, classify_line_type
from tests.conftest import requires_data


@pytest.mark.parametrize("inv,qty,price,expected", [
    ("489434", 12, 6.95, "SALE"),
    ("C489449", -12, 2.95, "CANCELLATION"),
    ("c489449", -1, 1.0, "CANCELLATION"),
    ("A506401", 1, -53594.36, "BAD_DEBT_ADJUSTMENT"),
    ("489463", -240, 0.0, "STOCK_ADJUSTMENT"),
    ("489500", 5, 0.0, "ZERO_PRICE"),
])
def test_line_type(inv, qty, price, expected):
    assert classify_line_type(inv, qty, price) == expected


@pytest.mark.parametrize("code,expected", [
    ("85123A", "PRODUCT"), ("22423", "PRODUCT"), ("POST", "POSTAGE"), ("DOT", "POSTAGE"), ("C2", "POSTAGE"),
    ("M", "MANUAL_ADJUSTMENT"), ("m", "MANUAL_ADJUSTMENT"), ("BANK CHARGES", "FEE"), ("AMAZONFEE", "FEE"),
    ("D", "DISCOUNT"), ("TEST001", "TEST"), ("gift_0001_20", "GIFT_VOUCHER"), ("DCGS0058", "PRODUCT"),
])
def test_item_type(code, expected):
    assert classify_item_type(code) == expected


@pytest.mark.parametrize("q", ["Who are our best customers?", "Show me our top customers", "What are our best-selling products?",
                               "best sellers"])
def test_ambiguous_questions_detected(q):
    assert check_ambiguity(q) is not None


@pytest.mark.parametrize("q", ["Who are our best customers by net revenue?", "Top 5 customers by number of invoices",
                               "Which products had the most returned units?", "Top products by units sold"])
def test_unambiguous_questions_pass(q):
    assert check_ambiguity(q) is None


@requires_data
def test_every_row_classified_and_overlap_removed():
    from app.database.connection import fetch_metadata, run_query

    res = run_query("SELECT COUNT(*) FILTER (WHERE line_type IS NULL OR item_type IS NULL), COUNT(*) FROM transactions")
    unclassified, total = res.rows[0]
    assert unclassified == 0
    meta = fetch_metadata()
    assert meta["source_rows_total"] == 1067371
    assert total == meta["source_rows_total"] - meta["overlap_rows_removed"]
    # The overlap week must now appear exactly once per invoice line.
    dup = run_query("""SELECT COUNT(*) FROM (SELECT invoice, stock_code, quantity, invoice_date, COUNT(DISTINCT source_sheet) s
                       FROM transactions GROUP BY ALL HAVING s > 1)""").rows[0][0]
    assert dup == 0


@requires_data
def test_cancellations_are_negative_and_stock_adjustments_not_returns():
    from app.database.connection import run_query

    row = run_query("""SELECT
        COUNT(*) FILTER (WHERE line_type = 'CANCELLATION' AND NOT starts_with(invoice, 'C')),
        COUNT(*) FILTER (WHERE line_type = 'STOCK_ADJUSTMENT' AND starts_with(invoice, 'C')),
        COUNT(*) FILTER (WHERE line_type = 'SALE' AND (quantity <= 0 OR unit_price <= 0))
        FROM transactions""").rows[0]
    assert row == [0, 0, 0]
