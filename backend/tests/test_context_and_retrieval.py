import difflib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.agent.context import ConversationState, extract_filters, parse_comparison
from app.main import app
from tests.conftest import requires_data

client = TestClient(app)


def test_extract_filters_reads_where_not_aggregate_filters():
    sql = ("SELECT country, SUM(line_amount) FILTER (WHERE invoice_month = DATE '2011-11-01') AS nov FROM transactions "
           "WHERE country = 'Germany' AND invoice_year = 2011 AND invoice_date >= TIMESTAMP '2011-01-01' "
           "AND invoice_date < TIMESTAMP '2011-07-01' AND stock_code IN ('22423', '85123a') GROUP BY country")
    f = extract_filters(sql)
    assert f == {"country": "Germany", "year": 2011, "date_from": "2011-01-01", "date_to": "2011-07-01",
                 "stock_codes": ["22423", "85123A"]}


def test_parse_comparison_equal_windows():
    c = parse_comparison("December 2011 (1-9 Dec, partial) vs November 2011 (1-9 Nov)")
    assert c.current == ("2011-12-01", "2011-12-10") and c.previous == ("2011-11-01", "2011-11-10")


@requires_data
def test_follow_up_sequence_keeps_context_and_shows_active_filters():
    def ask(q, cid=None, clar=None):
        return client.post("/api/agent/query", json={"question": q, "conversation_id": cid, "clarification_response": clar}).json()

    r1 = ask("Which products generated the most revenue?")
    cid = r1["conversation_id"]
    r2 = ask("Only in the UK", cid)
    assert r2["status"] == "success" and "United Kingdom" in r2["sql"]
    assert [f["field"] for f in r2["context"]["filters"]] == ["country"]
    r3 = ask("Compare with the previous month", cid)
    assert r3["status"] == "clarification"  # no month set: must ask, not guess
    r4 = ask("", cid, "November 2011 vs October 2011")
    assert r4["status"] == "success" and r4["context"]["comparison"]["label"].startswith("November 2011")
    assert "United Kingdom" in r4["sql"] and "2011-10-01" in r4["sql"]
    r5 = ask("How many units of those products were returned?", cid)
    codes = [row[0] for row in r4["rows"]]
    assert r5["status"] == "success" and all(c in r5["sql"] for c in codes)
    # Remove the country chip and re-run: the filter must disappear from the executed SQL.
    client.patch(f"/api/conversations/{cid}", json={"remove": ["country"]})
    r6 = client.post("/api/agent/query", json={"question": "", "conversation_id": cid, "rerun": True}).json()
    assert r6["status"] == "success" and "United Kingdom" not in r6["sql"]
    assert r6["evidence"]["source_row_count"] > 0


@requires_data
def test_those_without_previous_result_asks_back():
    r = client.post("/api/agent/query", json={"question": "How many units of those products were returned?"}).json()
    assert r["status"] == "clarification"


@requires_data
def test_malicious_context_values_cannot_inject_sql():
    from app.agent import context as ctx

    cid = "inject-test"
    ctx.save(cid, ConversationState(filters={"country": "Germany'; DROP TABLE transactions; --"},
                                    last_keys={"column": "stock_code", "values": ["1') OR 1=1 --", "22423"]}))
    r = client.post("/api/agent/query", json={"question": "Which products generated the most revenue?", "conversation_id": cid}).json()
    assert r["status"] in ("success", "empty", "rejected")
    if r["sql"]:
        assert "DROP TABLE" not in r["sql"].upper().replace("'GERMANY''; DROP TABLE TRANSACTIONS; --'", "")
    from app.database.connection import run_query
    assert run_query("SELECT COUNT(*) FROM transactions").rows[0][0] > 1_000_000


@requires_data
def test_evidence_lists_filters_grouping_rows_and_unverified_status():
    r = client.post("/api/agent/query", json={"question": "Which countries generated the highest revenue in 2011?"}).json()
    e = r["evidence"]
    assert e["filters"] == [{"field": "year", "label": "Year: 2011"}]
    assert e["grouping"] == ["country"]
    assert e["source_row_count"] == 496677
    assert e["verification"]["independently_verified"] is False
    assert any("December 2011" in x for x in e["limitations"])


@requires_data
def test_max_revenue_asks_then_flags_cancelled_largest_order():
    r = client.post("/api/agent/query", json={"question": "what is the max revenue"}).json()
    assert r["status"] == "clarification" and "Largest single order (invoice)" in r["clarification"]["options"]
    r2 = client.post("/api/agent/query", json={"question": "", "conversation_id": r["conversation_id"],
                                               "clarification_response": "Largest single order (invoice)"}).json()
    assert r2["rows"][0][0] == "581483"
    assert "cancelled in full" in r2["answer"]


def test_totals_label_product_cancellations_explicitly():
    from app.agent.agent import answer_question

    r = answer_question("What is our total revenue?", record=False)
    assert "product_cancelled_value_gbp" in [c["name"] for c in r["columns"]]


# ----------------------------------------------------------------------------- retrieval library
@requires_data
def test_every_retrieval_example_is_valid_and_runs():
    from app.agent.examples import EXAMPLES
    from app.database.connection import run_query
    from app.security.sql_validator import validate_sql

    for e in EXAMPLES:
        v = validate_sql(e["sql"])
        run_query(v.sql, max_rows=10)


def test_retrieval_examples_do_not_leak_benchmark_questions():
    from app.agent.examples import EXAMPLES
    from app.benchmarks.cases import CASES

    for e in EXAMPLES:
        for c in CASES:
            for q in [c.question, *c.setup]:
                ratio = difflib.SequenceMatcher(None, e["question"].lower(), q.lower()).ratio()
                assert ratio < 0.8, (e["id"], c.id, ratio)


def test_keyword_retrieval_fallback_finds_relevant_example():
    from app.agent.retrieval import KeywordRetriever, documents

    hits = KeywordRetriever(documents()).search("first purchase customers 2011", 3)
    assert hits and hits[0][0].id == "ex_new_customers_2011"


# ----------------------------------------------------------------------------- DeepSeek provider
class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        assert body["response_format"] == {"type": "json_object"}
        if _Handler.mode == "401":
            self.send_response(401)
            self.end_headers()
            return
        content = ("not json" if _Handler.mode == "malformed" else json.dumps(
            {"intent": "analytical", "sql": "SELECT COUNT(*) AS n FROM transactions", "explanation": "count",
             "business_rules": [], "clarification_options": []}))
        out = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def deepseek_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@requires_data
@pytest.mark.parametrize("mode,status", [("ok", "success"), ("malformed", "error"), ("401", "error")])
def test_deepseek_provider_success_and_failures(deepseek_server, mode, status, monkeypatch):
    from app.agent import agent as agent_module
    from app.agent.providers import DeepSeekProvider

    _Handler.mode = mode
    provider = DeepSeekProvider("test-key", "deepseek-chat", deepseek_server, 10)
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    monkeypatch.setattr("app.agent.retrieval.retrieve", lambda q, **k: {"backend": "keyword", "examples": [], "notes": []})
    r = agent_module.answer_question("How many lines are there?", record=False)
    assert r["status"] == status
    assert "test-key" not in json.dumps(r)
    if status == "error":
        assert r["rows"] == [] and r["error"]["code"] == "llm_error"
