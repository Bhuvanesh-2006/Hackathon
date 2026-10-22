from datetime import date, timedelta

import pytest

from app.insights.anomalies import AnomalyConfig, Week, detect
from tests.conftest import requires_data


def _weeks(values: list[float], days: list[int] | None = None) -> list[Week]:
    start = date(2010, 1, 4)
    days = days or [6] * len(values)
    return [Week(start + timedelta(weeks=i), d, {"net_revenue": v * d, "units_sold": 100.0 * d, "orders": 50.0 * d,
                                                   "cancelled_value": 10.0 * d, "cancellation_rate": 0.05,
                                                   "gross_value": v * d})
            for i, (v, d) in enumerate(zip(values, days))]


def test_detects_injected_spike_and_drop_only_with_enough_history():
    base = [100 + (i % 3) for i in range(20)]
    base[12] = 300  # spike
    base[16] = 20  # drop
    base[3] = 900  # inside the first weeks: not enough history -> must not be flagged
    r = detect(AnomalyConfig(), _weeks(base))
    flagged = {(a["metric"], a["period_start"], a["kind"]) for a in r["anomalies"]}
    start = date(2010, 1, 4)
    assert ("net_revenue", (start + timedelta(weeks=12)).isoformat(), "spike") in flagged
    assert ("net_revenue", (start + timedelta(weeks=16)).isoformat(), "drop") in flagged
    assert not any(p == (start + timedelta(weeks=3)).isoformat() for _, p, _ in flagged)
    spike = next(a for a in r["anomalies"] if a["period_start"] == (start + timedelta(weeks=12)).isoformat())
    assert spike["expected"] > 0 and spike["observed"] > spike["expected"]
    assert len(spike["evidence"]) == len(spike["baseline_weeks"]) + 1


def test_short_weeks_are_skipped_not_flagged():
    vals = [100.0] * 15
    days = [6] * 15
    days[10] = 2  # e.g. Christmas closure: very low total, but only two trading days
    r = detect(AnomalyConfig(), _weeks(vals, days))
    assert not r["anomalies"]
    assert any("2 trading days" in s["reason"] for s in r["skipped_weeks"])


def test_per_day_normalisation_prevents_false_alert_on_short_week():
    vals = [100.0] * 15
    days = [6] * 15
    days[10] = 4  # shorter week, same daily sales
    r = detect(AnomalyConfig(), _weeks(vals, days))
    assert not any(a["metric"] == "net_revenue" for a in r["anomalies"])


def test_cancellation_drops_are_not_alerts():
    weeks = _weeks([100.0] * 15)
    for i, w in enumerate(weeks):
        w.values["cancelled_value"] = (0.0 if i == 12 else 10.0 + i % 2) * w.trading_days
    r = detect(AnomalyConfig(), weeks)
    assert not any(a["metric"] == "cancelled_value" for a in r["anomalies"])


@requires_data
def test_real_data_anomalies_are_documented_and_have_evidence():
    from app.insights.anomalies import cached_detection

    r = cached_detection()
    assert r["anomalies"], "expected at least one anomaly in two years of data"
    for a in r["anomalies"]:
        assert a["severity"] in ("high", "medium")
        assert abs(a["robust_z"]) >= r["config"]["z_medium"]
        assert a["trading_days"] >= r["config"]["min_trading_days"]
        assert a["evidence"][-1]["role"] == "observed"
    assert "not proven business causes" in r["disclaimer"]


@requires_data
def test_contribution_reconciles_and_handles_missing_categories():
    from app.insights.anomalies import cached_detection
    from app.insights.contribution import contribution, windows_for_anomaly

    a = next(x for x in cached_detection()["anomalies"] if x["metric"] == "cancelled_value")
    cur, cmp = windows_for_anomaly(a)
    for dim in ("product", "country", "customer", "weekday"):
        r = contribution("cancelled_value", dim, cur, cmp, top_n=5)
        assert r["reconciled"], dim
        assert abs(sum(x["change"] for x in r["rows"]) - r["totals"]["change"]) < 0.1
        # Observed value for the anomaly week must equal the breakdown's current total.
        assert abs(r["totals"]["current"] - a["observed"]) < 0.05
    cust = contribution("cancelled_value", "customer", cur, cmp, top_n=50)
    assert any(x["category"] == "(missing customer ID)" for x in cust["rows"])
    assert any(x["only_in"] in ("current", "comparison") for x in cust["rows"])
    assert cust["negative_contributors"] > 0


@requires_data
def test_contribution_independent_check_for_month_over_month():
    from app.database.connection import run_query
    from app.insights.contribution import contribution

    r = contribution("net_revenue", "country", (date(2011, 11, 1), date(2011, 12, 1)), [(date(2011, 10, 1), date(2011, 11, 1))])
    days = run_query("SELECT COUNT(DISTINCT CAST(invoice_date AS DATE)) FILTER (WHERE invoice_date >= '2011-11-01' AND invoice_date < '2011-12-01'), "
                     "COUNT(DISTINCT CAST(invoice_date AS DATE)) FILTER (WHERE invoice_date >= '2011-10-01' AND invoice_date < '2011-11-01') FROM transactions").rows[0]
    raw = run_query("SELECT SUM(quantity*unit_price) FILTER (WHERE invoice_date >= '2011-11-01' AND invoice_date < '2011-12-01'), "
                    "SUM(quantity*unit_price) FILTER (WHERE invoice_date >= '2011-10-01' AND invoice_date < '2011-11-01') "
                    "FROM transactions WHERE item_type = 'PRODUCT' AND line_type IN ('SALE','CANCELLATION')").rows[0]
    assert abs(r["totals"]["current"] - raw[0]) < 0.05
    assert abs(r["totals"]["comparison"] - raw[1] * days[0] / days[1]) < 0.05


@requires_data
def test_non_additive_breakdown_is_refused():
    from app.insights.contribution import ContributionError, contribution

    with pytest.raises(ContributionError):
        contribution("orders", "product", (date(2011, 11, 1), date(2011, 12, 1)), [(date(2011, 10, 1), date(2011, 11, 1))])


@requires_data
def test_forecast_uses_time_split_and_beats_or_reports_naive():
    from app.insights.forecast import HOLDOUT_MONTHS, build_forecast

    r = build_forecast()
    assert r["available"]
    months = [h["month"] for h in r["history"]]
    assert "2011-12" not in months  # partial month excluded from fitting
    assert r["holdout_period"][1] == months[-1]
    assert r["train_period"][1] < r["holdout_period"][0]  # train strictly before test
    for e in r["evaluation"]:
        assert len(e["holdout"]) == HOLDOUT_MONTHS
    best = min(r["evaluation"], key=lambda e: e["mae"])
    assert r["selected_method"] == best["method"]
    assert all(f["low"] <= f["forecast"] <= f["high"] for f in r["forecast"])
