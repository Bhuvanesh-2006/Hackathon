"""Single source of truth for the retail data rules.

These definitions are used by the data preparation script (to derive columns), the LLM
prompt, the offline provider, the benchmark reference SQL, and the UI (via the API).
"""
from __future__ import annotations

import re

CURRENCY = "GBP"
CURRENCY_SYMBOL = "£"

# Stock codes that are not merchandise. Matched case-insensitively against the full code.
NON_PRODUCT_CODES: dict[str, str] = {
    "POST": "POSTAGE",
    "DOT": "POSTAGE",
    "C2": "POSTAGE",
    "BANK CHARGES": "FEE",
    "AMAZONFEE": "FEE",
    "CRUK": "FEE",
    "M": "MANUAL_ADJUSTMENT",
    "ADJUST": "MANUAL_ADJUSTMENT",
    "ADJUST2": "MANUAL_ADJUSTMENT",
    "B": "MANUAL_ADJUSTMENT",
    "D": "DISCOUNT",
    "S": "SAMPLE",
    "TEST001": "TEST",
    "TEST002": "TEST",
}
GIFT_VOUCHER_PATTERN = re.compile(r"^gift_\d{4}_\d+$", re.IGNORECASE)


def classify_item_type(stock_code: str | None) -> str:
    """Return PRODUCT or a non-product category for a stock code."""
    if stock_code is None:
        return "UNKNOWN"
    code = str(stock_code).strip()
    upper = code.upper()
    if upper in NON_PRODUCT_CODES:
        return NON_PRODUCT_CODES[upper]
    if GIFT_VOUCHER_PATTERN.match(code):
        return "GIFT_VOUCHER"
    return "PRODUCT"


# Line types (column transactions.line_type). Every source row receives exactly one.
LINE_TYPES: dict[str, str] = {
    "SALE": "Invoice number does not start with 'C' or 'A', quantity > 0 and unit price > 0.",
    "CANCELLATION": "Invoice number starts with 'C'. Quantity is negative. Represents a cancelled "
    "order line or a customer return; the dataset does not distinguish the two.",
    "STOCK_ADJUSTMENT": "Invoice does not start with 'C'/'A' but quantity <= 0 (e.g. damaged, lost, "
    "'found' stock write-offs). Not a customer return. Excluded from revenue.",
    "ZERO_PRICE": "Invoice does not start with 'C'/'A', quantity > 0 but unit price <= 0 "
    "(free items / internal corrections). Excluded from revenue.",
    "BAD_DEBT_ADJUSTMENT": "Invoice number starts with 'A' ('Adjust bad debt'). Accounting "
    "adjustment, excluded from revenue.",
}

ITEM_TYPES: dict[str, str] = {
    "PRODUCT": "Merchandise stock code.",
    "POSTAGE": "Postage / carriage charges (POST, DOT, C2).",
    "FEE": "Bank charges, Amazon fees, CRUK commission.",
    "MANUAL_ADJUSTMENT": "Manual entries and adjustments (M, ADJUST, ADJUST2, B).",
    "DISCOUNT": "Discount lines (D).",
    "SAMPLE": "Samples (S).",
    "TEST": "Test codes (TEST001, TEST002).",
    "GIFT_VOUCHER": "Gift voucher codes (gift_0001_*).",
}


def classify_line_type(invoice: str, quantity: float, unit_price: float) -> str:
    inv = str(invoice).strip().upper()
    if inv.startswith("C"):
        return "CANCELLATION"
    if inv.startswith("A"):
        return "BAD_DEBT_ADJUSTMENT"
    if quantity <= 0:
        return "STOCK_ADJUSTMENT"
    if unit_price <= 0:
        return "ZERO_PRICE"
    return "SALE"


# Business definitions. `sql` is the canonical expression over table `transactions`.
BUSINESS_RULES: list[dict[str, str]] = [
    {
        "id": "currency",
        "name": "Currency",
        "definition": "All monetary values are in pounds sterling (GBP, £). unit_price is the "
        "per-unit price in GBP as recorded by the retailer.",
        "sql": "line_amount = quantity * unit_price",
    },
    {
        "id": "period",
        "name": "Reporting period",
        "definition": "The dataset covers invoices dated from 2009-12-01 to 2011-12-09. Unless the "
        "user specifies a period, figures cover the full dataset period.",
        "sql": "invoice_date BETWEEN '2009-12-01' AND '2011-12-10'",
    },
    {
        "id": "gross_revenue",
        "name": "Gross revenue",
        "definition": "Sum of line_amount for SALE lines of PRODUCT items. Cancellations are not "
        "deducted. Postage, fees and adjustments are excluded.",
        "sql": "SUM(line_amount) FILTER (WHERE line_type = 'SALE' AND item_type = 'PRODUCT')",
    },
    {
        "id": "net_revenue",
        "name": "Net revenue (default 'revenue')",
        "definition": "Gross revenue minus the value of cancelled/returned product lines, i.e. the "
        "sum of line_amount over PRODUCT lines whose line_type is SALE or CANCELLATION "
        "(cancellation amounts are negative). This is the default meaning of 'revenue' or 'sales'.",
        "sql": "SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION') AND item_type = 'PRODUCT')",
    },
    {
        "id": "cancellations",
        "name": "Cancellations and returns",
        "definition": "Lines on invoices starting with 'C'. The dataset does not separate order "
        "cancellations from returns, so they are reported together. Cancelled value is "
        "reported as a positive amount: -SUM(line_amount). Cancellations are deducted in net "
        "revenue and reported separately everywhere else. A 'C' line is not always the return "
        "of a sale in this data: 11% of customer-linked cancellation lines have no earlier sale "
        "of that product to that customer (purchases before Dec 2009 or adjustments), and one "
        "manual-adjustment 'C' line has a positive quantity.",
        "sql": "-SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION')",
    },
    {
        "id": "returned_units",
        "name": "Returned units vs return transactions",
        "definition": "Returned units = -SUM(quantity) over CANCELLATION lines of PRODUCT items. "
        "Return transactions = COUNT(DISTINCT invoice) over CANCELLATION lines. These are "
        "different measures and are never mixed.",
        "sql": "-SUM(quantity) FILTER (WHERE line_type = 'CANCELLATION' AND item_type = 'PRODUCT')",
    },
    {
        "id": "negative_quantities",
        "name": "Negative quantities",
        "definition": "Negative quantities appear on CANCELLATION lines (customer-facing) and on "
        "STOCK_ADJUSTMENT lines (internal write-offs such as damaged or lost stock, usually "
        "with zero price and no customer). Only CANCELLATION lines count as returns.",
        "sql": "line_type IN ('CANCELLATION','STOCK_ADJUSTMENT')",
    },
    {
        "id": "orders",
        "name": "Orders / valid invoices",
        "definition": "Number of distinct invoices containing at least one SALE line. Cancellation "
        "invoices are not orders.",
        "sql": "COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE')",
    },
    {
        "id": "units_sold",
        "name": "Units sold",
        "definition": "SUM(quantity) over SALE lines of PRODUCT items (before cancellations).",
        "sql": "SUM(quantity) FILTER (WHERE line_type = 'SALE' AND item_type = 'PRODUCT')",
    },
    {
        "id": "customers",
        "name": "Customer count",
        "definition": "Distinct non-NULL customer_id values with at least one SALE line. Lines "
        "without a customer ID are not counted as customers.",
        "sql": "COUNT(DISTINCT customer_id) FILTER (WHERE line_type = 'SALE')",
    },
    {
        "id": "quantity",
        "name": "Quantity",
        "definition": "quantity is units per line, signed: positive on sales, negative on "
        "cancellations and stock adjustments. Never sum it across line types without saying so.",
        "sql": "quantity",
    },
    {
        "id": "revenue_not_profit",
        "name": "Revenue is not profit",
        "definition": "The data has prices but no costs, so every revenue figure is sales value. "
        "Profit and margin cannot be calculated.",
        "sql": "",
    },
    {
        "id": "missing_customers",
        "name": "Missing customer IDs",
        "definition": "About a fifth of lines have no customer_id (has_customer = false). These "
        "lines are kept in revenue, country and product totals, but excluded from "
        "customer-level rankings. Answers about customers state how much revenue is unattributed.",
        "sql": "has_customer = false",
    },
    {
        "id": "non_product",
        "name": "Non-product lines",
        "definition": "Postage, fees, manual adjustments, discounts, samples, tests and gift "
        "vouchers have item_type <> 'PRODUCT'. They are excluded from product revenue and "
        "rankings and can be reported separately.",
        "sql": "item_type <> 'PRODUCT'",
    },
    {
        "id": "sheet_overlap",
        "name": "Worksheet overlap",
        "definition": "The workbook's two worksheets both contain 2010-12-01 to 2010-12-09. The "
        "second copy (22,523 identical rows) is removed during loading so that week is not "
        "double counted. It is the only removal and is reported in the Data Explorer.",
        "sql": "",
    },
    {
        "id": "no_silent_discard",
        "name": "No silent discarding",
        "definition": "Rows are classified (line_type, item_type, has_customer) rather than "
        "deleted. Exact duplicate rows within a worksheet are retained and counted in the Data "
        "Explorer because they cannot be proven to be errors.",
        "sql": "",
    },
]

DATASET_INFO = {
    "name": "Online Retail II",
    "source": "UCI Machine Learning Repository",
    "source_page": "https://archive.ics.uci.edu/dataset/502/online+retail+ii",
    "license": "CC BY 4.0",
    "description": "Transactions of a UK-based, registered non-store online retailer of gift-ware "
    "(many customers are wholesalers) between 2009-12-01 and 2011-12-09.",
    "currency": CURRENCY,
}
