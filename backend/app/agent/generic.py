"""Question answering for imported datasets (any schema).

Only the selected dataset's schema reaches the model. The retail business rules, the retail
verified examples and the retail-specific guards are not used, because they do not apply. SQL is
validated against this dataset's own table and columns and runs on its own read-only file.
"""
from __future__ import annotations

import re
import time
from typing import Any

from app.agent.models import AgentPlan, ChartSpec
from app.agent.presentation import choose_chart, summarize
from app.agent.providers import LLMError, LLMProvider, PlanContext
from app.database import connection
from app.datasets import execution, registry
from app.security.sql_validator import SQLValidationError

MONEY_WORDS = re.compile(r"\b(revenue|sales|profit|margin|income|turnover|spend|spending|earnings|returns?|refunds?)\b", re.I)


def system_prompt(ds: dict[str, Any]) -> str:
    support = "\n".join(f"- {s}" for s in ds.get("support", []))
    return f"""You are RetailPilot, an analyst that answers questions about ONE imported dataset by writing DuckDB SQL.

Dataset: "{ds['name']}" (imported from {ds.get('source_filename')}, {ds.get('row_count')} rows).
Only this table exists:
{registry.schema_text(ds)}

What this dataset supports:
{support}

RULES
- Write exactly one read-only SELECT over table {ds['table']}. Use only the columns listed above, by their
  listed names. Other tables do not exist.
- Never invent metrics. Revenue, profit, margin, returns or similar may only be computed if columns that
  directly contain them exist; otherwise set intent = "unsupported" and say which columns would be needed.
- Do not assume this is a sales dataset. Describe results with the actual column names.
- If the question is ambiguous about which column or aggregation is meant, set intent = "clarification"
  and offer 2-4 options using real column names.
- Round decimals to 2 places, give readable snake_case aliases, use LIMIT for rankings (default 10).
- chart: "line" for time series, "bar" for category rankings, "none" for single values.
- explanation: one or two sentences naming the columns and aggregation used.
"""


def user_prompt(question: str, clarification: str | None, history: list, error_feedback: str | None) -> str:
    parts = []
    if history:
        parts.append("CONVERSATION SO FAR (most recent last):")
        for t in history[-4:]:
            parts.append(f"- Q: {t.question}" + (f"\n  SQL: {t.sql}" if t.sql else ""))
    parts.append(f"QUESTION: {question}")
    if clarification:
        parts.append(f"USER'S CLARIFICATION: {clarification}")
    if error_feedback:
        parts.append("YOUR PREVIOUS SQL FAILED. Fix it.\n" + error_feedback)
    return "\n".join(parts)


class GenericOfflinePlanner(LLMProvider):
    """Rule-based planner for imported datasets when no LLM is configured. Not an LLM."""

    name = "offline"
    model = "rule-based templates (no LLM)"
    is_llm = False

    def __init__(self, ds: dict[str, Any]) -> None:
        self.ds = ds

    def _mentioned(self, q: str, role: str) -> list[dict]:
        out = []
        for c in self.ds["columns"]:
            if role and c.get("role") != role:
                continue
            words = {c["name"], c["name"].replace("_", " "), (c.get("original_name") or "").lower()}
            if any(w and re.search(r"\b" + re.escape(w.lower()) + r"\b", q) for w in words):
                out.append(c)
        return out

    def plan(self, system: str, user: str, context: PlanContext) -> AgentPlan:
        q = (context.question + " " + (context.clarification or "")).lower()
        t = self.ds["table"]
        nums, texts, dates = self._mentioned(q, "numeric"), self._mentioned(q, "text"), self._mentioned(q, "date")
        m = re.search(r"\b(?:top|first|bottom)\s+(\d{1,3})\b", q)
        n = max(1, min(int(m.group(1)), 100)) if m else 10
        agg = "AVG" if re.search(r"\b(average|avg|mean)\b", q) else "MAX" if re.search(r"\b(max|maximum|highest value)\b", q) \
            else "MIN" if re.search(r"\b(min|minimum|lowest value)\b", q) else "SUM"
        agg_word = {"AVG": "average", "MAX": "maximum", "MIN": "minimum", "SUM": "total"}[agg]

        if MONEY_WORDS.search(q) and not nums:
            words = ", ".join(sorted({w.lower() for w in MONEY_WORDS.findall(q)}))
            return AgentPlan(intent="unsupported", explanation="No matching column.",
                             unsupported_reason=f"This dataset has no column for {words}. Available numeric columns: "
                             + (", ".join(c["name"] for c in self.ds["columns"] if c.get("role") == "numeric") or "none")
                             + ". RetailPilot does not invent metrics that the data does not contain.")
        if nums and (dates or re.search(r"\b(monthly|per month|by month|trend|over time)\b", q)):
            d = (dates or [c for c in self.ds["columns"] if c.get("role") == "date"] or [None])[0]
            if d is not None:
                v = nums[0]["name"]
                sql = (f"SELECT date_trunc('month', {d['name']}) AS month, ROUND({agg}({v}), 2) AS {agg_word}_{v} "
                       f"FROM {t} WHERE {d['name']} IS NOT NULL GROUP BY month ORDER BY month")
                return AgentPlan(intent="analytical", sql=sql, explanation=f"Monthly {agg_word} of {v} by {d['name']}.",
                                 chart=ChartSpec(type="line", x="month", y=[f"{agg_word}_{v}"]))
        if nums and texts:
            v, g = nums[0]["name"], texts[0]["name"]
            sql = (f"SELECT {g}, ROUND({agg}({v}), 2) AS {agg_word}_{v}, COUNT(*) AS rows FROM {t} "
                   f"GROUP BY {g} ORDER BY {agg_word}_{v} DESC NULLS LAST LIMIT {n}")
            return AgentPlan(intent="analytical", sql=sql, explanation=f"Top {n} {g} values by {agg_word} {v}.",
                             chart=ChartSpec(type="bar", x=g, y=[f"{agg_word}_{v}"]))
        if nums:
            v = nums[0]["name"]
            sql = f"SELECT ROUND({agg}({v}), 2) AS {agg_word}_{v}, COUNT({v}) AS non_missing_values FROM {t}"
            return AgentPlan(intent="analytical", sql=sql, explanation=f"The {agg_word} of {v} over all rows with a value.",
                             chart=ChartSpec(type="none"))
        if texts:
            g = texts[0]["name"]
            sql = f"SELECT {g}, COUNT(*) AS rows FROM {t} GROUP BY {g} ORDER BY rows DESC LIMIT {n}"
            return AgentPlan(intent="analytical", sql=sql, explanation=f"Number of rows per {g}.",
                             chart=ChartSpec(type="bar", x=g, y=["rows"]))
        if re.search(r"\b(how many|count|number of)\b.*\b(rows|records|entries|lines)\b", q):
            return AgentPlan(intent="analytical", sql=f"SELECT COUNT(*) AS row_count FROM {t}",
                             explanation="Number of rows in the dataset.", chart=ChartSpec(type="none"))
        return AgentPlan(
            intent="unsupported", explanation="Question not recognised.",
            unsupported_reason="Offline mode answers questions that name this dataset's columns: totals or averages of a "
            "numeric column, rankings by a text column, monthly trends with a date column, and row counts. "
            "Configure an LLM provider for open questions.")


def answer_generic(question: str, ds: dict[str, Any], resp: dict[str, Any], clarification: str | None, hist: list,
                   provider: LLMProvider, use_cache: bool, finish, ask_back) -> dict[str, Any]:
    """Fills `resp` (created by the main agent) for an imported dataset."""
    from app.agent.agent import MAX_REGENERATIONS
    from app.agent.evidence import build_generic_evidence

    from app.agent.offline_provider import OfflineRuleProvider

    # The retail rule-based planner does not apply to other schemas; any other provider (LLM or an
    # internal security stub) plans directly.
    planner = GenericOfflinePlanner(ds) if isinstance(provider, OfflineRuleProvider) else provider
    system = system_prompt(ds)
    ctx = PlanContext(question=question, history=hist, clarification=clarification)
    feedback = None
    validated = result = plan = None
    cache_info: dict[str, Any] = {}
    for attempt in range(MAX_REGENERATIONS + 1):
        resp["execution"]["attempts"] = attempt + 1
        resp["execution"]["regenerated"] = attempt > 0
        try:
            plan = planner.plan(system, user_prompt(question, clarification, hist, feedback), ctx)
        except LLMError as exc:
            resp.update(status="error", answer="The language model could not produce a plan.",
                        error={"code": "llm_error", "message": str(exc), "retryable": True})
            return finish()
        resp["explanation"] = plan.explanation
        if plan.intent == "clarification":
            return ask_back(plan.clarification_question or "Could you clarify?", plan.clarification_options[:4], "model")
        if plan.intent == "unsupported" or not plan.sql:
            resp.update(status="unsupported", answer=plan.unsupported_reason or "This dataset cannot answer that question.")
            return finish()
        resp["sql"] = plan.sql
        try:
            validated = execution.validate_for(ds, plan.sql)
        except SQLValidationError as exc:
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
            resp.update(status="error", answer="The dataset's storage is unavailable.",
                        error={"code": "dataset_unavailable", "message": str(exc), "retryable": False})
            return finish()

    assert result is not None and plan is not None and validated is not None
    resp["columns"] = [{"name": n, "type": t} for n, t in zip(result.columns, result.column_types)]
    resp["rows"] = result.rows
    resp["row_count"] = result.row_count
    resp["truncated"] = result.truncated
    resp["execution"]["db_ms"] = None if cache_info.get("hit") else result.duration_ms
    resp["execution"]["cache"] = cache_info
    all_null = bool(result.rows) and all(v is None for row in result.rows for v in row)
    resp["status"] = "success" if result.rows and not all_null else "empty"
    resp["answer"] = (summarize(result.columns, result.column_types, result.rows, result.truncated) if not all_null
                      else "The query ran successfully but found no matching rows.")
    resp["chart"] = choose_chart(plan.chart, result.columns, result.column_types, result.rows)
    resp["evidence"] = build_generic_evidence(ds, validated.sql, result.rows, result.truncated)
    return finish()


def _now() -> float:
    return time.time()
