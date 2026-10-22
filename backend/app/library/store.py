"""Saved queries: persistent, dataset-associated, revalidated on every use.

Stored in the app-state SQLite file (survives restarts). Only the title, question, SQL,
description, tags, category, parameter definitions and dataset association are stored: no API
keys, prompts or result rows. Saving a query never freezes its result; results come from the
normal execution path (and its versioned cache).

Parameters: SQL may contain {{name}} placeholders. Each must have a definition with a type
(integer, number, text, date). Values are converted to escaped SQL literals and the rendered SQL is
validated before it runs, so parameters cannot inject SQL.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import date
from typing import Any

from app.config import get_settings
from app.datasets import execution, registry
from app.security.sql_validator import SQLValidationError

_lock = threading.Lock()
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]{0,30})\s*\}\}")
PARAM_TYPES = ("integer", "number", "text", "date")
CATEGORIES = ("Products", "Revenue", "Customers", "Trends", "Geography", "Returns", "General")

SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_queries (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    question TEXT,
    sql TEXT NOT NULL,
    description TEXT,
    category TEXT,
    tags_json TEXT,
    parameters_json TEXT,
    dataset_id TEXT NOT NULL,
    dataset_name TEXT,
    dataset_version TEXT,
    required_columns_json TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT,
    use_count INTEGER NOT NULL DEFAULT 0
);
"""


class LibraryError(ValueError):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def _db() -> sqlite3.Connection:
    path = get_settings().app_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _now() -> str:
    from app.history import now_iso

    return now_iso()


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("tags", "parameters", "required_columns"):
        raw = d.pop(f"{k}_json", None)
        d[k] = json.loads(raw) if raw else []
    return d


# ----------------------------------------------------------------------------- parameters
def check_parameters(sql: str, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = set(PLACEHOLDER.findall(sql))
    defs = {}
    for p in params:
        name = str(p.get("name", "")).strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,30}", name):
            raise LibraryError(422, "invalid_parameter", f"Parameter name '{name}' must be lowercase letters, digits or _.")
        if p.get("type") not in PARAM_TYPES:
            raise LibraryError(422, "invalid_parameter", f"Parameter '{name}' needs a type: {', '.join(PARAM_TYPES)}.")
        if name in defs:
            raise LibraryError(422, "invalid_parameter", f"Parameter '{name}' is defined twice.")
        defs[name] = {"name": name, "type": p["type"], "default": p.get("default"),
                      "description": (p.get("description") or "")[:200]}
        _literal(defs[name], defs[name]["default"])  # default must be valid
    missing = names - set(defs)
    if missing:
        raise LibraryError(422, "missing_parameter", f"The SQL uses undefined parameters: {', '.join(sorted(missing))}.")
    unused = set(defs) - names
    if unused:
        raise LibraryError(422, "unused_parameter", f"Defined but not used in the SQL: {', '.join(sorted(unused))}.")
    return list(defs.values())


def _literal(defn: dict[str, Any], value: Any) -> str:
    name, ptype = defn["name"], defn["type"]
    if value is None or value == "":
        raise LibraryError(422, "missing_value", f"Parameter '{name}' needs a value.")
    try:
        if ptype == "integer":
            return str(int(str(value).strip()))
        if ptype == "number":
            v = float(str(value).strip())
            if v != v or v in (float("inf"), float("-inf")):
                raise ValueError
            return repr(v)
        if ptype == "date":
            return f"DATE '{date.fromisoformat(str(value).strip()).isoformat()}'"
    except ValueError as exc:
        raise LibraryError(422, "invalid_value", f"Parameter '{name}' must be a valid {ptype}.") from exc
    text = str(value)
    if len(text) > 200:
        raise LibraryError(422, "invalid_value", f"Parameter '{name}' is too long.")
    return "'" + text.replace("'", "''") + "'"


def render(sql: str, params: list[dict[str, Any]], values: dict[str, Any] | None) -> str:
    values = values or {}
    defs = {p["name"]: p for p in params}
    rendered = PLACEHOLDER.sub(lambda m: _literal(defs[m.group(1)], values.get(m.group(1), defs[m.group(1)].get("default"))), sql)
    if "{{" in rendered or "}}" in rendered:
        raise LibraryError(422, "malformed_placeholder", "The SQL contains a malformed {{parameter}} placeholder.")
    return rendered


# ----------------------------------------------------------------------------- compatibility
def compatibility(query: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
    """Can this query run on `target`? Re-validates the rendered SQL against the target's schema."""
    own = registry.get(query["dataset_id"])
    if target is None:
        return {"status": "unavailable", "reason": "No dataset selected."}
    if target["status"] != "ready":
        return {"status": "unavailable", "reason": f"Dataset '{target['name']}' is not ready."}
    try:
        sql = render(query["sql"], query.get("parameters", []), None)
        execution.validate_for(target, sql)
    except (SQLValidationError, LibraryError) as exc:
        missing = sorted(set(query.get("required_columns", [])) - registry.allowed_columns(target))
        detail = str(exc.message if isinstance(exc, LibraryError) else exc)
        if own is None:
            lead = f"The dataset it was saved for ('{query.get('dataset_name')}') has been deleted, and the SQL does not fit '{target['name']}'."
        elif target["id"] == query["dataset_id"]:
            lead = "The dataset was re-imported and its schema no longer matches this query."
        else:
            lead = f"It was written for '{query.get('dataset_name')}' and does not match the schema of '{target['name']}'."
        reason = f"{lead} ({detail})"
        return {"status": "incompatible", "reason": reason, "missing_columns": missing,
                "same_dataset": target["id"] == query["dataset_id"],
                "hint": "Adapt the question for this dataset in the AI Sales Analyst, then save the new version."}
    if target["id"] == query["dataset_id"]:
        return {"status": "compatible", "reason": "Validated against the current schema of its own dataset."}
    note = "Its own dataset was deleted." if own is None else f"It was saved for '{query.get('dataset_name')}'."
    return {"status": "other_dataset", "reason": f"{note} The SQL also validates against '{target['name']}', but running "
            "it there needs your explicit confirmation.", "missing_columns": []}


# ----------------------------------------------------------------------------- CRUD
def _validate_definition(sql: str, params: list[dict[str, Any]], ds: dict[str, Any]) -> tuple[list[dict], list[str], str]:
    if not sql or not sql.strip():
        raise LibraryError(422, "invalid_sql", "SQL is required.")
    params = check_parameters(sql, params)
    try:
        validated = execution.validate_for(ds, render(sql, params, None))
    except SQLValidationError as exc:
        raise LibraryError(422, "invalid_sql", f"The SQL does not validate against '{ds['name']}': {exc}") from exc
    return params, sorted(set(validated.columns) & registry.allowed_columns(ds)), validated.sql


def _title_taken(con: sqlite3.Connection, title: str, dataset_id: str, exclude: str | None = None) -> bool:
    return con.execute("SELECT 1 FROM saved_queries WHERE lower(title) = lower(?) AND dataset_id = ? AND id IS NOT ?",
                       (title.strip(), dataset_id, exclude)).fetchone() is not None


def create(data: dict[str, Any]) -> dict[str, Any]:
    ds = registry.get(data["dataset_id"])
    if ds is None or ds["status"] != "ready":
        raise LibraryError(404, "dataset_not_found", "The dataset for this query does not exist or is not ready.")
    params, required, _ = _validate_definition(data["sql"], data.get("parameters") or [], ds)
    qid = "sq_" + uuid.uuid4().hex[:12]
    ts = _now()
    with _lock:
        con = _db()
        try:
            if _title_taken(con, data["title"], ds["id"]):
                raise LibraryError(409, "duplicate_title", f"A saved query named '{data['title']}' already exists for this dataset.")
            con.execute("INSERT INTO saved_queries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)", (
                qid, data["title"].strip(), data.get("question"), data["sql"].strip(), data.get("description"),
                data.get("category") or "General", json.dumps(data.get("tags") or []), json.dumps(params), ds["id"],
                ds["name"], registry.version_key(ds), json.dumps(required), data.get("source") or "user", ts, ts, None))
            con.commit()
        finally:
            con.close()
    return get(qid)  # type: ignore[return-value]


def get(qid: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"sq_[0-9a-f]{12}", qid or ""):
        return None
    with _lock:
        con = _db()
        try:
            r = con.execute("SELECT * FROM saved_queries WHERE id = ?", (qid,)).fetchone()
        finally:
            con.close()
    return _row(r) if r else None


def list_queries(search: str | None = None, category: str | None = None, tag: str | None = None,
                 dataset_id: str | None = None) -> list[dict[str, Any]]:
    clauses, params = [], []
    if search:
        clauses.append("(title LIKE ? OR question LIKE ? OR description LIKE ? OR sql LIKE ?)")
        params += [f"%{search}%"] * 4
    if category:
        clauses.append("category = ?")
        params.append(category)
    if dataset_id:
        clauses.append("dataset_id = ?")
        params.append(dataset_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _lock:
        con = _db()
        try:
            rows = con.execute(f"SELECT * FROM saved_queries {where} ORDER BY COALESCE(last_used_at, updated_at) DESC", params).fetchall()
        finally:
            con.close()
    items = [_row(r) for r in rows]
    if tag:
        items = [q for q in items if tag.lower() in [t.lower() for t in q["tags"]]]
    return items


def update(qid: str, changes: dict[str, Any]) -> dict[str, Any]:
    q = get(qid)
    if q is None:
        raise LibraryError(404, "not_found", "Saved query not found.")
    merged = {**q, **{k: v for k, v in changes.items() if v is not None}}
    ds = registry.get(merged["dataset_id"])
    sql_changed = any(k in changes and changes[k] is not None for k in ("sql", "parameters"))
    required = q["required_columns"]
    params = q["parameters"]
    version = q["dataset_version"]
    if sql_changed:
        if ds is None or ds["status"] != "ready":
            raise LibraryError(409, "dataset_unavailable", "The query's dataset no longer exists; save it for another dataset instead.")
        params, required, _ = _validate_definition(merged["sql"], merged.get("parameters") or [], ds)
        version = registry.version_key(ds)
    with _lock:
        con = _db()
        try:
            if "title" in changes and changes["title"] and _title_taken(con, changes["title"], q["dataset_id"], qid):
                raise LibraryError(409, "duplicate_title", f"A saved query named '{changes['title']}' already exists for this dataset.")
            con.execute("UPDATE saved_queries SET title=?, question=?, sql=?, description=?, category=?, tags_json=?, "
                        "parameters_json=?, required_columns_json=?, dataset_version=?, updated_at=? WHERE id=?",
                        (merged["title"].strip(), merged.get("question"), merged["sql"].strip(), merged.get("description"),
                         merged.get("category") or "General", json.dumps(merged.get("tags") or []), json.dumps(params),
                         json.dumps(required), version, _now(), qid))
            con.commit()
        finally:
            con.close()
    return get(qid)  # type: ignore[return-value]


def duplicate(qid: str, title: str | None = None) -> dict[str, Any]:
    q = get(qid)
    if q is None:
        raise LibraryError(404, "not_found", "Saved query not found.")
    base = title or f"{q['title']} (copy)"
    candidate, n = base, 2
    with _lock:
        con = _db()
        try:
            while _title_taken(con, candidate, q["dataset_id"]):
                if title:
                    raise LibraryError(409, "duplicate_title", f"A saved query named '{title}' already exists for this dataset.")
                candidate = f"{base} {n}"
                n += 1
        finally:
            con.close()
    return create({**q, "title": candidate, "source": "user"})


def delete(qid: str) -> bool:
    with _lock:
        con = _db()
        try:
            n = con.execute("DELETE FROM saved_queries WHERE id = ?", (qid,)).rowcount
            con.commit()
        finally:
            con.close()
    return n > 0


def touch(qid: str) -> None:
    with _lock:
        con = _db()
        try:
            con.execute("UPDATE saved_queries SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?", (_now(), qid))
            con.commit()
        finally:
            con.close()


def count_for_dataset(dataset_id: str) -> int:
    with _lock:
        con = _db()
        try:
            return con.execute("SELECT COUNT(*) FROM saved_queries WHERE dataset_id = ?", (dataset_id,)).fetchone()[0]
        finally:
            con.close()
