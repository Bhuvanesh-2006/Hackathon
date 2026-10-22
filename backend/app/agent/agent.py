"""The question -> SQL -> validated execution workflow.

1. Validate input, load conversation state (active filters, comparison, previous result keys).
2. Deterministic guards: designated ambiguous phrasings, "compare with previous month" without a
   current period, and "those products" without a previous result all ask back instead of guessing.
3. For LLM providers, retrieve verified examples and notes (BGE + FAISS or keyword fallback).
4. Ask the provider for a structured plan (intent, SQL, explanation, chart, rules).
5. Validate SQL with SQLGlot (read-only, single statement, table/column allowlists).
6. Execute on a read-only connection with timeout and row limit.
7. On a correctable validation/execution error, allow at most ONE regeneration, re-validated.
8. Build the response and its evidence from the rows actually returned; update the state from
   the executed SQL.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app import history
from app.agent import context as ctx_mod
from app.agent.ambiguity import check_ambiguity
from app.agent.evidence import build_evidence
from app.agent.models import AgentPlan
from app.agent.presentation import choose_chart, result_caveats, summarize
from app.agent.prompts import system_prompt, user_prompt
from app.agent.providers import LLMError, PlanContext, get_provider
from app.config import get_settings
from app.database import connection
from app.database.business_rules import BUSINESS_RULES
from app.datasets import execution, registry
from app.security.sql_validator import SQLValidationError, validate_sql

log = logging.getLogger(__name__)
RULES_BY_ID = {r["id"]: r for r in BUSINESS_RULES}
MAX_REGENERATIONS = 1


class InputError(ValueError):
    pass


class DatasetMismatch(InputError):
    """The conversation is bound to another dataset; the client must start a new conversation."""


def _rules(ids: list[str]) -> list[dict[str, str]]:
    seen, out = set(), []
    for rid in [*ids, "currency"]:
        if rid in RULES_BY_ID and rid not in seen:
            seen.add(rid)
            r = RULES_BY_ID[rid]
            out.append({"id": r["id"], "name": r["name"], "definition": r["definition"]})
    return out


def context_view(state: ctx_mod.ConversationState) -> dict[str, Any]:
    active = {k: v for k, v in state.filters.items() if k not in state.removed}
    return {
        "filters": ctx_mod.filter_labels(active),
        "removed": state.removed,
        "comparison": state.comparison.model_dump() if state.comparison else None,
        "previous_result": ({"column": state.last_keys["column"], "count": len(state.last_keys["values"])}
                            if state.last_keys else None),
        "root_question": state.root_question,
        "topic": state.topic,
    }


def _base(conversation_id: str, question: str, provider) -> dict[str, Any]:
    return {
        "query_id": uuid.uuid4().hex,
        "conversation_id": conversation_id,
        "created_at": history.now_iso(),
        "question": question,
        "status": "error",
        "answer": "",
        "explanation": None,
        "sql": None,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "chart": None,
        "clarification": None,
        "business_rules": [],
        "error": None,
        "evidence": None,
        "context": None,
        "rerun": False,
        "execution": {
            "provider": provider.name, "model": provider.model, "is_llm": provider.is_llm,
            "attempts": 0, "validated": False, "db_ms": None, "total_ms": None,
            "regenerated": False, "max_rows": get_settings().max_result_rows,
            "timeout_s": get_settings().query_timeout_seconds,
        },
    }


def answer_question(question: str, conversation_id: str | None = None, clarification: str | None = None,
                    record: bool = True, rerun: bool = False, provider_override=None,
                    dataset_id: str | None = None, use_cache: bool = True) -> dict[str, Any]:
    settings = get_settings()
    question = (question or "").strip()
    clarification = (clarification or "").strip() or None
    conversation_id = conversation_id or uuid.uuid4().hex
    state = ctx_mod.load(conversation_id)
    ds = registry.get(dataset_id or state.dataset_id or registry.BUILTIN_ID)
    if ds is None:
        raise InputError("Unknown dataset. Select a dataset in the Dataset Manager.")
    if ds["status"] != "ready":
        raise InputError(f"Dataset '{ds['name']}' is not ready (status: {ds['status']}).")
    if state.dataset_id and state.dataset_id != ds["id"]:
        bound = registry.get(state.dataset_id)
        raise DatasetMismatch(f"This conversation uses dataset '{bound['name'] if bound else state.dataset_id}'. "
                              f"Start a new conversation to query '{ds['name']}'.")
    if state.dataset_id is None:
        state.dataset_id = ds["id"]
        ctx_mod.save(conversation_id, state)
    if rerun:
        question = state.root_question or state.last_question or ""
        if not question:
            raise InputError("There is no previous question in this conversation to re-run.")
    if not question:
        raise InputError("Please enter a question.")
    if len(question) > settings.max_question_length:
        raise InputError(f"Questions are limited to {settings.max_question_length} characters.")
    if clarification and len(clarification) > 200:
        raise InputError("Clarification is too long.")

    started = time.perf_counter()
    provider = provider_override or get_provider()  # override: internal security probes only
    hist = history.conversation_history(conversation_id) if record else []
    resp = _base(conversation_id, question, provider)
    resp["dataset"] = {"id": ds["id"], "name": ds["name"], "version": ds["version"], "kind": ds["kind"]}
    resp["rerun"] = rerun
    if clarification:
        resp["clarification_response"] = clarification

    def finish() -> dict[str, Any]:
        resp["execution"]["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        resp["context"] = context_view(state)
        if record:
            try:
                history.save(resp, question, clarification)
            except Exception:  # history must never break answering
                log.exception("failed to save history")
        return resp

    def ask_back(q: str, options: list[str], source: str) -> dict[str, Any]:
        resp.update(status="clarification", answer=q, clarification={"question": q, "options": options, "source": source})
        return finish()

    if not registry.is_builtin(ds):
        from app.agent.generic import answer_generic

        return answer_generic(question, ds, resp, clarification, hist, provider, use_cache, finish, ask_back)

    if not connection.dataset_available():
        resp.update(status="error", answer="The dataset is not loaded yet.",
                    error={"code": "dataset_unavailable", "message": "Run the data preparation script first.", "retryable": False})
        return finish()

    if not clarification and not rerun:
        amb = check_ambiguity(question)
        if amb:
            return ask_back(amb.question, amb.options, "ambiguity_rules")

    # "those products" needs a previous result to refer to.
    if ctx_mod.THOSE.search(question) and not state.last_keys and not rerun:
        return ask_back("Which items do you mean? There is no previous result in this conversation to refer to.",
                        [], "context_rules")

    # Comparisons need an explicit current period; never guess one.
    comparison = None
    if ctx_mod.COMPARE_PREVIOUS.search(question) or (rerun and state.comparison):
        comparison = (ctx_mod.parse_comparison(clarification or "") or ctx_mod.parse_comparison(question)
                      or (state.comparison if rerun else None)
                      or ctx_mod.previous_window({k: v for k, v in state.filters.items() if k not in state.removed}))
        if comparison is None:
            return ask_back("Which period should be compared with the previous one? No month or date range is set "
                            "in this conversation, and the data ends on 2011-12-09 (December 2011 is partial).",
                            ctx_mod.comparison_options(), "context_rules")

    retrieval = None
    if provider.is_llm:
        try:
            from app.agent.retrieval import retrieve

            retrieval = retrieve(" ".join(x for x in (question, clarification) if x))
        except Exception:
            log.exception("retrieval failed; continuing without retrieved examples")

    ctx = PlanContext(question=question, history=hist, clarification=clarification, state=state,
                      rerun=rerun, comparison=comparison)
    system = system_prompt()
    plan: AgentPlan | None = None
    feedback: str | None = None
    validated = None
    result = None

    for attempt in range(MAX_REGENERATIONS + 1):
        resp["execution"]["attempts"] = attempt + 1
        resp["execution"]["regenerated"] = attempt > 0
        ctx.error_feedback = feedback
        try:
            plan = provider.plan(system, user_prompt(question, hist, clarification, feedback, state=state,
                                                     retrieval=retrieval, comparison=comparison, rerun=rerun), ctx)
        except LLMError as exc:
            resp.update(status="error", answer="The language model could not produce a plan.",
                        error={"code": "llm_error", "message": str(exc), "retryable": True})
            return finish()

        resp["explanation"] = plan.explanation
        resp["business_rules"] = _rules(plan.business_rules)

        if plan.intent == "clarification":
            options = [o for o in plan.clarification_options if o][:4]
            return ask_back(plan.clarification_question or "Could you clarify what you mean?", options, "model")
        if plan.intent == "unsupported" or not plan.sql:
            reason = plan.unsupported_reason or "This question cannot be answered from the transaction data."
            resp.update(status="unsupported", answer=reason)
            return finish()

        resp["sql"] = plan.sql
        try:
            validated = validate_sql(plan.sql)
        except SQLValidationError as exc:
            resp["execution"]["validated"] = False
            if attempt < MAX_REGENERATIONS:
                feedback = f"SQL:\n{plan.sql}\nVALIDATION ERROR: {exc}"
                continue
            resp.update(status="rejected", answer="The generated SQL was rejected by the safety validator and was not executed.",
                        error={"code": "sql_rejected", "message": str(exc), "retryable": True})
            return finish()

        resp["sql"] = validated.sql
        resp["execution"]["validated"] = True
        try:
            result, cache_info = execution.execute(ds, validated, use_cache=use_cache)
            resp["execution"]["cache"] = cache_info
            break
        except connection.QueryTimeoutError as exc:
            resp.update(status="error", answer="The query took too long and was stopped.",
                        error={"code": "timeout", "message": str(exc), "retryable": True})
            return finish()
        except connection.QueryExecutionError as exc:
            if attempt < MAX_REGENERATIONS:
                feedback = f"SQL:\n{validated.sql}\nDATABASE ERROR: {exc}"
                continue
            resp.update(status="error", answer="The query failed to execute.",
                        error={"code": "execution_error", "message": str(exc), "retryable": True})
            return finish()
        except connection.DatasetUnavailableError as exc:
            resp.update(status="error", answer="The dataset is not loaded yet.",
                        error={"code": "dataset_unavailable", "message": str(exc), "retryable": False})
            return finish()

    assert result is not None and plan is not None and validated is not None
    resp["columns"] = [{"name": n, "type": t} for n, t in zip(result.columns, result.column_types)]
    resp["rows"] = result.rows
    resp["row_count"] = result.row_count
    resp["truncated"] = result.truncated
    resp["execution"]["db_ms"] = None if resp["execution"].get("cache", {}).get("hit") else result.duration_ms
    all_null = bool(result.rows) and all(v is None for row in result.rows for v in row)
    resp["status"] = "success" if result.rows and not all_null else "empty"
    resp["answer"] = summarize(result.columns, result.column_types, result.rows, result.truncated)
    if all_null:
        resp["answer"] = ("The query ran successfully but found no matching transactions (all values are empty). "
                          "The dataset covers 2009-12-01 to 2011-12-09.")
    caveats = result_caveats(result.columns, result.rows)
    if caveats:
        resp["answer"] = resp["answer"] + " " + " ".join(caveats)
    resp["chart"] = choose_chart(plan.chart, result.columns, result.column_types, result.rows)

    # Update conversation state from what was actually executed.
    executed_filters = ctx_mod.extract_filters(validated.sql)
    if comparison:
        executed_filters.pop("date_from", None)
        executed_filters.pop("date_to", None)
        for k in ("date_from", "date_to"):
            if k in state.filters:
                executed_filters[k] = state.filters[k]
    if ctx_mod.THOSE.search(question) and state.last_keys:
        executed_filters.pop("stock_codes", None)  # a one-off reference, not a sticky filter
    state.removed = [f for f in state.removed if f not in executed_filters]
    state.filters = executed_filters
    state.comparison = comparison
    if not rerun and not ctx_mod.is_follow_up(question):
        state.root_question = question if not clarification else f"{question} ({clarification})"
    state.last_question = question
    state.last_sql = validated.sql
    state.last_keys = ctx_mod.result_keys(result.columns, result.rows) or state.last_keys
    ctx_mod.save(conversation_id, state)

    try:
        resp["evidence"] = build_evidence(validated.sql, result.columns, result.rows, result.truncated,
                                          resp["business_rules"], retrieval,
                                          comparison.model_dump() if comparison else None)
    except Exception:
        log.exception("evidence build failed")
    return finish()


def seed_conversation(topic: dict[str, Any], filters: dict[str, Any]) -> str:
    """Start a conversation pre-scoped to an investigation (e.g. an anomaly week)."""
    conversation_id = uuid.uuid4().hex
    ctx_mod.save(conversation_id, ctx_mod.ConversationState(filters=filters, topic=topic))
    return conversation_id
