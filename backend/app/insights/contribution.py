"""Descriptive contribution analysis: which categories account for a change in a metric.

For a current window C and comparison windows B1..Bk:
  comparison_value(cat) = sum over B of metric(cat) * scale
  scale = trading_days(C) / trading_days(B)      (equivalent-window adjustment)
  change(cat) = current_value(cat) - comparison_value(cat)
The changes of all categories (including "All other" and the missing-customer bucket) add up
exactly to the total change. A category absent from one side counts as 0 on that side.

This is descriptive arithmetic. It shows where a change is concentrated; it does not show why
it happened, and it is never presented as a cause.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.database.connection import run_query
from app.insights.anomalies import METRICS

DIMENSIONS: dict[str, dict[str, str]] = {
    "product": {"label": "Product", "key": "stock_code",
                "name": "ANY_VALUE(description)"},
    "country": {"label": "Country", "key": "COALESCE(country, '(unknown country)')", "name": "ANY_VALUE(country)"},
    "customer": {"label": "Customer", "key": "COALESCE(customer_id, '(missing customer ID)')",
                 "name": "ANY_VALUE(COALESCE(country, ''))"},
    "weekday": {"label": "Weekday", "key": "dayname(invoice_date)", "name": "ANY_VALUE(dayname(invoice_date))"},
}

# Metrics whose per-category values add up to the total for a dimension.
NON_ADDITIVE = {("orders", "product"): "An order can contain many products, so order counts by product do not add up "
                                          "to the total. Use net revenue or units sold for a product breakdown."}


class ContributionError(ValueError):
    pass


def _window_sql(windows: list[tuple[date, date]], params: list[Any]) -> str:
    parts = []
    for start, end in windows:
        parts.append("(invoice_date >= ? AND invoice_date < ?)")
        params.extend([start.isoformat(), end.isoformat()])
    return "(" + " OR ".join(parts) + ")"


def _trading_days(windows: list[tuple[date, date]]) -> int:
    params: list[Any] = []
    where = _window_sql(windows, params)
    res = run_query(f"SELECT COUNT(DISTINCT CAST(invoice_date AS DATE)) FROM transactions WHERE {where}", params)
    return int(res.rows[0][0] or 0)


def _display_sql(sql: str, params: list[Any]) -> str:
    """Inline parameters for display only (the query itself runs parameterised)."""
    out = sql
    for p in params:
        lit = str(p) if isinstance(p, (int, float)) else "'" + str(p).replace("'", "''") + "'"
        out = out.replace("?", lit, 1)
    return out


def contribution(metric: str, dimension: str, current: tuple[date, date], comparison: list[tuple[date, date]],
                 top_n: int = 10) -> dict:
    if metric not in METRICS:
        raise ContributionError(f"Unknown metric '{metric}'.")
    if dimension not in DIMENSIONS:
        raise ContributionError(f"Unknown dimension '{dimension}'.")
    if (metric, dimension) in NON_ADDITIVE:
        raise ContributionError(NON_ADDITIVE[(metric, dimension)])
    if not comparison:
        raise ContributionError("At least one comparison window is required.")
    for start, end in [current, *comparison]:
        if end <= start:
            raise ContributionError("Each window must end after it starts.")
    top_n = max(1, min(top_n, 50))

    cur_days = _trading_days([current])
    cmp_days = _trading_days(comparison)
    if cur_days == 0:
        raise ContributionError("The current window contains no transactions.")
    if cmp_days == 0:
        raise ContributionError("The comparison window contains no transactions.")
    scale = cur_days / cmp_days

    m_sql = METRICS[metric]["sql"]
    d = DIMENSIONS[dimension]
    params: list[Any] = []
    cur_where = _window_sql([current], params)
    cur_params = list(params)
    params = []
    cmp_where = _window_sql(comparison, params)
    cmp_params = list(params)
    sql = f"""WITH cur AS (
  SELECT {d['key']} AS category, {d['name']} AS name, {m_sql} AS value
  FROM transactions WHERE {cur_where}
  GROUP BY 1
),
cmp AS (
  SELECT {d['key']} AS category, {d['name']} AS name, ({m_sql}) * ? AS value
  FROM transactions WHERE {cmp_where}
  GROUP BY 1
)
SELECT COALESCE(cur.category, cmp.category) AS category,
       COALESCE(cur.name, cmp.name) AS name,
       COALESCE(cur.value, 0) AS current_value,
       COALESCE(cmp.value, 0) AS comparison_value,
       COALESCE(cur.value, 0) - COALESCE(cmp.value, 0) AS change
FROM cur FULL OUTER JOIN cmp ON cur.category IS NOT DISTINCT FROM cmp.category
ORDER BY abs(change) DESC"""
    all_params = cur_params + [scale] + cmp_params
    res = run_query(sql, all_params, max_rows=20000)
    rows = [dict(zip(res.columns, r)) for r in res.rows]

    total_current = sum(r["current_value"] or 0 for r in rows)
    total_comparison = sum(r["comparison_value"] or 0 for r in rows)
    total_change = total_current - total_comparison

    def share(change: float) -> float | None:
        return round(100 * change / total_change, 1) if abs(total_change) > 1e-9 else None

    top = rows[:top_n]
    rest = rows[top_n:]
    out_rows = [{
        "category": r["category"], "name": r["name"],
        "current_value": round(r["current_value"] or 0, 2), "comparison_value": round(r["comparison_value"] or 0, 2),
        "change": round(r["change"] or 0, 2), "share_of_change_pct": share(r["change"] or 0),
        "only_in": "current" if (r["comparison_value"] or 0) == 0 and (r["current_value"] or 0) != 0 else
                   ("comparison" if (r["current_value"] or 0) == 0 and (r["comparison_value"] or 0) != 0 else None),
    } for r in top]
    if rest:
        rest_change = sum(r["change"] or 0 for r in rest)
        out_rows.append({
            "category": f"All other ({len(rest):,})", "name": None,
            "current_value": round(sum(r["current_value"] or 0 for r in rest), 2),
            "comparison_value": round(sum(r["comparison_value"] or 0 for r in rest), 2),
            "change": round(rest_change, 2), "share_of_change_pct": share(rest_change), "only_in": None,
        })
    reconciled = abs(sum(r["change"] for r in out_rows) - total_change) < 0.05 + 1e-6 * abs(total_change)

    return {
        "metric": metric, "metric_label": METRICS[metric]["label"], "unit": METRICS[metric]["unit"],
        "dimension": dimension, "dimension_label": d["label"],
        "current_window": {"start": current[0].isoformat(), "end_exclusive": current[1].isoformat(), "trading_days": cur_days},
        "comparison_windows": [{"start": s.isoformat(), "end_exclusive": e.isoformat()} for s, e in comparison],
        "comparison_trading_days": cmp_days,
        "scale": round(scale, 6),
        "totals": {"current": round(total_current, 2), "comparison": round(total_comparison, 2), "change": round(total_change, 2)},
        "rows": out_rows,
        "categories_compared": len(rows),
        "positive_contributors": sum(1 for r in rows if (r["change"] or 0) > 0),
        "negative_contributors": sum(1 for r in rows if (r["change"] or 0) < 0),
        "reconciled": reconciled,
        "calculation": (
            f"change = current - comparison x {cur_days}/{cmp_days} trading days. Comparison values are scaled to "
            "the same number of trading days as the current window, so the windows are equivalent. Categories missing "
            "from one window count as 0 there. Contributions sum to the total change. An anomaly's expected value "
            "uses the median baseline week, which is robust to outliers but does not add up across categories, so the "
            "breakdown's comparison total can differ slightly from it."
        ),
        "sql": _display_sql(sql, all_params),
        "disclaimer": "Contribution analysis is descriptive: it shows where the change is concentrated, not why it "
                      "happened. It does not establish a cause.",
    }


def windows_for_anomaly(anomaly: dict) -> tuple[tuple[date, date], list[tuple[date, date]]]:
    start = date.fromisoformat(anomaly["period_start"])
    current = (start, start + timedelta(days=7))
    comparison = [(date.fromisoformat(w), date.fromisoformat(w) + timedelta(days=7)) for w in anomaly["baseline_weeks"]]
    return current, comparison
