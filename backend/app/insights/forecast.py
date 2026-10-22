"""Small, transparent monthly net-revenue forecast.

Only full calendar months are used (December 2011 ends on the 9th and is excluded from fitting).
That leaves 24 months, i.e. two seasonal cycles, so the forecast is a rough estimate.

Candidates (all simple, all explainable):
  * naive            - next month equals the last observed month
  * seasonal_naive   - next month equals the same month one year earlier
  * seasonal_drift   - seasonal naive x year-over-year growth of the last 3 months
Evaluation: time-based split. Fit on months before the holdout, forecast the last
HOLDOUT_MONTHS months in one shot, report MAE and MAPE per method. The method with the lowest
holdout MAE is refitted on all full months and projects HORIZON months ahead.
Range: point forecast x (1 +/- the largest absolute percentage error seen on the holdout). With
6 holdout errors this is a rough range, not a statistical prediction interval.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache

from app.database.connection import run_query

HOLDOUT_MONTHS = 6
HORIZON = 3
MONTHLY_SQL = """
SELECT strftime(invoice_month, '%Y-%m') AS month,
       SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION') AND item_type = 'PRODUCT') AS net_revenue,
       MAX(invoice_date) AS last_invoice
FROM transactions
GROUP BY 1
ORDER BY 1
""".strip()


def _add_months(ym: str, k: int) -> str:
    y, m = map(int, ym.split("-"))
    idx = y * 12 + (m - 1) + k
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _predict(method: str, history: dict[str, float], months: list[str], target: str) -> float | None:
    last = months[-1]
    if method == "naive":
        return history[last]
    ly = _add_months(target, -12)
    if ly not in history:
        return None
    if method == "seasonal_naive":
        return history[ly]
    recent = [months[-i] for i in range(1, 4)]
    prior = [_add_months(m, -12) for m in recent]
    if not all(p in history for p in prior):
        return None
    growth = sum(history[m] for m in recent) / sum(history[p] for p in prior)
    return history[ly] * growth


METHODS = {
    "naive": "Last observed month repeated",
    "seasonal_naive": "Same month one year earlier",
    "seasonal_drift": "Same month one year earlier x year-over-year growth of the last 3 months",
}


def build_forecast() -> dict:
    res = run_query(MONTHLY_SQL)
    rows = [dict(zip(res.columns, r)) for r in res.rows]
    if not rows:
        return {"available": False, "reason": "No data loaded."}
    last_date = date.fromisoformat(str(rows[-1]["last_invoice"])[:10])
    partial_month = rows[-1]["month"] if last_date.day < 28 else None
    full = [r for r in rows if r["month"] != partial_month]
    history = {r["month"]: float(r["net_revenue"] or 0) for r in full}
    months = [r["month"] for r in full]
    if len(months) < 12 + HOLDOUT_MONTHS + 3:
        return {"available": False, "reason": f"Only {len(months)} full months; at least {12 + HOLDOUT_MONTHS + 3} are needed."}

    train_months = months[:-HOLDOUT_MONTHS]
    test_months = months[-HOLDOUT_MONTHS:]
    train = {m: history[m] for m in train_months}
    evaluation = []
    for method in METHODS:
        preds = [_predict(method, train, train_months, t) for t in test_months]
        if any(p is None for p in preds):
            continue
        errors = [p - history[t] for p, t in zip(preds, test_months)]
        ape = [abs(e) / abs(history[t]) for e, t in zip(errors, test_months) if history[t]]
        evaluation.append({
            "method": method, "description": METHODS[method],
            "mae": round(sum(abs(e) for e in errors) / len(errors), 2),
            "mape_pct": round(100 * sum(ape) / len(ape), 1),
            "max_ape_pct": round(100 * max(ape), 1),
            "holdout": [{"month": t, "actual": round(history[t], 2), "predicted": round(p, 2)} for t, p in zip(test_months, preds)],
        })
    best = min(evaluation, key=lambda e: e["mae"])
    naive = next(e for e in evaluation if e["method"] == "naive")

    band = best["max_ape_pct"] / 100
    future = []
    hist = dict(history)
    hist_months = list(months)
    for k in range(1, HORIZON + 1):
        target = _add_months(months[-1], k)
        p = _predict(best["method"], hist, months, target)
        if p is None:
            break
        future.append({"month": target, "forecast": round(p, 2), "low": round(p * (1 - band), 2), "high": round(p * (1 + band), 2)})
    partial_actual = None
    if partial_month:
        partial_actual = {"month": partial_month, "net_revenue_to_date": round(float(rows[-1]["net_revenue"] or 0), 2),
                          "through": last_date.isoformat()}
    return {
        "available": True,
        "metric": "Monthly net revenue (GBP)",
        "history": [{"month": m, "actual": round(history[m], 2)} for m in hist_months],
        "partial_month": partial_actual,
        "train_period": [train_months[0], train_months[-1]],
        "holdout_period": [test_months[0], test_months[-1]],
        "evaluation": evaluation,
        "selected_method": best["method"],
        "selected_description": best["description"],
        "improvement_vs_naive_pct": round(100 * (1 - best["mae"] / naive["mae"]), 1) if naive["mae"] else None,
        "forecast": future,
        "range_note": f"Range = forecast +/- {best['max_ape_pct']}%, the largest error of the selected method on the "
                      f"{HOLDOUT_MONTHS}-month holdout. It is a rough range, not a statistical prediction interval.",
        "limitations": [
            f"Only {len(months)} full months (two seasonal cycles); seasonal effects are estimated from a single prior year.",
            "December 2011 is partial (data ends 9 Dec) and is excluded from fitting.",
            "Forecasts are estimates, not actual results. No promotions, prices or external factors are modelled.",
        ],
        "sql": MONTHLY_SQL,
    }


@lru_cache(maxsize=1)
def cached_forecast() -> dict:
    return build_forecast()
