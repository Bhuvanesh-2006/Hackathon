"""Execute a saved or recommended query through the normal validation pipeline.

The SQL is rendered with typed parameters, validated against the selected dataset's schema every
time, and executed on that dataset only. The response has the same shape as an analyst answer.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from app import history
from app.agent.evidence import build_evidence, build_generic_evidence
from app.agent.presentation import choose_chart, result_caveats, summarize
from app.database import connection
from app.datasets import execution, registry
from app.library import store
from app.security.sql_validator import SQLValidationError


def run_definition(definition: dict[str, Any], ds: dict[str, Any], values: dict[str, Any] | None,
                   use_cache: bool = True, record: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    title = definition["title"]
    sql = store.render(definition["sql"], definition.get("parameters", []), values)
    resp: dict[str, Any] = {
        "query_id": uuid.uuid4().hex, "conversation_id": uuid.uuid4().hex, "created_at": history.now_iso(),
        "question": definition.get("question") or title, "status": "error", "answer": "",
        "explanation": definition.get("description"), "sql": sql, "columns": [], "rows": [], "row_count": 0,
        "truncated": False, "chart": None, "clarification": None, "business_rules": [], "error": None,
        "evidence": None, "context": None, "rerun": False,
        "dataset": {"id": ds["id"], "name": ds["name"], "version": ds["version"], "kind": ds["kind"]},
        "saved_query": {"id": definition.get("id"), "title": title, "builtin": bool(definition.get("builtin")),
                        "parameters": values or {}},
        "execution": {"provider": "saved query", "model": "", "is_llm": False, "attempts": 1, "validated": False,
                      "db_ms": None, "total_ms": None, "regenerated": False, "max_rows": 0, "timeout_s": 0},
    }

    def finish() -> dict[str, Any]:
        resp["execution"]["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if record:
            try:
                history.save(resp, f"[Saved query] {title}", None)
            except Exception:
                pass
        return resp

    try:
        validated = execution.validate_for(ds, sql)
    except SQLValidationError as exc:
        resp.update(status="rejected", answer="The saved SQL does not validate against this dataset and was not executed.",
                    error={"code": "sql_rejected", "message": str(exc), "retryable": False})
        return finish()
    resp["sql"] = validated.sql
    resp["execution"]["validated"] = True
    try:
        result, cache = execution.execute(ds, validated, use_cache=use_cache, params_for_key=values)
    except connection.QueryTimeoutError as exc:
        resp.update(status="error", answer="The query took too long and was stopped.",
                    error={"code": "timeout", "message": str(exc), "retryable": True})
        return finish()
    except (connection.QueryExecutionError, connection.DatasetUnavailableError) as exc:
        resp.update(status="error", answer="The query failed to execute.",
                    error={"code": "execution_error", "message": str(exc), "retryable": True})
        return finish()
    resp["execution"]["cache"] = cache
    resp["execution"]["db_ms"] = None if cache.get("hit") else result.duration_ms
    resp["columns"] = [{"name": n, "type": t} for n, t in zip(result.columns, result.column_types)]
    resp["rows"], resp["row_count"], resp["truncated"] = result.rows, result.row_count, result.truncated
    all_null = bool(result.rows) and all(v is None for r in result.rows for v in r)
    resp["status"] = "success" if result.rows and not all_null else "empty"
    resp["answer"] = summarize(result.columns, result.column_types, result.rows, result.truncated) if not all_null \
        else "The query ran successfully but returned no values."
    caveats = result_caveats(result.columns, result.rows)
    if caveats:
        resp["answer"] += " " + " ".join(caveats)
    resp["chart"] = choose_chart(None, result.columns, result.column_types, result.rows)
    resp["evidence"] = (build_evidence(validated.sql, result.columns, result.rows, result.truncated, [], None, None)
                        if registry.is_builtin(ds) else build_generic_evidence(ds, validated.sql, result.rows, result.truncated))
    if resp["evidence"] is not None:
        resp["evidence"]["dataset"] = resp["dataset"]
    return finish()


def run_saved(qid: str, dataset_id: str, values: dict[str, Any] | None, allow_other_dataset: bool,
              use_cache: bool = True) -> dict[str, Any]:
    q = store.get(qid)
    if q is None:
        raise store.LibraryError(404, "not_found", "Saved query not found.")
    ds = registry.get(dataset_id)
    if ds is None:
        raise store.LibraryError(404, "dataset_not_found", "The selected dataset does not exist.")
    compat = store.compatibility(q, ds)
    if compat["status"] in ("incompatible", "unavailable"):
        raise store.LibraryError(409, "incompatible_query", compat["reason"], {"compatibility": compat})
    if compat["status"] == "other_dataset" and not allow_other_dataset:
        raise store.LibraryError(409, "confirmation_required", compat["reason"], {"compatibility": compat})
    resp = run_definition(q, ds, values, use_cache=use_cache)
    store.touch(qid)
    resp["saved_query"]["compatibility"] = compat
    return resp
