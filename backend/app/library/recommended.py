"""Recommended (built-in) queries, generated per dataset from its actual schema.

Built-in retail dataset: curated SQL that follows the documented business rules.
Imported datasets: generated from detected column roles (numeric / text / date) and validated
against the dataset's schema before being offered. Nothing is called "revenue" unless a column of
that dataset directly contains it; cancellation/return queries only exist for the built-in dataset,
whose definitions are verified.
"""
from __future__ import annotations

import re
from typing import Any

from app.datasets import execution, registry
from app.security.sql_validator import SQLValidationError

NET = "SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION'))"

BUILTIN: list[dict[str, Any]] = [
    {"id": "rec_top5_products_revenue", "category": "Products", "title": "Top 5 products by net revenue",
     "question": "Which 5 products generated the highest net revenue?",
     "description": "Net revenue = sales minus cancellations, product lines only (GBP).",
     "sql": f"SELECT stock_code, ANY_VALUE(description) AS description, ROUND({NET}, 2) AS net_revenue_gbp\n"
            "FROM transactions WHERE item_type = 'PRODUCT'\nGROUP BY stock_code ORDER BY net_revenue_gbp DESC LIMIT 5"},
    {"id": "rec_monthly_revenue", "category": "Trends", "title": "Monthly net revenue trend",
     "question": "What is the monthly net revenue trend?",
     "description": "Net product revenue per month. December 2011 is partial.",
     "sql": f"SELECT strftime(invoice_month, '%Y-%m') AS month, ROUND({NET}, 2) AS net_revenue_gbp\n"
            "FROM transactions WHERE item_type = 'PRODUCT'\nGROUP BY month ORDER BY month"},
    {"id": "rec_best_sellers_units", "category": "Products", "title": "Best-selling products by quantity",
     "question": "Which products sold the most units?",
     "description": "Units on sale lines of products (before cancellations).",
     "sql": "SELECT stock_code, ANY_VALUE(description) AS description, SUM(quantity) AS units_sold\n"
            "FROM transactions WHERE line_type = 'SALE' AND item_type = 'PRODUCT'\nGROUP BY stock_code ORDER BY units_sold DESC LIMIT 10"},
    {"id": "rec_sales_by_country", "category": "Geography", "title": "Net revenue by country",
     "question": "What is the net revenue by country?", "description": "Net product revenue per country (GBP).",
     "sql": f"SELECT country, ROUND({NET}, 2) AS net_revenue_gbp, COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') AS orders\n"
            "FROM transactions WHERE item_type = 'PRODUCT'\nGROUP BY country ORDER BY net_revenue_gbp DESC"},
    {"id": "rec_top_customers", "category": "Customers", "title": "Top customers by spending",
     "question": "Which customers spent the most (net)?",
     "description": "Net product revenue per known customer; lines without a customer ID are excluded.",
     "sql": f"SELECT customer_id, ANY_VALUE(country) AS country, ROUND({NET}, 2) AS net_revenue_gbp\n"
            "FROM transactions WHERE item_type = 'PRODUCT' AND has_customer\nGROUP BY customer_id ORDER BY net_revenue_gbp DESC LIMIT 10"},
    {"id": "rec_cancellations_monthly", "category": "Returns", "title": "Cancellations and returns by month",
     "question": "How many cancellation invoices and how much value were cancelled each month?",
     "description": "'C' invoices (cancellations and returns cannot be told apart in this data); value shown as positive GBP.",
     "sql": "SELECT strftime(invoice_month, '%Y-%m') AS month, COUNT(DISTINCT invoice) AS cancellation_invoices,\n"
            "       ROUND(-SUM(line_amount), 2) AS cancelled_value_gbp, -SUM(quantity) AS cancelled_units\n"
            "FROM transactions WHERE line_type = 'CANCELLATION'\nGROUP BY month ORDER BY month"},
    {"id": "rec_top_products_in_country", "category": "Geography", "title": "Top N products in a country",
     "question": "Which products generated the most net revenue in a given country?",
     "description": "Parameterised: choose the country and how many products to list.",
     "sql": f"SELECT stock_code, ANY_VALUE(description) AS description, ROUND({NET}, 2) AS net_revenue_gbp\n"
            "FROM transactions WHERE item_type = 'PRODUCT' AND country = {{country}}\n"
            "GROUP BY stock_code ORDER BY net_revenue_gbp DESC LIMIT {{top_n}}",
     "parameters": [{"name": "country", "type": "text", "default": "Germany", "description": "Country name as in the data"},
                    {"name": "top_n", "type": "integer", "default": 10, "description": "Number of products"}]},
]

PRODUCT = re.compile(r"(product|item|sku|description|article|title|name)")
CUSTOMER = re.compile(r"(customer|client|buyer|account|user)")
GEO = re.compile(r"(country|region|city|state|province|territory|location|market)")
MONEY = re.compile(r"(revenue|sales|amount|total|price|spend|value|cost)")
QTY = re.compile(r"(qty|quantity|units|count|volume)")


def _category(col: str) -> str:
    return ("Products" if PRODUCT.search(col) else "Customers" if CUSTOMER.search(col)
            else "Geography" if GEO.search(col) else "General")


def generated(ds: dict[str, Any]) -> list[dict[str, Any]]:
    cols = ds["columns"]
    t = ds["table"]
    numeric = [c["name"] for c in cols if c.get("role") == "numeric"]
    texts = [c for c in cols if c.get("role") == "text" and 1 < (c.get("approx_distinct") or 0) <= 1000]
    dates = [c["name"] for c in cols if c.get("role") == "date"]
    money = [n for n in numeric if MONEY.search(n)]
    qty = [n for n in numeric if QTY.search(n)]
    measure = (money or qty or numeric or [None])[0]
    texts.sort(key=lambda c: (0 if PRODUCT.search(c["name"]) or GEO.search(c["name"]) or CUSTOMER.search(c["name"]) else 1))
    out: list[dict[str, Any]] = [{
        "id": "rec_row_count", "category": "General", "title": "Row count", "question": "How many rows does the dataset have?",
        "description": "Number of rows imported.", "sql": f"SELECT COUNT(*) AS row_count FROM {t}"}]
    if measure:
        out.append({"id": f"rec_summary_{measure}", "category": "Revenue" if measure in money else "General",
                    "title": f"Summary of {measure}", "question": f"What are the total, average, minimum and maximum of {measure}?",
                    "description": f"Aggregates of the numeric column {measure}.",
                    "sql": f"SELECT ROUND(SUM({measure}), 2) AS total_{measure}, ROUND(AVG({measure}), 2) AS average_{measure},\n"
                           f"       MIN({measure}) AS min_{measure}, MAX({measure}) AS max_{measure}, COUNT({measure}) AS non_missing\nFROM {t}"})
    for c in texts[:2]:
        g = c["name"]
        if measure:
            out.append({"id": f"rec_top_{g}_by_{measure}", "category": _category(g),
                        "title": f"Top 10 {g} by total {measure}", "question": f"Which {g} values have the highest total {measure}?",
                        "description": f"Ranks {g} by SUM({measure}). Uses only existing columns.",
                        "sql": f"SELECT {g}, ROUND(SUM({measure}), 2) AS total_{measure}, COUNT(*) AS rows\nFROM {t}\n"
                               f"GROUP BY {g} ORDER BY total_{measure} DESC NULLS LAST LIMIT 10"})
        out.append({"id": f"rec_rows_by_{g}", "category": _category(g), "title": f"Rows by {g}",
                    "question": f"How many rows are there per {g}?", "description": f"Row count per {g} value.",
                    "sql": f"SELECT {g}, COUNT(*) AS rows FROM {t}\nGROUP BY {g} ORDER BY rows DESC LIMIT 20"})
    if qty and texts and qty[0] != measure:
        g = texts[0]["name"]
        out.append({"id": f"rec_best_{g}_by_{qty[0]}", "category": _category(g), "title": f"Best-selling {g} by {qty[0]}",
                    "question": f"Which {g} have the highest total {qty[0]}?", "description": f"Ranks {g} by SUM({qty[0]}).",
                    "sql": f"SELECT {g}, SUM({qty[0]}) AS total_{qty[0]} FROM {t}\nGROUP BY {g} ORDER BY total_{qty[0]} DESC NULLS LAST LIMIT 10"})
    if dates:
        d = dates[0]
        if measure:
            out.append({"id": f"rec_monthly_{measure}", "category": "Trends", "title": f"Monthly total {measure}",
                        "question": f"What is the monthly total of {measure}?", "description": f"SUM({measure}) per month of {d}.",
                        "sql": f"SELECT date_trunc('month', {d}) AS month, ROUND(SUM({measure}), 2) AS total_{measure}\nFROM {t}\n"
                               f"WHERE {d} IS NOT NULL GROUP BY month ORDER BY month"})
        else:
            out.append({"id": f"rec_monthly_rows_{d}", "category": "Trends", "title": f"Rows per month of {d}",
                        "question": f"How many rows are there per month of {d}?", "description": "Row count per month.",
                        "sql": f"SELECT date_trunc('month', {d}) AS month, COUNT(*) AS rows FROM {t}\n"
                               f"WHERE {d} IS NOT NULL GROUP BY month ORDER BY month"})
    return out


def recommended(ds: dict[str, Any]) -> list[dict[str, Any]]:
    """Recommended queries for a dataset, each validated against its schema."""
    from app.library.store import render

    items = BUILTIN if registry.is_builtin(ds) else generated(ds)
    out = []
    for item in items:
        params = item.get("parameters", [])
        try:
            execution.validate_for(ds, render(item["sql"], params, None))
        except (SQLValidationError, Exception):
            continue
        out.append({**item, "parameters": params, "tags": [], "builtin": True, "dataset_id": ds["id"],
                    "dataset_name": ds["name"], "compatibility": {"status": "compatible", "reason": "Generated for this dataset's schema."}})
    return out
