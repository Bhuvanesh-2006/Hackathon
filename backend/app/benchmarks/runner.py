"""Runs the benchmark suite against the live agent and the loaded data.

Runs happen in a background thread; progress and the last completed run are kept in memory
and the completed run is also persisted to the app-state SQLite file.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

from app.agent.agent import answer_question
from app.agent.providers import get_provider
from app.benchmarks.cases import CASES, BenchmarkCase
from app.benchmarks.security import run_security_suite
from app.benchmarks.compare import Comparison, compare_keyed, compare_scalar, num
from app.config import get_settings
from app.database import connection
from app.history import now_iso

log = logging.getLogger(__name__)
_lock = threading.Lock()
_state: dict[str, Any] = {"current": None}


def _db() -> sqlite3.Connection:
    path = get_settings().app_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS benchmark_runs (id TEXT PRIMARY KEY, created_at TEXT, json TEXT)")
    return con


def last_completed_run() -> dict | None:
    con = _db()
    try:
        row = con.execute("SELECT json FROM benchmark_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else None


def _save_run(run: dict) -> None:
    con = _db()
    try:
        con.execute("INSERT OR REPLACE INTO benchmark_runs VALUES (?,?,?)", (run["run_id"], run["started_at"], json.dumps(run, default=str)))
        con.commit()
    finally:
        con.close()


def case_definitions() -> list[dict]:
    out = []
    for c in CASES:
        d = asdict(c)
        d["reference_sql"] = (c.reference_sql or "").strip() or None
        out.append(d)
    return out


def _expected(case: BenchmarkCase) -> dict | None:
    if not case.reference_sql:
        return None
    res = connection.run_query(case.reference_sql, max_rows=500)
    return {"columns": res.columns, "rows": res.rows}


def _expected_display(case: BenchmarkCase, expected: dict | None) -> str:
    if case.expect == "clarification":
        return "Agent asks a clarifying question"
    if case.expect == "unsupported":
        return "Agent declines / query is not executed"
    if case.expect == "empty":
        return "No data (empty result or only NULL / zero values)"
    if not expected or not expected["rows"]:
        return "-"
    cols, rows = expected["columns"], expected["rows"]
    if case.compare == "scalar":
        return ", ".join(f"{c} = {_fmt(v)}" for c, v in zip(cols, rows[0]))
    preview = "; ".join(f"{r[0]}: {_fmt(r[1])}" for r in rows[:3])
    return f"{len(rows)} rows by {cols[0]}: {preview}{' ...' if len(rows) > 3 else ''}"


def _fmt(v: Any) -> str:
    n = num(v)
    if n is None:
        return str(v)
    return f"{n:,.2f}" if not float(n).is_integer() else f"{int(n):,}"


def run_case(case: BenchmarkCase) -> dict:
    started = time.perf_counter()
    item: dict[str, Any] = {
        "id": case.id, "question": case.question, "category": case.category, "expect": case.expect,
        "description": case.description, "reference_sql": (case.reference_sql or "").strip() or None,
        "setup": case.setup, "clarification": case.clarification,
    }
    try:
        expected = _expected(case)
    except Exception as exc:  # reference SQL must work; surface clearly if it does not
        log.exception("reference SQL failed for %s", case.id)
        item.update(passed=False, executed=False, agent_status="not_run",
                    reason=f"Reference SQL failed: {exc}", expected_display="-")
        return item
    item["expected_display"] = _expected_display(case, expected)
    item["expected"] = expected

    try:
        cid = f"bench-{case.id}-{uuid.uuid4().hex[:8]}"
        for turn in case.setup:
            answer_question(turn, conversation_id=cid, record=False, use_cache=False)
        resp = answer_question(case.question, conversation_id=cid, clarification=case.clarification, record=False,
                               use_cache=False)
    except Exception as exc:
        log.exception("agent failed for %s", case.id)
        item.update(passed=False, executed=False, agent_status="error", reason=f"Agent raised an error: {type(exc).__name__}")
        return item

    status = resp["status"]
    cols = [c["name"] for c in resp["columns"]]
    rows = resp["rows"]
    item.update(
        agent_status=status, agent_sql=resp.get("sql"), agent_answer=resp.get("answer"),
        agent_columns=cols, agent_rows=rows[:20], agent_row_count=resp.get("row_count", 0),
        sql_validated=resp["execution"]["validated"], attempts=resp["execution"]["attempts"],
        executed=status in ("success", "empty"),
    )

    cmp: Comparison
    if case.expect == "clarification":
        cmp = Comparison(status == "clarification",
                         "Agent asked for clarification." if status == "clarification"
                         else f"Agent did not ask for clarification (status: {status}).")
    elif case.expect == "unsupported":
        ok = status in ("unsupported", "rejected")
        cmp = Comparison(ok, "Agent declined; nothing was executed." if ok
                         else f"Agent did not decline (status: {status}).")
    elif case.expect == "empty":
        values = [num(v) for r in rows for v in r]
        ok = status in ("empty",) or (status == "success" and all(v in (None, 0.0) for v in values))
        cmp = Comparison(ok, "Agent reported no data." if ok
                         else f"Expected no data; agent status {status} with values {[v for v in values if v][:3]}.")
    elif status not in ("success", "empty"):
        msg = (resp.get("error") or {}).get("message") or resp.get("answer") or status
        cmp = Comparison(False, f"Agent did not return a result (status: {status}): {msg}")
    elif case.compare == "scalar":
        exp_row = dict(zip(expected["columns"], expected["rows"][0]))
        cmp = compare_scalar(exp_row, cols, rows, case.value_columns, case.rel_tol, case.abs_tol)
    else:
        cmp = compare_keyed(expected["columns"], expected["rows"], cols, rows, case.key_columns,
                            case.value_columns, case.top_n, case.rel_tol, case.abs_tol)
    item.update(passed=cmp.passed, reason=cmp.reason, duration_ms=round((time.perf_counter() - started) * 1000, 1))
    return item


def _summarize(results: list[dict]) -> dict:
    analytical = [r for r in results if r["expect"] == "answer"]
    clar = [r for r in results if r["expect"] == "clarification"]
    neg = [r for r in results if r["expect"] in ("unsupported", "empty")]

    def rate(xs: list[dict], key: str) -> dict:
        n = sum(1 for x in xs if x.get(key))
        return {"passed": n, "total": len(xs), "rate": round(n / len(xs), 4) if xs else None}

    return {
        "overall": rate(results, "passed"),
        "result_match": rate(analytical, "passed"),
        "sql_execution": rate(analytical, "executed"),
        "clarification": rate(clar, "passed"),
        "unsupported_and_empty": rate(neg, "passed"),
        "multi_turn": rate([r for r in results if r.get("setup")], "passed"),
    }


def _run(run: dict) -> None:
    try:
        for case in CASES:
            run["progress"]["current"] = case.id
            result = run_case(case)
            run["results"].append(result)
            run["progress"]["done"] += 1
        run["progress"]["current"] = "security probes"
        security = run_security_suite()
        run["security"] = security["results"]
        run["summary"] = _summarize(run["results"])
        run["summary"]["security"] = security["summary"]
        run["status"] = "completed"
    except Exception as exc:  # pragma: no cover
        log.exception("benchmark run failed")
        run["status"] = "failed"
        run["error"] = str(exc)
    finally:
        run["finished_at"] = now_iso()
        run["progress"]["current"] = None
        if run["status"] == "completed":
            _save_run(run)


def start_run() -> dict:
    with _lock:
        current = _state["current"]
        if current and current["status"] == "running":
            return current
        if not connection.dataset_available():
            raise RuntimeError("Dataset not loaded: the benchmark cannot run.")
        provider = get_provider()
        run = {
            "run_id": uuid.uuid4().hex, "status": "running", "started_at": now_iso(), "finished_at": None,
            "provider": provider.name, "model": provider.model, "is_llm": provider.is_llm,
            "progress": {"done": 0, "total": len(CASES), "current": None},
            "results": [], "summary": None,
        }
        _state["current"] = run
        threading.Thread(target=_run, args=(run,), daemon=True).start()
        return run


def run_sync() -> dict:
    """Run synchronously (CLI / tests)."""
    provider = get_provider()
    run = {
        "run_id": uuid.uuid4().hex, "status": "running", "started_at": now_iso(), "finished_at": None,
        "provider": provider.name, "model": provider.model, "is_llm": provider.is_llm,
        "progress": {"done": 0, "total": len(CASES), "current": None}, "results": [], "summary": None,
    }
    _run(run)
    return run


def current_state() -> dict:
    return {"current": _state["current"], "last_completed": last_completed_run()}
