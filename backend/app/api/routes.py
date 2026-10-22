"""HTTP routes. Errors are returned as {"error": {"code", "message"}} without stack traces."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool

from app import history
from app.agent import context as ctx_mod
from app.agent.agent import DatasetMismatch, InputError, answer_question, context_view, seed_conversation
from app.agent.providers import get_provider
from app.api import analytics
from app.api.errors import ApiError
from app.api.schemas import AgentQueryRequest, ContributionRequest, ConversationCreate, ConversationPatch
from app.benchmarks import runner
from app.config import get_settings
from app.database import connection
from app.insights import anomalies, contribution, forecast
from app.database.business_rules import BUSINESS_RULES, CURRENCY, DATASET_INFO, ITEM_TYPES, LINE_TYPES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
APP_VERSION = "1.2.0"


def _require_dataset() -> None:
    if not connection.dataset_available():
        raise ApiError(503, "dataset_unavailable",
                       "The dataset is not loaded. Run `python -m scripts.prepare_data` in backend/.")


@router.get("/health")
def health() -> dict:
    loaded = connection.dataset_available()
    db = {"loaded": loaded, "read_only": True}
    if loaded:
        try:
            meta = connection.fetch_metadata()
            db.update(status="connected", row_count=meta.get("row_count"), prepared_at=meta.get("prepared_at"))
        except Exception:
            log.exception("health check query failed")
            db.update(status="error")
    else:
        db["status"] = "not_loaded"
    return {"status": "ok", "version": APP_VERSION, "database": db, "llm": get_provider().status()}


@router.get("/dashboard/summary")
async def dashboard_summary(year: int | None = Query(None, ge=2009, le=2011),
                            country: str | None = Query(None, max_length=60)) -> dict:
    _require_dataset()
    data = await run_in_threadpool(analytics.dashboard_summary, year, country or None)
    meta = await run_in_threadpool(connection.fetch_metadata)
    recent, _ = await run_in_threadpool(history.list_history, 6, 0, None, None)
    options = await run_in_threadpool(analytics.filter_options)
    return {**data, "currency": CURRENCY, "dataset": {**DATASET_INFO, **meta}, "recent_queries": recent,
            "filter_options": options}


@router.get("/dataset/schema")
async def dataset_schema() -> dict:
    _require_dataset()
    profile = await run_in_threadpool(analytics.dataset_profile)
    return {**profile, "dataset": DATASET_INFO, "business_rules": BUSINESS_RULES,
            "line_type_definitions": LINE_TYPES, "item_type_definitions": ITEM_TYPES, "table": "transactions"}


@router.get("/dataset/preview")
async def dataset_preview(limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0, le=2_000_000),
                          line_type: str | None = Query(None, max_length=30), item_type: str | None = Query(None, max_length=30),
                          country: str | None = Query(None, max_length=60), search: str | None = Query(None, max_length=60)) -> dict:
    _require_dataset()
    if line_type and line_type not in LINE_TYPES:
        raise ApiError(400, "invalid_filter", "Unknown line_type")
    if item_type and item_type not in ITEM_TYPES:
        raise ApiError(400, "invalid_filter", "Unknown item_type")
    return await run_in_threadpool(analytics.dataset_preview, limit, offset, line_type, item_type, country or None, search or None)


@router.post("/agent/query")
async def agent_query(body: AgentQueryRequest) -> dict:
    question = body.question.strip()
    clarification = (body.clarification_response or "").strip() or None
    if clarification and not question and body.conversation_id:
        pending = await run_in_threadpool(history.pending_clarification, body.conversation_id)
        if pending:
            question = pending
    try:
        return await run_in_threadpool(answer_question, question, body.conversation_id, clarification, True, body.rerun,
                                       None, body.dataset_id)
    except DatasetMismatch as exc:
        raise ApiError(409, "dataset_mismatch", str(exc)) from exc
    except InputError as exc:
        raise ApiError(400, "invalid_question", str(exc)) from exc


# ----------------------------------------------------------------------------- conversations
FIELD_KEYS = {"country": ["country"], "year": ["year"], "date_range": ["date_from", "date_to"],
              "stock_codes": ["stock_codes"], "customer_id": ["customer_id"]}


def _check_conversation_id(conversation_id: str) -> None:
    if not conversation_id or len(conversation_id) > 64 or not all(c.isalnum() or c in "_-" for c in conversation_id):
        raise ApiError(400, "invalid_id", "Invalid conversation id")


@router.post("/conversations", status_code=201)
async def create_conversation(body: ConversationCreate) -> dict:
    """Start an analyst conversation scoped to an anomaly week."""
    _require_dataset()
    anomaly = await run_in_threadpool(anomalies.find, body.anomaly_id)
    if not anomaly:
        raise ApiError(404, "not_found", "Anomaly not found")
    end = (date.fromisoformat(anomaly["period_start"]) + timedelta(days=7)).isoformat()
    topic = {"type": "anomaly", "anomaly_id": anomaly["id"],
             "summary": f"{anomaly['metric_label']} {anomaly['kind']} in the week of {anomaly['period_start']}: "
                        f"observed {anomaly['observed']:,.2f} vs expected {anomaly['expected']:,.2f} ({anomaly['unit']})"}
    cid = seed_conversation(topic, {"date_from": anomaly["period_start"], "date_to": end})
    return {"conversation_id": cid, "context": context_view(ctx_mod.load(cid))}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict:
    _check_conversation_id(conversation_id)
    return {"conversation_id": conversation_id, "context": context_view(ctx_mod.load(conversation_id))}


@router.patch("/conversations/{conversation_id}")
async def patch_conversation(conversation_id: str, body: ConversationPatch) -> dict:
    """Remove individual active filters, clear all filters, or clear the comparison period."""
    _check_conversation_id(conversation_id)
    state = ctx_mod.load(conversation_id)
    if body.clear_filters:
        state.removed = sorted(set(state.removed) | set(state.filters))
        state.filters = {}
        state.topic = None
    for field in body.remove:
        for key in FIELD_KEYS[field]:
            state.filters.pop(key, None)
            if key not in state.removed:
                state.removed.append(key)
    if body.clear_comparison or body.clear_filters:
        state.comparison = None
    ctx_mod.save(conversation_id, state)
    return {"conversation_id": conversation_id, "context": context_view(state)}


# ----------------------------------------------------------------------------- insights
@router.get("/insights/anomalies")
async def list_anomalies(metric: str | None = Query(None, max_length=30),
                         severity: str | None = Query(None, pattern="^(high|medium)$")) -> dict:
    _require_dataset()
    data = dict(await run_in_threadpool(anomalies.cached_detection))
    items = data["anomalies"]
    if metric:
        if metric not in anomalies.METRICS:
            raise ApiError(400, "invalid_filter", "Unknown metric")
        items = [a for a in items if a["metric"] == metric]
    if severity:
        items = [a for a in items if a["severity"] == severity]
    data["anomalies"] = items
    return data


@router.get("/insights/anomalies/{anomaly_id}")
async def get_anomaly(anomaly_id: str) -> dict:
    _require_dataset()
    a = await run_in_threadpool(anomalies.find, anomaly_id)
    if not a:
        raise ApiError(404, "not_found", "Anomaly not found")
    return a


@router.post("/insights/contribution")
async def contribution_analysis(body: ContributionRequest) -> dict:
    _require_dataset()
    if body.anomaly_id:
        a = await run_in_threadpool(anomalies.find, body.anomaly_id)
        if not a:
            raise ApiError(404, "not_found", "Anomaly not found")
        metric = a["metric"]
        current, comparison = contribution.windows_for_anomaly(a)
    else:
        if not (body.metric and body.current and body.comparison):
            raise ApiError(400, "invalid_request", "Provide anomaly_id, or metric, current and comparison windows.")
        metric = body.metric
        current = (body.current.start, body.current.end)
        comparison = [(w.start, w.end) for w in body.comparison]
    try:
        result = await run_in_threadpool(contribution.contribution, metric, body.dimension, current, comparison, body.top_n)
    except contribution.ContributionError as exc:
        raise ApiError(400, "invalid_analysis", str(exc)) from exc
    result["anomaly_id"] = body.anomaly_id
    return result


@router.get("/insights/forecast")
async def sales_forecast() -> dict:
    _require_dataset()
    return await run_in_threadpool(forecast.cached_forecast)


@router.get("/knowledge/status")
def knowledge_status() -> dict:
    from app.agent.examples import EXAMPLES, NOTES
    from app.agent.retrieval import status

    return {"retrieval": status(), "configured_backend": get_settings().retrieval_backend,
            "embedding_model": get_settings().embedding_model, "examples": len(EXAMPLES), "notes": len(NOTES),
            "used_by": "LLM providers only (the offline planner does not use retrieval)"}


@router.get("/knowledge/search")
async def knowledge_search(q: str = Query(..., min_length=2, max_length=300)) -> dict:
    from app.agent.retrieval import retrieve

    return await run_in_threadpool(retrieve, q)


@router.get("/history")
async def list_history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       status: str | None = Query(None, max_length=20), search: str | None = Query(None, max_length=100)) -> dict:
    items, total = await run_in_threadpool(history.list_history, limit, offset, status or None, search or None)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/history/{query_id}")
async def get_history_item(query_id: str) -> dict:
    if not query_id.isalnum() or len(query_id) > 64:
        raise ApiError(400, "invalid_id", "Invalid query id")
    item = await run_in_threadpool(history.get_entry, query_id)
    if not item:
        raise ApiError(404, "not_found", "Query not found")
    return item


@router.delete("/history")
async def clear_history() -> dict:
    deleted = await run_in_threadpool(history.clear)
    return {"deleted": deleted}


@router.get("/benchmarks")
async def benchmarks() -> dict:
    state = await run_in_threadpool(runner.current_state)
    return {"cases": runner.case_definitions(), "dataset_loaded": connection.dataset_available(),
            "llm": get_provider().status(), **state}


@router.post("/benchmarks/run", status_code=202)
async def run_benchmarks() -> dict:
    try:
        run = runner.start_run()
    except RuntimeError as exc:
        raise ApiError(503, "dataset_unavailable", str(exc)) from exc
    return {"run_id": run["run_id"], "status": run["status"], "progress": run["progress"]}


@router.get("/settings")
def app_settings() -> dict:
    s = get_settings()
    return {
        "dataset": {**DATASET_INFO, "excel_path_configured": s.source_excel_path.name, "database_file": s.duckdb_path.name,
                    "loaded": connection.dataset_available()},
        "database": {"engine": "DuckDB", "mode": "read-only connection, external file/network access disabled"},
        "llm": get_provider().status(),
        "query_limits": {"timeout_seconds": s.query_timeout_seconds, "max_result_rows": s.max_result_rows,
                         "max_question_length": s.max_question_length, "max_regenerations": 1},
        "benchmark": {"case_count": len(runner.CASES), "numeric_relative_tolerance": 0.005, "numeric_absolute_tolerance": 0.51,
                      "comparison": "grouped results compared by key, order-insensitive (top-N compares the set of top keys)"},
        "business_rules": BUSINESS_RULES,
        "anomaly_detection": {**anomalies.DEFAULT_CONFIG.__dict__, "method": "weekly robust z-score (median/MAD) per trading day"},
        "forecast": {"holdout_months": forecast.HOLDOUT_MONTHS, "horizon_months": forecast.HORIZON,
                     "methods": forecast.METHODS},
        "retrieval": {"configured_backend": s.retrieval_backend, "embedding_model": s.embedding_model},
        "demo": {
            "offline_provider_available": True,
            "how_to_enable": "Leave both API keys unset, or set LLM_PROVIDER=offline in backend/.env, to use the deterministic rule-based planner (no LLM).",
            "sample_questions": SAMPLE_QUESTIONS,
        },
    }


SAMPLE_QUESTIONS = [
    "Which products generated the highest revenue?",
    "Which products had the most returned units?",
    "Which countries generated the highest revenue?",
    "What were the monthly revenue trends?",
    "Which customers contributed the most revenue?",
    "How much revenue was associated with cancelled invoices?",
    "Who are our best customers?",
    "How much net revenue came from transactions with a missing customer ID?",
]
