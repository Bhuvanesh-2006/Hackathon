"""Proactive anomaly detection on weekly sales metrics.

Method (deliberately interpretable, documented in README "Anomaly detection"):

* Aggregate each metric by ISO week (Monday start) and divide by the number of trading days
  in that week (days with at least one invoice). The shop does not trade on Saturdays and
  closes over Christmas, so raw weekly totals would flag every short week.
* Weeks with fewer than MIN_TRADING_DAYS trading days are not evaluated and are not used in
  baselines (insufficient coverage).
* Baseline = median of the per-day value over the previous BASELINE_WEEKS eligible weeks
  (looking back at most MAX_LOOKBACK_WEEKS calendar weeks). Spread = 1.4826 * MAD.
  At least MIN_BASELINE_WEEKS eligible weeks are required, otherwise the week is skipped.
* robust z = (observed_per_day - baseline_per_day) / spread. A week is flagged when
  |robust z| >= Z_MEDIUM and the relative change >= MIN_RELATIVE_CHANGE.
  Severity: "high" when |z| >= Z_HIGH, else "medium". Thresholds live in AnomalyConfig.
* Seasonal context: when the same ISO week exists one year earlier, its own robust z is
  computed the same way. If it deviated in the same direction, the alert is marked as a
  possibly recurring seasonal pattern.

Isolation Forest is not used: with ~100 weekly points per metric it cannot be validated
meaningfully, and its scores are not interpretable for a business user.

Anomalies are potential issues in the data, never proven business causes.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from app.database.connection import run_query

METRICS: dict[str, dict[str, Any]] = {
    "net_revenue": {
        "label": "Net revenue", "unit": "GBP", "directions": ("up", "down"), "rule": "net_revenue",
        "sql": "SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION') AND item_type = 'PRODUCT')",
    },
    "units_sold": {
        "label": "Units sold", "unit": "units", "directions": ("up", "down"), "rule": "units_sold",
        "sql": "SUM(quantity) FILTER (WHERE line_type = 'SALE' AND item_type = 'PRODUCT')",
    },
    "orders": {
        "label": "Orders", "unit": "orders", "directions": ("up", "down"), "rule": "orders",
        "sql": "COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE')",
    },
    "cancelled_value": {
        "label": "Cancelled value", "unit": "GBP", "directions": ("up",), "rule": "cancellations",
        "sql": "-SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION')",
    },
}


@dataclass(frozen=True)
class AnomalyConfig:
    baseline_weeks: int = 8
    min_baseline_weeks: int = 6
    max_lookback_weeks: int = 12
    min_trading_days: int = 4
    z_medium: float = 3.5
    z_high: float = 5.0
    min_relative_change: float = 0.25


DEFAULT_CONFIG = AnomalyConfig()

WEEKLY_SQL = f"""
SELECT
  CAST(date_trunc('week', invoice_date) AS DATE) AS week_start,
  COUNT(DISTINCT CAST(invoice_date AS DATE)) AS trading_days,
  {METRICS['net_revenue']['sql']} AS net_revenue,
  {METRICS['units_sold']['sql']} AS units_sold,
  {METRICS['orders']['sql']} AS orders,
  {METRICS['cancelled_value']['sql']} AS cancelled_value,
  SUM(line_amount) FILTER (WHERE line_type = 'SALE') AS gross_value
FROM transactions
GROUP BY 1
ORDER BY 1
""".strip()


@dataclass
class Week:
    week_start: date
    trading_days: int
    values: dict[str, float | None]


@dataclass
class Anomaly:
    id: str
    metric: str
    metric_label: str
    unit: str
    kind: str  # spike | drop
    severity: str  # high | medium
    period_start: str
    period_end: str
    trading_days: int
    observed: float
    expected: float
    deviation: float
    deviation_pct: float | None
    robust_z: float
    baseline_weeks: list[str]
    baseline_per_day: float | None
    seasonal: dict | None
    evidence: list[dict]
    notes: list[str] = field(default_factory=list)


def _to_date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def load_weeks() -> list[Week]:
    res = run_query(WEEKLY_SQL, max_rows=1000)
    weeks: list[Week] = []
    for row in res.rows:
        rec = dict(zip(res.columns, row))
        gross = rec.pop("gross_value") or 0.0
        cancelled = rec.get("cancelled_value") or 0.0
        values = {k: (float(rec[k]) if rec[k] is not None else 0.0) for k in ("net_revenue", "units_sold", "orders", "cancelled_value")}
        values["gross_value"] = gross
        values["cancellation_rate"] = (cancelled / gross) if gross > 0 else None
        weeks.append(Week(_to_date(rec["week_start"]), int(rec["trading_days"]), values))
    return weeks


def _per_day(metric: str, week: Week) -> float | None:
    v = week.values.get(metric)
    if v is None:
        return None
    return v / week.trading_days if week.trading_days else None


def _scale(metric: str, per_day: float, trading_days: int) -> float:
    return per_day * trading_days


def _robust_stats(values: list[float]) -> tuple[float, float]:
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    spread = 1.4826 * mad
    if spread == 0:
        # All baseline values identical: fall back to a small fraction of the level to avoid
        # division by zero; such weeks rarely occur in this data.
        spread = abs(med) * 0.05 or 1.0
    return med, spread


def _baseline(metric: str, weeks: list[Week], idx: int, cfg: AnomalyConfig) -> tuple[list[Week], str | None]:
    current = weeks[idx].week_start
    earliest = current - timedelta(weeks=cfg.max_lookback_weeks)
    chosen: list[Week] = []
    for w in reversed(weeks[:idx]):
        if w.week_start < earliest:
            break
        if w.trading_days >= cfg.min_trading_days and _per_day(metric, w) is not None:
            chosen.append(w)
        if len(chosen) == cfg.baseline_weeks:
            break
    if len(chosen) < cfg.min_baseline_weeks:
        return chosen, f"only {len(chosen)} eligible baseline weeks (minimum {cfg.min_baseline_weeks})"
    return list(reversed(chosen)), None


def _score(metric: str, weeks: list[Week], idx: int, cfg: AnomalyConfig) -> dict | None:
    w = weeks[idx]
    obs = _per_day(metric, w)
    if obs is None or w.trading_days < cfg.min_trading_days:
        return None
    base, problem = _baseline(metric, weeks, idx, cfg)
    if problem:
        return None
    vals = [_per_day(metric, b) for b in base]
    med, spread = _robust_stats([v for v in vals if v is not None])
    z = (obs - med) / spread
    rel = (obs - med) / abs(med) if med else None
    return {"z": z, "rel": rel, "median": med, "baseline": base, "observed_per_day": obs}


def detect(cfg: AnomalyConfig = DEFAULT_CONFIG, weeks: list[Week] | None = None) -> dict:
    weeks = weeks if weeks is not None else load_weeks()
    by_start = {w.week_start: i for i, w in enumerate(weeks)}
    anomalies: list[Anomaly] = []
    skipped: list[dict] = []

    for metric, meta in METRICS.items():
        for idx, w in enumerate(weeks):
            if w.trading_days < cfg.min_trading_days:
                if metric == "net_revenue":
                    skipped.append({"week_start": w.week_start.isoformat(), "reason":
                                    f"{w.trading_days} trading days (minimum {cfg.min_trading_days})"})
                continue
            base, problem = _baseline(metric, weeks, idx, cfg)
            if problem:
                if metric == "net_revenue":
                    skipped.append({"week_start": w.week_start.isoformat(), "reason": f"insufficient history: {problem}"})
                continue
            s = _score(metric, weeks, idx, cfg)
            if s is None:
                continue
            z, rel = s["z"], s["rel"]
            direction = "up" if z > 0 else "down"
            if direction not in meta["directions"]:
                continue
            if abs(z) < cfg.z_medium or rel is None or abs(rel) < cfg.min_relative_change:
                continue

            seasonal = None
            ly = by_start.get(w.week_start - timedelta(weeks=52))
            if ly is not None:
                s_ly = _score(metric, weeks, ly, cfg)
                if s_ly is not None:
                    recurring = abs(s_ly["z"]) >= cfg.z_medium and (s_ly["z"] > 0) == (z > 0)
                    seasonal = {
                        "last_year_week": weeks[ly].week_start.isoformat(),
                        "last_year_observed": round(weeks[ly].values[metric] or 0.0, 4),
                        "last_year_robust_z": round(s_ly["z"], 2),
                        "recurring": recurring,
                    }

            expected = _scale(metric, s["median"], w.trading_days)
            observed = w.values[metric] or 0.0
            notes = []
            if seasonal and seasonal["recurring"]:
                notes.append("The same week last year deviated in the same direction: this may be a recurring "
                             "seasonal pattern rather than an isolated event.")
            if seasonal is None:
                notes.append("No comparable week one year earlier, so seasonality cannot be checked.")
            if metric == "cancelled_value":
                base_rates = [b.values["cancellation_rate"] for b in s["baseline"] if b.values["cancellation_rate"] is not None]
                rate = w.values["cancellation_rate"]
                if rate is not None and base_rates:
                    notes.append(f"Cancellation rate (cancelled value / gross sales) was {rate * 100:.1f}% this week "
                                 f"vs a baseline median of {statistics.median(base_rates) * 100:.1f}%.")
            if w.week_start + timedelta(days=6) >= date(2011, 12, 9):
                notes.append("This is the final week of the dataset (data ends 2011-12-09).")
            evidence = [
                {"week_start": b.week_start.isoformat(), "trading_days": b.trading_days,
                 "value": round(b.values[metric] or 0.0, 4), "per_day": round(_per_day(metric, b) or 0.0, 4),
                 "role": "baseline"}
                for b in s["baseline"]
            ] + [{"week_start": w.week_start.isoformat(), "trading_days": w.trading_days,
                  "value": round(observed, 4), "per_day": round(s["observed_per_day"], 4), "role": "observed"}]
            anomalies.append(Anomaly(
                id=f"{metric}-{w.week_start.isoformat()}", metric=metric, metric_label=meta["label"], unit=meta["unit"],
                kind="spike" if z > 0 else "drop",
                severity="high" if abs(z) >= cfg.z_high else "medium",
                period_start=w.week_start.isoformat(), period_end=(w.week_start + timedelta(days=6)).isoformat(),
                trading_days=w.trading_days, observed=round(observed, 4), expected=round(expected, 4),
                deviation=round(observed - expected, 4), deviation_pct=round(rel * 100, 1) if rel is not None else None,
                robust_z=round(z, 2), baseline_weeks=[b.week_start.isoformat() for b in s["baseline"]],
                baseline_per_day=round(s["median"], 4), seasonal=seasonal, evidence=evidence, notes=notes,
            ))

    anomalies.sort(key=lambda a: (a.severity != "high", -abs(a.robust_z)))
    series = {
        m: [{"week_start": w.week_start.isoformat(), "trading_days": w.trading_days,
             "value": None if w.values[m] is None else round(w.values[m], 4)} for w in weeks]
        for m in METRICS
    }
    return {
        "config": asdict(cfg),
        "method": "Weekly robust z-score (median/MAD) on per-trading-day values against the previous "
                  f"{cfg.baseline_weeks} eligible weeks; seasonal check against the same week one year earlier.",
        "metrics": {k: {"label": v["label"], "unit": v["unit"], "directions": list(v["directions"])} for k, v in METRICS.items()},
        "anomalies": [asdict(a) for a in anomalies],
        "skipped_weeks": skipped,
        "weeks_analysed": len(weeks),
        "series": series,
        "sql": WEEKLY_SQL,
        "disclaimer": "Anomalies are statistical deviations from recent history. They are potential issues "
                      "to investigate, not proven business causes.",
    }


@lru_cache(maxsize=1)
def cached_detection() -> dict:
    return detect()


def find(anomaly_id: str) -> dict | None:
    return next((a for a in cached_detection()["anomalies"] if a["id"] == anomaly_id), None)


def is_finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))
