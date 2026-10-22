from fastapi.testclient import TestClient

from app.agent import agent as agent_module
from app.agent.models import AgentPlan
from app.agent.providers import LLMProvider
from app.benchmarks.compare import compare_keyed, compare_scalar
from app.main import app
from tests.conftest import requires_data

client = TestClient(app)


def test_health_does_not_expose_credentials():
    body = client.get("/api/health").json()
    text = str(body).lower()
    assert "api_key" not in text and "sk-ant" not in text
    assert body["llm"]["provider"] == "offline"


def test_empty_question_is_400():
    r = client.post("/api/agent/query", json={"question": "   "})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_question"


def test_bad_conversation_id_is_422_without_trace():
    r = client.post("/api/agent/query", json={"question": "x", "conversation_id": "../../etc"})
    assert r.status_code == 422
    assert "Traceback" not in r.text


@requires_data
def test_clarification_then_answer_then_follow_up():
    first = client.post("/api/agent/query", json={"question": "Who are our best customers?"}).json()
    assert first["status"] == "clarification"
    assert len(first["clarification"]["options"]) >= 2
    cid = first["conversation_id"]
    second = client.post("/api/agent/query", json={"question": "", "conversation_id": cid,
                                                   "clarification_response": "Net revenue (sales minus cancellations)"}).json()
    assert second["status"] == "success"
    assert second["execution"]["validated"] is True
    assert "has_customer" in second["sql"]
    third = client.post("/api/agent/query", json={"question": "now only for Germany", "conversation_id": cid}).json()
    assert third["status"] == "success"
    assert "Germany" in third["sql"]
    hist = client.get("/api/history").json()
    assert hist["total"] == 3
    reopened = client.get(f"/api/history/{third['query_id']}").json()
    assert reopened["sql"] == third["sql"]


@requires_data
def test_unsupported_and_write_requests_are_not_executed():
    for q in ["What is our profit margin?", "Delete all cancelled invoices"]:
        r = client.post("/api/agent/query", json={"question": q}).json()
        assert r["status"] == "unsupported"
        assert r["sql"] is None


class _UnsafeProvider(LLMProvider):
    """Simulates a compromised / prompt-injected model that keeps returning a write query."""
    name = "fake"
    model = "fake"
    calls = 0

    def plan(self, system, user, context):
        _UnsafeProvider.calls += 1
        return AgentPlan(intent="analytical", sql="DROP TABLE transactions", explanation="x")


class _FixingProvider(LLMProvider):
    """Returns broken SQL first, then corrected SQL after receiving error feedback."""
    name = "fake"
    model = "fake"

    def plan(self, system, user, context):
        if context.error_feedback:
            return AgentPlan(intent="analytical", sql="SELECT COUNT(*) AS lines FROM transactions", explanation="fixed")
        return AgentPlan(intent="analytical", sql="SELECT COUNT(*) AS lines FROM transactions WHERE no_such_fn(quantity) > 0",
                         explanation="broken")


@requires_data
def test_unsafe_llm_output_is_rejected_after_one_regeneration(monkeypatch):
    _UnsafeProvider.calls = 0
    monkeypatch.setattr(agent_module, "get_provider", lambda: _UnsafeProvider())
    r = agent_module.answer_question("Give me revenue", record=False)
    assert r["status"] == "rejected"
    assert _UnsafeProvider.calls == 2  # original + exactly one regeneration
    assert r["rows"] == []


@requires_data
def test_execution_error_triggers_single_regeneration(monkeypatch):
    monkeypatch.setattr(agent_module, "get_provider", lambda: _FixingProvider())
    r = agent_module.answer_question("How many lines?", record=False)
    assert r["status"] == "success"
    assert r["execution"]["attempts"] == 2 and r["execution"]["regenerated"] is True
    assert r["rows"][0][0] > 1_000_000


@requires_data
def test_dashboard_kpis_are_consistent():
    k = client.get("/api/dashboard/summary").json()["kpis"]
    assert abs(k["gross_revenue"] - k["net_revenue"] - _product_cancelled()) < 1
    filtered = client.get("/api/dashboard/summary", params={"year": 2011, "country": "Germany"}).json()["kpis"]
    assert filtered["net_revenue"] < k["net_revenue"]


def _product_cancelled():
    from app.database.connection import run_query

    return -run_query("SELECT SUM(line_amount) FROM transactions WHERE line_type='CANCELLATION' AND item_type='PRODUCT'").rows[0][0]


@requires_data
def test_benchmark_runs_against_real_data():
    from app.benchmarks.runner import run_sync

    run = run_sync()
    assert run["status"] == "completed"
    assert len(run["results"]) >= 10
    s = run["summary"]
    assert s["clarification"]["total"] == 4
    assert s["multi_turn"]["total"] == 4
    assert s["security"]["total"] == len(run["security"]) >= 12
    assert all(p["passed"] for p in run["security"] if p["kind"] == "sql"), "a malicious SQL plan was not blocked"
    # Every analytical case must have a reference value computed from data.
    for r in run["results"]:
        if r["expect"] == "answer":
            assert r["expected"]["rows"], r["id"]


def test_compare_keyed_is_order_insensitive_and_tolerant():
    exp_cols = ["country", "rev"]
    exp_rows = [["UK", 100.0], ["DE", 50.0]]
    ok = compare_keyed(exp_cols, exp_rows, ["c", "r"], [["de", 50.001], ["uk", 100.0]], ["country"], ["rev"], None, 0.005, 0.51)
    assert ok.passed
    bad = compare_keyed(exp_cols, exp_rows, ["c", "r"], [["UK", 100.0], ["DE", 80.0]], ["country"], ["rev"], None, 0.005, 0.51)
    assert not bad.passed and "differ" in bad.reason
    top = compare_keyed(exp_cols, exp_rows, ["c", "r"], [["UK", 100.0], ["FR", 60.0]], ["country"], ["rev"], 2, 0.005, 0.51)
    assert not top.passed


def test_compare_scalar():
    assert compare_scalar({"v": 10.0}, ["x"], [[10.2]], ["v"], 0.05, 0.01).passed
    assert not compare_scalar({"v": 10.0}, ["x"], [[12.0]], ["v"], 0.005, 0.01).passed
    assert not compare_scalar({"v": 10.0}, ["x"], [], ["v"], 0.005, 0.01).passed


@requires_data
def test_query_timeout_interrupts_long_query():
    import pytest

    from app.database.connection import QueryTimeoutError, run_query

    with pytest.raises(QueryTimeoutError):
        run_query("SELECT COUNT(*) FROM transactions a, transactions b WHERE a.quantity + b.quantity = 7", timeout_s=0.5)


@requires_data
def test_result_row_limit():
    from app.database.connection import run_query

    res = run_query("SELECT invoice FROM transactions", max_rows=50)
    assert res.row_count == 50 and res.truncated


@requires_data
def test_connection_is_read_only_even_without_validator():
    """Defence in depth: the raw connection itself refuses writes, file reads and config changes."""
    import pytest

    from app.database.connection import QueryExecutionError, run_query

    for sql in ["DELETE FROM transactions", "CREATE TABLE x AS SELECT 1",
                "SELECT * FROM read_csv('C:/Windows/win.ini')", "SET enable_external_access = true"]:
        with pytest.raises(QueryExecutionError):
            run_query(sql)


@requires_data
def test_date_of_max_revenue_for_unnamed_product_asks_then_answers_each_reading():
    from app.database.connection import run_query

    q = "On which invoice date the product has generated maximum revenue"
    first = client.post("/api/agent/query", json={"question": q}).json()
    assert first["status"] == "clarification" and len(first["clarification"]["options"]) == 3
    cid = first["conversation_id"]
    answers = {}
    for option in first["clarification"]["options"]:
        r = client.post("/api/agent/query", json={"question": "", "conversation_id": cid,
                                                  "clarification_response": option}).json()
        assert r["status"] == "success", (option, r.get("error"))
        answers[option] = r

    net = "SUM(quantity * unit_price) FILTER (WHERE invoice LIKE 'C%' OR (quantity > 0 AND unit_price > 0 AND invoice NOT LIKE 'A%'))"
    best_day = run_query(f"SELECT CAST(invoice_date AS DATE)::VARCHAR, {net} AS n FROM transactions WHERE item_type = 'PRODUCT' "
                         "GROUP BY 1 ORDER BY n DESC LIMIT 1").rows[0]
    overall = answers["The single day with the highest revenue across all products"]
    assert overall["rows"][0][0] == best_day[0] and abs(overall["rows"][0][1] - best_day[1]) < 0.01

    best_pair = run_query(f"SELECT stock_code, CAST(invoice_date AS DATE)::VARCHAR, {net} AS n FROM transactions "
                          "WHERE item_type = 'PRODUCT' GROUP BY 1, 2 ORDER BY n DESC LIMIT 1").rows[0]
    pair = answers["The single product and day with the highest revenue"]["rows"][0]
    assert (pair[0], pair[2]) == (best_pair[0], best_pair[1]) and abs(pair[3] - best_pair[2]) < 0.01
    # The gross-sales trap: the largest same-day-cancelled order must not win.
    assert pair[0] != "23843"

    per_product = answers["The best day for each of the top 10 products"]
    assert per_product["row_count"] == 10
    assert len({row[0] for row in per_product["rows"]}) == 10


@requires_data
def test_unsupported_grouping_is_declined_not_answered_wrongly():
    r = client.post("/api/agent/query", json={"question": "Which weekday has the highest revenue?"}).json()
    assert r["status"] == "unsupported" and r["sql"] is None


def test_cte_alias_qualified_columns_pass_validation():
    from app.security.sql_validator import validate_sql

    validate_sql("WITH daily AS (SELECT stock_code, SUM(line_amount) AS n FROM transactions GROUP BY 1) "
                 "SELECT d.stock_code, d.n FROM daily AS d ORDER BY d.n DESC")
