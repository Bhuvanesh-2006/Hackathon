"""Trusted, hand-written queries for the dashboard and data explorer (parameterised, no LLM)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.database.connection import fetch_metadata, run_query

NET_COND = "line_type IN ('SALE','CANCELLATION') AND item_type = 'PRODUCT'"
NET = f"SUM(line_amount) FILTER (WHERE {NET_COND})"
GROSS = "SUM(line_amount) FILTER (WHERE line_type = 'SALE' AND item_type = 'PRODUCT')"


def _filters(year: int | None, country: str | None) -> tuple[str, list[Any]]:
    clauses, params = [], []
    if year:
        clauses.append("invoice_year = ?")
        params.append(year)
    if country:
        clauses.append("country = ?")
        params.append(country)
    return (" AND ".join(clauses) or "TRUE"), params


def _records(sql: str, params: list[Any]) -> list[dict]:
    res = run_query(sql, params, max_rows=5000)
    return [dict(zip(res.columns, r)) for r in res.rows]


@lru_cache(maxsize=64)
def dashboard_summary(year: int | None, country: str | None) -> dict:
    where, params = _filters(year, country)
    kpi = _records(
        f"""SELECT
              ROUND({GROSS}, 2) AS gross_revenue,
              ROUND({NET}, 2) AS net_revenue,
              ROUND(-SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION'), 2) AS cancelled_value,
              ROUND(-SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION' AND item_type = 'PRODUCT'), 2) AS product_cancelled_value,
              COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') AS orders,
              SUM(quantity) FILTER (WHERE line_type = 'SALE' AND item_type = 'PRODUCT') AS units_sold,
              COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'CANCELLATION') AS cancellation_invoices,
              -SUM(quantity) FILTER (WHERE line_type = 'CANCELLATION' AND item_type = 'PRODUCT') AS returned_units,
              COUNT(DISTINCT customer_id) FILTER (WHERE line_type = 'SALE') AS customers,
              ROUND(SUM(line_amount) FILTER (WHERE {NET_COND} AND NOT has_customer), 2) AS unattributed_net_revenue,
              COUNT(*) AS lines
            FROM transactions WHERE {where}""",
        params,
    )[0]
    trend = _records(
        f"""SELECT strftime(invoice_month, '%Y-%m') AS month,
                   ROUND({GROSS}, 2) AS gross_revenue,
                   ROUND({NET}, 2) AS net_revenue,
                   ROUND(-SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION' AND item_type = 'PRODUCT'), 2) AS cancelled_value,
                   COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') AS orders
            FROM transactions WHERE {where} GROUP BY 1 ORDER BY 1""",
        params,
    )
    top_products = _records(
        f"""SELECT stock_code, ANY_VALUE(description) AS description, ROUND({NET}, 2) AS net_revenue,
                   SUM(quantity) FILTER (WHERE line_type = 'SALE') AS units_sold
            FROM transactions WHERE {where} AND item_type = 'PRODUCT'
            GROUP BY stock_code ORDER BY net_revenue DESC NULLS LAST LIMIT 8""",
        params,
    )
    by_country = _records(
        f"""SELECT country, ROUND({NET}, 2) AS net_revenue,
                   COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') AS orders
            FROM transactions WHERE {where}
            GROUP BY country ORDER BY net_revenue DESC NULLS LAST LIMIT 10""",
        params,
    )
    line_types = _records(
        f"""SELECT line_type, COUNT(*) AS lines, ROUND(SUM(line_amount), 2) AS amount
            FROM transactions WHERE {where} GROUP BY 1 ORDER BY lines DESC""",
        params,
    )
    return {
        "filters": {"year": year, "country": country},
        "kpis": kpi,
        "revenue_trend": trend,
        "top_products": top_products,
        "sales_by_country": by_country,
        "line_types": line_types,
    }


@lru_cache(maxsize=1)
def filter_options() -> dict:
    years = [r["invoice_year"] for r in _records("SELECT DISTINCT invoice_year FROM transactions ORDER BY 1", [])]
    countries = [r["country"] for r in _records(
        "SELECT country FROM transactions GROUP BY country ORDER BY COUNT(*) DESC", [])]
    return {"years": years, "countries": countries}


@lru_cache(maxsize=1)
def dataset_profile() -> dict:
    from app.database.schema_catalog import COLUMNS

    meta = fetch_metadata()
    total = meta.get("row_count") or _records("SELECT COUNT(*) AS n FROM transactions", [])[0]["n"]
    missing_sql = ", ".join(f"COUNT(*) FILTER (WHERE {c['name']} IS NULL) AS \"{c['name']}\"" for c in COLUMNS)
    missing_row = _records(f"SELECT {missing_sql} FROM transactions", [])[0]
    distinct_sql = ", ".join(f"approx_count_distinct({c['name']}) AS \"{c['name']}\"" for c in COLUMNS)
    distinct_row = _records(f"SELECT {distinct_sql} FROM transactions", [])[0]
    columns = [
        {**c, "missing": missing_row[c["name"]], "missing_pct": round(100 * missing_row[c["name"]] / total, 2),
         "approx_distinct": distinct_row[c["name"]]}
        for c in COLUMNS
    ]
    line_types = _records(
        """SELECT line_type, COUNT(*) AS lines, COUNT(DISTINCT invoice) AS invoices,
                  SUM(quantity) AS quantity, ROUND(SUM(line_amount), 2) AS amount
           FROM transactions GROUP BY 1 ORDER BY lines DESC""", [])
    item_types = _records(
        """SELECT item_type, COUNT(*) AS lines, ROUND(SUM(line_amount), 2) AS amount,
                  string_agg(DISTINCT stock_code, ', ' ORDER BY stock_code) FILTER (WHERE item_type <> 'PRODUCT') AS codes
           FROM transactions GROUP BY 1 ORDER BY lines DESC""", [])
    cancel = _records(
        """SELECT COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'CANCELLATION') AS cancellation_invoices,
                  COUNT(*) FILTER (WHERE line_type = 'CANCELLATION') AS cancellation_lines,
                  -SUM(quantity) FILTER (WHERE line_type = 'CANCELLATION') AS cancelled_units,
                  ROUND(-SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION'), 2) AS cancelled_value,
                  COUNT(*) FILTER (WHERE quantity < 0) AS negative_quantity_lines,
                  COUNT(*) FILTER (WHERE quantity < 0 AND line_type = 'STOCK_ADJUSTMENT') AS negative_qty_stock_adjustments,
                  COUNT(*) FILTER (WHERE quantity < 0 AND line_type = 'CANCELLATION') AS negative_qty_cancellations,
                  COUNT(*) FILTER (WHERE NOT has_customer) AS lines_missing_customer,
                  COUNT(DISTINCT invoice) FILTER (WHERE NOT has_customer) AS invoices_missing_customer,
                  ROUND(SUM(line_amount) FILTER (WHERE {net} AND NOT has_customer), 2) AS net_revenue_missing_customer
           FROM transactions""".replace("{net}", NET_COND), [])[0]
    return {
        "metadata": meta,
        "row_count": total,
        "columns": columns,
        "line_types": line_types,
        "item_types": item_types,
        "quality": cancel,
    }


PREVIEW_COLUMNS = ["invoice", "invoice_date", "stock_code", "description", "quantity", "unit_price", "line_amount",
                   "customer_id", "country", "line_type", "item_type"]


def dataset_preview(limit: int, offset: int, line_type: str | None, item_type: str | None,
                    country: str | None, search: str | None) -> dict:
    clauses, params = [], []
    if line_type:
        clauses.append("line_type = ?")
        params.append(line_type)
    if item_type:
        clauses.append("item_type = ?")
        params.append(item_type)
    if country:
        clauses.append("country = ?")
        params.append(country)
    if search:
        clauses.append("(invoice ILIKE ? OR stock_code ILIKE ? OR description ILIKE ? OR customer_id = ?)")
        params += [f"%{search}%", f"%{search}%", f"%{search}%", search]
    where = " AND ".join(clauses) or "TRUE"
    total = _records(f"SELECT COUNT(*) AS n FROM transactions WHERE {where}", params)[0]["n"]
    res = run_query(
        f"SELECT {', '.join(PREVIEW_COLUMNS)} FROM transactions WHERE {where} "
        f"ORDER BY invoice_date, invoice, source_row LIMIT ? OFFSET ?",
        [*params, limit, offset], max_rows=limit,
    )
    return {"columns": res.columns, "rows": res.rows, "total": total, "limit": limit, "offset": offset}
