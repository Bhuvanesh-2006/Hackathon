"""Dataset registry: stable IDs mapped to controlled storage, schema metadata and status.

* The built-in demo dataset (UCI Online Retail II) is synthesised from the existing
  retail.duckdb and its curated schema; it cannot be deleted or re-imported through the UI.
* Each imported dataset gets an internal ID (ds_<hex>) and its own DuckDB file under
  data/datasets/<id>/v<version>.duckdb containing exactly one table named `data`. A query
  therefore can only ever see one dataset's records.
* User-supplied names are display text only. They never become SQL identifiers; columns use
  sanitised identifiers with the original header kept as metadata.
* The application has no authentication, so the "active dataset" is a single application-wide
  setting. It is not per-user isolation.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from app.config import get_settings

BUILTIN_ID = "online_retail_ii"
IMPORTED_TABLE = "data"
DATASET_ID_PATTERN = re.compile(r"^(online_retail_ii|ds_[0-9a-f]{12})$")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    source_filename TEXT,
    file_format TEXT,
    status TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT,
    row_count INTEGER,
    column_count INTEGER,
    columns_json TEXT,
    findings_json TEXT,
    errors_json TEXT,
    support_json TEXT,
    file_size_bytes INTEGER,
    created_at TEXT NOT NULL,
    imported_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT);
"""


def _db() -> sqlite3.Connection:
    path = get_settings().app_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now_iso() -> str:
    from app.history import now_iso as _now

    return _now()


def new_id() -> str:
    return "ds_" + uuid.uuid4().hex[:12]


# ----------------------------------------------------------------------------- built-in dataset
def _builtin() -> dict[str, Any]:
    from app.database import connection
    from app.database.business_rules import DATASET_INFO
    from app.database.schema_catalog import COLUMNS

    settings = get_settings()
    loaded = settings.duckdb_path.exists()
    meta: dict[str, Any] = {}
    if loaded:
        try:
            meta = connection.fetch_metadata()
        except Exception:
            meta = {}
    return {
        "id": BUILTIN_ID, "name": "Online Retail II (built-in demo)", "kind": "builtin",
        "description": DATASET_INFO["description"], "source_filename": "online_retail_II.xlsx",
        "file_format": "xlsx (prepared by scripts/prepare_data.py)",
        "status": "ready" if loaded else "not_loaded", "version": 1,
        "fingerprint": str(meta.get("prepared_at", "")), "row_count": meta.get("row_count"),
        "column_count": len(COLUMNS),
        "columns": [{"name": c["name"], "original_name": c["name"], "type": c["type"], "description": c["description"]}
                    for c in COLUMNS],
        "findings": [], "errors": [],
        "support": ["Curated retail business rules (net/gross revenue, cancellations, returns, orders, customers)",
                    "Anomaly detection, contribution analysis and forecasting", "Reliability benchmark"],
        "table": "transactions", "created_at": meta.get("prepared_at"), "imported_at": meta.get("prepared_at"),
        "updated_at": meta.get("prepared_at"), "file_size_bytes": meta.get("source_file_size_bytes"),
    }


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for key in ("columns", "findings", "errors", "support"):
        raw = d.pop(f"{key}_json", None)
        d[key] = json.loads(raw) if raw else []
    d["kind"] = "imported"
    d["table"] = IMPORTED_TABLE
    return d


# ----------------------------------------------------------------------------- queries
def list_datasets() -> list[dict[str, Any]]:
    with _lock:
        con = _db()
        try:
            rows = con.execute("SELECT * FROM datasets ORDER BY created_at").fetchall()
        finally:
            con.close()
    return [_builtin(), *[_row_to_dict(r) for r in rows]]


def get(dataset_id: str | None) -> dict[str, Any] | None:
    if not dataset_id or not DATASET_ID_PATTERN.match(dataset_id):
        return None
    if dataset_id == BUILTIN_ID:
        return _builtin()
    with _lock:
        con = _db()
        try:
            row = con.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        finally:
            con.close()
    return _row_to_dict(row) if row else None


def storage_path(ds: dict[str, Any], version: int | None = None) -> Path:
    if ds["id"] == BUILTIN_ID:
        return get_settings().duckdb_path
    return get_settings().datasets_dir / ds["id"] / f"v{version or ds['version']}.duckdb"


def is_builtin(ds: dict[str, Any] | None) -> bool:
    return bool(ds) and ds["id"] == BUILTIN_ID


def allowed_tables(ds: dict[str, Any]) -> set[str]:
    return {ds["table"]}


def allowed_columns(ds: dict[str, Any]) -> set[str]:
    return {c["name"] for c in ds["columns"]}


def version_key(ds: dict[str, Any]) -> str:
    """Changes whenever the stored data changes (re-import, rebuild)."""
    return f"{ds['id']}:v{ds['version']}:{(ds.get('fingerprint') or '')[:16]}"


def public(ds: dict[str, Any]) -> dict[str, Any]:
    """Client-safe view: no filesystem paths."""
    return {k: v for k, v in ds.items() if k not in ("storage", "path")}


# ----------------------------------------------------------------------------- writes
def create(name: str, description: str | None, source_filename: str, file_format: str) -> dict[str, Any]:
    ds_id = new_id()
    ts = now_iso()
    with _lock:
        con = _db()
        try:
            con.execute("INSERT INTO datasets (id, name, description, source_filename, file_format, status, version, "
                        "created_at, updated_at) VALUES (?,?,?,?,?,?,0,?,?)",
                        (ds_id, name, description, source_filename, file_format, "importing", ts, ts))
            con.commit()
        finally:
            con.close()
    return get(ds_id)  # type: ignore[return-value]


def mark_ready(ds_id: str, version: int, meta: dict[str, Any], source_filename: str, file_format: str) -> None:
    ts = now_iso()
    with _lock:
        con = _db()
        try:
            con.execute(
                "UPDATE datasets SET status='ready', version=?, fingerprint=?, row_count=?, column_count=?, columns_json=?, "
                "findings_json=?, errors_json='[]', support_json=?, file_size_bytes=?, source_filename=?, file_format=?, "
                "imported_at=?, updated_at=? WHERE id=?",
                (version, meta["fingerprint"], meta["row_count"], meta["column_count"], json.dumps(meta["columns"]),
                 json.dumps(meta["findings"]), json.dumps(meta["support"]), meta["file_size_bytes"], source_filename,
                 file_format, ts, ts, ds_id))
            con.commit()
        finally:
            con.close()


def mark_failed(ds_id: str, errors: list[str], findings: list[str], keep_ready: bool) -> None:
    """Record a failed import. A dataset that already had a good version stays 'ready' on it."""
    with _lock:
        con = _db()
        try:
            if keep_ready:
                con.execute("UPDATE datasets SET errors_json=?, updated_at=? WHERE id=?",
                            (json.dumps(errors + findings), now_iso(), ds_id))
            else:
                con.execute("UPDATE datasets SET status='failed', errors_json=?, findings_json=?, updated_at=? WHERE id=?",
                            (json.dumps(errors), json.dumps(findings), now_iso(), ds_id))
            con.commit()
        finally:
            con.close()


def update_details(ds_id: str, name: str | None, description: str | None) -> None:
    with _lock:
        con = _db()
        try:
            if name is not None:
                con.execute("UPDATE datasets SET name=?, updated_at=? WHERE id=?", (name, now_iso(), ds_id))
            if description is not None:
                con.execute("UPDATE datasets SET description=?, updated_at=? WHERE id=?", (description, now_iso(), ds_id))
            con.commit()
        finally:
            con.close()


def name_taken(name: str, exclude_id: str | None = None) -> bool:
    if name.strip().lower() == _builtin()["name"].lower():
        return True
    with _lock:
        con = _db()
        try:
            row = con.execute("SELECT 1 FROM datasets WHERE lower(name) = lower(?) AND id IS NOT ?", (name.strip(), exclude_id)).fetchone()
        finally:
            con.close()
    return row is not None


def delete(ds_id: str) -> None:
    import shutil

    from app.database import connection

    ds = get(ds_id)
    if not ds or is_builtin(ds):
        return
    folder = get_settings().datasets_dir / ds_id
    for f in folder.glob("*.duckdb") if folder.exists() else []:
        connection.reset_connection(f)
    with _lock:
        con = _db()
        try:
            con.execute("DELETE FROM datasets WHERE id = ?", (ds_id,))
            if (con.execute("SELECT value FROM app_settings WHERE key='active_dataset'").fetchone() or [None])[0] == ds_id:
                con.execute("DELETE FROM app_settings WHERE key='active_dataset'")
            con.commit()
        finally:
            con.close()
    # Only this dataset's own folder (derived from its internal ID) is removed.
    if folder.exists() and folder.parent == get_settings().datasets_dir:
        shutil.rmtree(folder, ignore_errors=True)


# ----------------------------------------------------------------------------- active dataset
def get_active_id() -> str:
    with _lock:
        con = _db()
        try:
            row = con.execute("SELECT value FROM app_settings WHERE key='active_dataset'").fetchone()
        finally:
            con.close()
    if row and get(row[0]) and get(row[0])["status"] == "ready":
        return row[0]
    return BUILTIN_ID


def set_active_id(ds_id: str) -> None:
    with _lock:
        con = _db()
        try:
            con.execute("INSERT OR REPLACE INTO app_settings VALUES ('active_dataset', ?)", (ds_id,))
            con.commit()
        finally:
            con.close()


def schema_text(ds: dict[str, Any]) -> str:
    lines = [f"TABLE {ds['table']} ("]
    for c in ds["columns"]:
        extra = f"  -- original header: {json.dumps(c.get('original_name'))}" if c.get("original_name") != c["name"] else ""
        samples = c.get("samples")
        sample_txt = f"; examples: {', '.join(json.dumps(s) for s in samples[:3])}" if samples else ""
        role = f"; {c['role']}" if c.get("role") else ""
        lines.append(f"  {c['name']} {c['type']}{extra}{role}{sample_txt}")
    lines.append(")")
    return "\n".join(lines)
