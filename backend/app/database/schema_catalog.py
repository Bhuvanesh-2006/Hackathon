"""Allowlisted schema exposed to the agent: tables, columns, types and descriptions."""
from __future__ import annotations

ALLOWED_TABLE = "transactions"

COLUMNS: list[dict[str, str]] = [
    {"name": "invoice", "type": "VARCHAR", "description": "Invoice number. 6 digits; prefix 'C' = cancellation, 'A' = bad-debt adjustment."},
    {"name": "stock_code", "type": "VARCHAR", "description": "Product (item) code. Non-product codes include POST, DOT, M, BANK CHARGES, AMAZONFEE."},
    {"name": "description", "type": "VARCHAR", "description": "Product / item name. May be NULL on stock adjustments."},
    {"name": "quantity", "type": "BIGINT", "description": "Units on the line. Negative on cancellations and stock adjustments."},
    {"name": "invoice_date", "type": "TIMESTAMP", "description": "Invoice date and time."},
    {"name": "invoice_month", "type": "DATE", "description": "First day of the invoice month (for monthly grouping)."},
    {"name": "invoice_year", "type": "INTEGER", "description": "Calendar year of the invoice."},
    {"name": "unit_price", "type": "DOUBLE", "description": "Unit price in GBP."},
    {"name": "line_amount", "type": "DOUBLE", "description": "quantity * unit_price in GBP (negative for cancellations)."},
    {"name": "customer_id", "type": "VARCHAR", "description": "Customer identifier. NULL when unknown."},
    {"name": "has_customer", "type": "BOOLEAN", "description": "False when customer_id is missing."},
    {"name": "country", "type": "VARCHAR", "description": "Customer country name (e.g. 'United Kingdom', 'Germany', 'EIRE' = Ireland)."},
    {"name": "line_type", "type": "VARCHAR", "description": "SALE | CANCELLATION | STOCK_ADJUSTMENT | ZERO_PRICE | BAD_DEBT_ADJUSTMENT."},
    {"name": "item_type", "type": "VARCHAR", "description": "PRODUCT | POSTAGE | FEE | MANUAL_ADJUSTMENT | DISCOUNT | SAMPLE | TEST | GIFT_VOUCHER."},
    {"name": "is_cancellation", "type": "BOOLEAN", "description": "True when line_type = 'CANCELLATION'."},
    {"name": "source_sheet", "type": "VARCHAR", "description": "Source worksheet in the original Excel workbook."},
    {"name": "source_row", "type": "BIGINT", "description": "Row number in the source worksheet."},
]

ALLOWED_COLUMNS: frozenset[str] = frozenset(c["name"] for c in COLUMNS)
ALLOWED_TABLES: frozenset[str] = frozenset({ALLOWED_TABLE})


def schema_as_text() -> str:
    lines = [f"TABLE {ALLOWED_TABLE} ("]
    for c in COLUMNS:
        lines.append(f"  {c['name']} {c['type']}  -- {c['description']}")
    lines.append(")")
    return "\n".join(lines)
