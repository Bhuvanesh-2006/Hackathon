"""Query history and conversation state, persisted in a small SQLite file (never the analytics DB).

Only questions, generated SQL, status, timings and result summaries are stored. No credentials.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.agent.models import ConversationTurn
from app.config import get_settings

_lock = threading.Lock()
MAX_STORED_ROWS = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS query_history (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    clarification TEXT,
    status TEXT NOT NULL,
    duration_ms REAL,
    sql TEXT,
    summary TEXT,
    row_count INTEGER,
    provider TEXT,
    response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_conv ON query_history(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_history_created ON query_history(created_at);
"""


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    path = get_settings().app_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute("PRAGMA table_info(query_history)")}
        for col in ("dataset_id", "dataset_name"):  # additive migration for v1.2
            if col not in cols:
                con.execute(f"ALTER TABLE query_history ADD COLUMN {col} TEXT")
        yield con
        con.commit()
    finally:
        con.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save(response: dict[str, Any], question: str, clarification: str | None) -> None:
    stored = dict(response)
    if isinstance(stored.get("rows"), list) and len(stored["rows"]) > MAX_STORED_ROWS:
        stored["rows"] = stored["rows"][:MAX_STORED_ROWS]
        stored["stored_rows_truncated"] = True
    with _lock, _db() as con:
        ds = response.get("dataset") or {}
        con.execute(
            "INSERT OR REPLACE INTO query_history (id, conversation_id, created_at, question, clarification, status, "
            "duration_ms, sql, summary, row_count, provider, response_json, dataset_id, dataset_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                response["query_id"], response["conversation_id"], response["created_at"], question,
                clarification, response["status"], response["execution"].get("total_ms"),
                response.get("sql"), response.get("answer"), response.get("row_count"),
                response["execution"].get("provider"), json.dumps(stored, default=str),
                ds.get("id"), ds.get("name"),
            ),
        )


def list_history(limit: int = 50, offset: int = 0, status: str | None = None, search: str | None = None) -> tuple[list[dict], int]:
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if search:
        where.append("question LIKE ?")
        params.append(f"%{search}%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with _lock, _db() as con:
        total = con.execute(f"SELECT COUNT(*) FROM query_history {clause}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT id, conversation_id, created_at, question, clarification, status, duration_ms, sql, "
            f"summary, row_count, provider, dataset_id, dataset_name FROM query_history {clause} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [dict(r) for r in rows], total


def get_entry(query_id: str) -> dict | None:
    with _lock, _db() as con:
        row = con.execute("SELECT response_json FROM query_history WHERE id = ?", (query_id,)).fetchone()
    return json.loads(row[0]) if row else None


def conversation_turns(conversation_id: str) -> list[dict]:
    with _lock, _db() as con:
        rows = con.execute(
            "SELECT question, clarification, status, sql FROM query_history WHERE conversation_id = ? "
            "ORDER BY created_at, rowid",
            (conversation_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def conversation_history(conversation_id: str) -> list[ConversationTurn]:
    return [
        ConversationTurn(question=t["question"] + (f" ({t['clarification']})" if t["clarification"] else ""),
                         sql=t["sql"], intent=t["status"])
        for t in conversation_turns(conversation_id)
    ]


def pending_clarification(conversation_id: str) -> str | None:
    """The question behind the most recent clarifying question in this conversation."""
    for turn in reversed(conversation_turns(conversation_id)):
        if turn["status"] == "clarification":
            return turn["question"]
    return None


def clear() -> int:
    with _lock, _db() as con:
        return con.execute("DELETE FROM query_history").rowcount
