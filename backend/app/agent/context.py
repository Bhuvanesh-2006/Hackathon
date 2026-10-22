"""Conversation state: active filters, comparison period, previous result keys.

Active filters are extracted from the executed (validated) SQL, so what the UI shows as
"active filters" is what was actually applied, not what a model claims it applied. The state
is stored in the app-state SQLite file next to the query history.

The state only ever reaches SQL through the planner, and every planned query still goes
through the SQL validator and the read-only connection. Context cannot bypass either.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import date, timedelta
from typing import Any

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp

from app.config import get_settings

_lock = threading.Lock()
KEY_COLUMNS = ("stock_code", "customer_id", "country")
MAX_KEYS = 50
FILTER_FIELDS = ("country", "year", "date_from", "date_to", "stock_codes", "customer_id")


class Comparison(BaseModel):
    current: tuple[str, str]  # [start, end) ISO dates
    previous: tuple[str, str]
    label: str


class ConversationState(BaseModel):
    dataset_id: str | None = None  # a conversation is bound to one dataset
    filters: dict[str, Any] = Field(default_factory=dict)
    removed: list[str] = Field(default_factory=list)
    root_question: str | None = None
    last_question: str | None = None
    last_sql: str | None = None
    last_keys: dict[str, Any] | None = None
    comparison: Comparison | None = None
    topic: dict[str, Any] | None = None


# ----------------------------------------------------------------------------- persistence
def _db() -> sqlite3.Connection:
    path = get_settings().app_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at TEXT)")
    return con


def load(conversation_id: str) -> ConversationState:
    with _lock:
        con = _db()
        try:
            row = con.execute("SELECT state_json FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        finally:
            con.close()
    return ConversationState.model_validate_json(row[0]) if row else ConversationState()


def save(conversation_id: str, state: ConversationState) -> None:
    from app.history import now_iso

    with _lock:
        con = _db()
        try:
            con.execute("INSERT OR REPLACE INTO conversations VALUES (?, ?, ?)",
                        (conversation_id, state.model_dump_json(), now_iso()))
            con.commit()
        finally:
            con.close()


def clear_all() -> None:
    with _lock:
        con = _db()
        try:
            con.execute("DELETE FROM conversations")
            con.commit()
        finally:
            con.close()


# ----------------------------------------------------------------------------- filter extraction
def _literal(node: exp.Expression) -> Any:
    """Return the Python value of a literal, unwrapping casts such as DATE '2011-01-01'."""
    while isinstance(node, (exp.Cast, exp.TryCast)) or type(node).__name__ in ("TsOrDsToDate", "StrToDate"):
        node = node.this
    if isinstance(node, exp.Literal):
        return int(node.this) if not node.is_string and re.fullmatch(r"-?\d+", node.this) else node.this
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        return -int(node.this.this)
    return None


def _column(node: exp.Expression) -> str | None:
    if isinstance(node, (exp.Upper, exp.Lower)):
        node = node.this
    return node.name.lower() if isinstance(node, exp.Column) else None


def _in_where(node: exp.Expression) -> bool:
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Filter):  # aggregate FILTER (WHERE ...) is a measure, not a scope filter
            return False
        if isinstance(parent, exp.Where):
            return True
        parent = parent.parent
    return False


def extract_filters(sql: str | None) -> dict[str, Any]:
    if not sql:
        return {}
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return {}
    out: dict[str, Any] = {}
    for node in tree.walk():
        if not _in_where(node):
            continue
        if isinstance(node, exp.EQ):
            col, val = _column(node.this), _literal(node.expression)
            if col == "country" and isinstance(val, str):
                out["country"] = val
            elif col == "invoice_year" and isinstance(val, int):
                out["year"] = val
            elif col == "stock_code" and isinstance(val, str):
                out["stock_codes"] = [val.upper()]
            elif col == "customer_id" and isinstance(val, str):
                out["customer_id"] = val
        elif isinstance(node, exp.In) and _column(node.this) == "stock_code":
            vals = [_literal(e) for e in node.expressions]
            if vals and all(isinstance(v, str) for v in vals):
                out["stock_codes"] = [v.upper() for v in vals]
        elif isinstance(node, (exp.GTE, exp.GT, exp.LT, exp.LTE)) and _column(node.this) in ("invoice_date", "invoice_month"):
            val = _literal(node.expression)
            if isinstance(val, str) and re.match(r"\d{4}-\d{2}-\d{2}", val):
                key = "date_from" if isinstance(node, (exp.GTE, exp.GT)) else "date_to"
                out[key] = val[:10]
        elif isinstance(node, exp.Between) and _column(node.this) in ("invoice_date", "invoice_month"):
            lo, hi = _literal(node.args.get("low")), _literal(node.args.get("high"))
            if isinstance(lo, str) and isinstance(hi, str):
                out["date_from"], out["date_to"] = lo[:10], hi[:10]
    return out


def filter_labels(filters: dict[str, Any]) -> list[dict[str, Any]]:
    labels = []
    if "country" in filters:
        labels.append({"field": "country", "label": f"Country: {filters['country']}"})
    if "year" in filters:
        labels.append({"field": "year", "label": f"Year: {filters['year']}"})
    if "date_from" in filters or "date_to" in filters:
        labels.append({"field": "date_range", "label": f"Dates: {filters.get('date_from', 'start')} to {filters.get('date_to', 'end')} (end exclusive)"})
    if "stock_codes" in filters:
        codes = filters["stock_codes"]
        labels.append({"field": "stock_codes", "label": f"Products: {', '.join(codes[:3])}{' +' + str(len(codes) - 3) if len(codes) > 3 else ''}"})
    if "customer_id" in filters:
        labels.append({"field": "customer_id", "label": f"Customer: {filters['customer_id']}"})
    return labels


def result_keys(columns: list[str], rows: list[list[Any]]) -> dict[str, Any] | None:
    for col in KEY_COLUMNS:
        if col in columns:
            i = columns.index(col)
            values = [str(r[i]) for r in rows if r[i] is not None][:MAX_KEYS]
            if values:
                return {"column": col, "values": values, "total_rows": len(rows)}
    return None


# ----------------------------------------------------------------------------- follow-up helpers
FOLLOW_UP = re.compile(r"^\s*(now|only|just|what about|how about|and|same|but|compare|also|those|these|for those|for them|filter)\b", re.I)
THOSE = re.compile(r"\b(those|these|them|that list|the same)\s*(products?|items?|customers?|countries)?\b", re.I)
COMPARE_PREVIOUS = re.compile(r"\b(compare|vs\.?|versus|against|change from)\b.*\b(previous|prior|last|preceding)\s+(month|period|week)\b"
                              r"|\b(month|period|week)\s+(before|earlier)\b|\bmonth[- ]over[- ]month\b", re.I)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], start=1)}


def is_follow_up(question: str) -> bool:
    return bool(FOLLOW_UP.match(question) or THOSE.search(question))


def month_window(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, end


def parse_comparison(text: str) -> Comparison | None:
    """Parse 'November 2011 vs October 2011' or 'December 2011 (1-9 Dec) vs November 2011 (1-9 Nov)'."""
    found = re.findall(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", text.lower())
    if len(found) < 2:
        return None
    (m1, y1), (m2, y2) = found[0], found[1]
    cur = month_window(int(y1), MONTHS[m1])
    prev = month_window(int(y2), MONTHS[m2])
    days = re.search(r"\b1\s*[-–]\s*(\d{1,2})\b", text)
    label = f"{m1.title()} {y1} vs {m2.title()} {y2}"
    if days:
        last = int(days.group(1))
        cur = (cur[0], cur[0] + timedelta(days=last))
        prev = (prev[0], prev[0] + timedelta(days=last))
        label = f"1-{last} {m1.title()[:3]} {y1} vs 1-{last} {m2.title()[:3]} {y2}"
    return Comparison(current=(cur[0].isoformat(), cur[1].isoformat()), previous=(prev[0].isoformat(), prev[1].isoformat()), label=label)


def previous_window(filters: dict[str, Any]) -> Comparison | None:
    """Equivalent previous window for an active date range (calendar month -> previous month)."""
    if "date_from" not in filters or "date_to" not in filters:
        if "year" in filters:
            y = int(filters["year"])
            return Comparison(current=(f"{y}-01-01", f"{y + 1}-01-01"), previous=(f"{y - 1}-01-01", f"{y}-01-01"),
                              label=f"{y} vs {y - 1}")
        return None
    start, end = date.fromisoformat(filters["date_from"]), date.fromisoformat(filters["date_to"])
    if start.day == 1 and end == month_window(start.year, start.month)[1]:
        pm = start.month - 1 or 12
        py = start.year - (start.month == 1)
        p = month_window(py, pm)
        return Comparison(current=(start.isoformat(), end.isoformat()), previous=(p[0].isoformat(), p[1].isoformat()),
                          label=f"{start:%b %Y} vs {p[0]:%b %Y}")
    length = end - start
    return Comparison(current=(start.isoformat(), end.isoformat()),
                      previous=((start - length).isoformat(), start.isoformat()),
                      label=f"{start} to {end} vs the previous {length.days} days")


def comparison_options() -> list[str]:
    return [
        "November 2011 vs October 2011",
        "October 2011 vs September 2011",
        "December 2011 (1-9 Dec, partial) vs November 2011 (1-9 Nov)",
    ]


def describe_for_prompt(state: ConversationState) -> str:
    """Conversation state as reference data for the LLM prompt."""
    lines = []
    active = {k: v for k, v in state.filters.items() if k not in state.removed}
    if active:
        lines.append("ACTIVE FILTERS (keep applying them unless the user changes or removes them): "
                     + json.dumps(active))
    if state.removed:
        lines.append("FILTERS THE USER REMOVED (do not apply them): " + ", ".join(state.removed))
    if state.comparison:
        lines.append(f"COMPARISON PERIOD: current {state.comparison.current[0]} to {state.comparison.current[1]}, "
                     f"previous {state.comparison.previous[0]} to {state.comparison.previous[1]} (end dates exclusive)")
    if state.last_keys:
        lines.append(f"'Those/these {state.last_keys['column']}s' refers to these values from the previous result: "
                     + json.dumps(state.last_keys["values"]))
    if state.topic:
        lines.append("INVESTIGATION TOPIC: " + json.dumps(state.topic))
    return "\n".join(lines)
