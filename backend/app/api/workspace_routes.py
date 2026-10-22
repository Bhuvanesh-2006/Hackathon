"""Dataset Manager, Saved Queries and cache endpoints."""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.errors import ApiError
from app.cache import get_cache
from app.config import get_settings
from app.datasets import importer, registry
from app.library import recommended as rec
from app.library import runner, store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
_import_locks: dict[str, threading.Lock] = {}
NAME_RE = re.compile(r"^[^\x00-\x1f]{1,80}$")


# ----------------------------------------------------------------------------- helpers
def _dataset_or_404(dataset_id: str) -> dict[str, Any]:
    ds = registry.get(dataset_id)
    if ds is None:
        raise ApiError(404, "not_found", "Dataset not found.")
    return ds


def _with_counts(ds: dict[str, Any]) -> dict[str, Any]:
    out = registry.public(ds)
    out["saved_query_count"] = store.count_for_dataset(ds["id"])
    return out


def _check_name(name: str, exclude: str | None = None) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ApiError(422, "invalid_name", "Dataset name must be 1-80 characters without control characters.")
    if registry.name_taken(name, exclude):
        raise ApiError(409, "duplicate_name", f"A dataset named '{name}' already exists.")
    return name


def _check_size(request: Request) -> None:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > (get_settings().max_upload_mb + 1) * 1024 * 1024:
        raise ApiError(413, "file_too_large", f"The upload exceeds the {get_settings().max_upload_mb} MB limit.")


def _do_import(ds: dict[str, Any], upload: UploadFile, reimport: bool) -> dict[str, Any]:
    lock = _import_locks.setdefault(ds["id"], threading.Lock())
    if not lock.acquire(blocking=False):
        raise ApiError(409, "import_in_progress", "An import is already running for this dataset.")
    raw = None
    try:
        try:
            raw, size, digest, fmt = importer.save_upload(upload.file, upload.filename or "")
            version = (ds["version"] or 0) + 1
            target = registry.storage_path(ds, version)
            meta = importer.import_upload(raw, fmt, target, size, digest)
        except importer.ImportFailed as exc:
            registry.mark_failed(ds["id"], [exc.message], exc.findings, keep_ready=reimport and ds["status"] == "ready")
            raise ApiError(422, "import_failed", exc.message + (" The previous version is unchanged." if reimport and ds["status"] == "ready" else ""))
        old_path = registry.storage_path(ds) if ds["version"] else None
        registry.mark_ready(ds["id"], version, meta, upload.filename or "", fmt)
        dropped = get_cache().invalidate_dataset(ds["id"])
        if old_path and old_path.exists():
            from app.database import connection

            connection.reset_connection(old_path)
            old_path.unlink(missing_ok=True)
        log.info("imported dataset %s v%s (%s rows); %s cache entries dropped", ds["id"], version, meta["row_count"], dropped)
        return _with_counts(registry.get(ds["id"]))  # type: ignore[arg-type]
    finally:
        if raw is not None:
            raw.unlink(missing_ok=True)
        lock.release()


# ----------------------------------------------------------------------------- datasets
@router.get("/datasets")
async def list_datasets() -> dict:
    items = await run_in_threadpool(lambda: [_with_counts(d) for d in registry.list_datasets()])
    return {"items": items, "active_id": registry.get_active_id(),
            "limits": {"max_upload_mb": get_settings().max_upload_mb, "formats": [".csv", ".xlsx"]}}


@router.post("/datasets", status_code=201)
async def upload_dataset(request: Request, file: UploadFile = File(...), name: str = Form(...),
                         description: str | None = Form(None)) -> dict:
    _check_size(request)
    name = _check_name(name)
    fmt = importer.ALLOWED_EXTENSIONS.get(("." + (file.filename or "").rsplit(".", 1)[-1].lower()) if "." in (file.filename or "") else "")
    if fmt is None:
        raise ApiError(415, "unsupported_type", "Unsupported file type. Supported: .csv, .xlsx.")
    ds = registry.create(name, (description or "")[:500] or None, (file.filename or "")[:200], fmt)
    try:
        return await run_in_threadpool(_do_import, ds, file, False)
    except ApiError as exc:
        exc.message += f" (dataset id {ds['id']} recorded as failed; delete it or re-import a corrected file)"
        raise


@router.get("/datasets/active")
async def active_dataset() -> dict:
    return {"active": _with_counts(_dataset_or_404(registry.get_active_id()))}


class ActiveRequest(BaseModel):
    dataset_id: str = Field(pattern=registry.DATASET_ID_PATTERN.pattern)


@router.put("/datasets/active")
async def set_active(body: ActiveRequest) -> dict:
    ds = _dataset_or_404(body.dataset_id)
    if ds["status"] != "ready":
        raise ApiError(409, "dataset_not_ready", f"Dataset '{ds['name']}' is not ready (status: {ds['status']}).")
    registry.set_active_id(ds["id"])
    return {"active": _with_counts(ds)}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str) -> dict:
    return _with_counts(_dataset_or_404(dataset_id))


@router.get("/datasets/{dataset_id}/preview")
async def preview_dataset(dataset_id: str, limit: int = Query(50, ge=1, le=200)) -> dict:
    ds = _dataset_or_404(dataset_id)
    if ds["status"] != "ready":
        raise ApiError(409, "dataset_not_ready", "This dataset has no imported data to preview.")
    from app.database import connection

    table = ds["table"]
    res = await run_in_threadpool(lambda: connection.run_query(f"SELECT * FROM {table} LIMIT {limit}",
                                                                db_path=registry.storage_path(ds), max_rows=limit))
    return {"columns": res.columns, "column_types": res.column_types, "rows": res.rows, "dataset_id": ds["id"]}


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)


@router.patch("/datasets/{dataset_id}")
async def rename_dataset(dataset_id: str, body: DatasetPatch) -> dict:
    ds = _dataset_or_404(dataset_id)
    if registry.is_builtin(ds):
        raise ApiError(403, "builtin_dataset", "The built-in demo dataset cannot be renamed.")
    name = _check_name(body.name, exclude=ds["id"]) if body.name is not None else None
    registry.update_details(ds["id"], name, body.description)
    return _with_counts(_dataset_or_404(dataset_id))


@router.post("/datasets/{dataset_id}/reimport")
async def reimport_dataset(request: Request, dataset_id: str, file: UploadFile = File(...)) -> dict:
    _check_size(request)
    ds = _dataset_or_404(dataset_id)
    if registry.is_builtin(ds):
        raise ApiError(403, "builtin_dataset", "Rebuild the built-in dataset with `python -m scripts.prepare_data`.")
    return await run_in_threadpool(_do_import, ds, file, True)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str) -> dict:
    ds = _dataset_or_404(dataset_id)
    if registry.is_builtin(ds):
        raise ApiError(403, "builtin_dataset", "The built-in demo dataset cannot be deleted.")
    affected = store.count_for_dataset(ds["id"])
    dropped = get_cache().invalidate_dataset(ds["id"])
    await run_in_threadpool(registry.delete, ds["id"])
    return {"deleted": ds["id"], "saved_queries_unavailable": affected, "cache_entries_dropped": dropped,
            "active_id": registry.get_active_id()}


# ----------------------------------------------------------------------------- saved queries
class Parameter(BaseModel):
    name: str = Field(max_length=31)
    type: str = Field(pattern="^(integer|number|text|date)$")
    default: Any = None
    description: str | None = Field(default=None, max_length=200)


class SavedQueryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    question: str | None = Field(default=None, max_length=500)
    sql: str = Field(min_length=1, max_length=8000)
    description: str | None = Field(default=None, max_length=1000)
    category: str = Field(default="General", pattern="^(Products|Revenue|Customers|Trends|Geography|Returns|General)$")
    tags: list[str] = Field(default_factory=list, max_length=10)
    parameters: list[Parameter] = Field(default_factory=list, max_length=10)
    dataset_id: str = Field(pattern=registry.DATASET_ID_PATTERN.pattern)


class SavedQueryPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    question: str | None = Field(default=None, max_length=500)
    sql: str | None = Field(default=None, min_length=1, max_length=8000)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, pattern="^(Products|Revenue|Customers|Trends|Geography|Returns|General)$")
    tags: list[str] | None = Field(default=None, max_length=10)
    parameters: list[Parameter] | None = Field(default=None, max_length=10)


class RunRequest(BaseModel):
    dataset_id: str = Field(pattern=registry.DATASET_ID_PATTERN.pattern)
    parameters: dict[str, Any] = Field(default_factory=dict)
    allow_other_dataset: bool = False
    use_cache: bool = True


def _lib_call(fn, *args):
    try:
        return fn(*args)
    except store.LibraryError as exc:
        err = ApiError(exc.status, exc.code, exc.message)
        err.details = exc.details  # type: ignore[attr-defined]
        raise err from exc


def _clean_tags(tags: list[str]) -> list[str]:
    return [t.strip()[:30] for t in tags if t and t.strip()][:10]


@router.get("/saved-queries")
async def list_saved(dataset_id: str = Query(..., pattern=registry.DATASET_ID_PATTERN.pattern),
                     search: str | None = Query(None, max_length=100), category: str | None = Query(None, max_length=20),
                     tag: str | None = Query(None, max_length=30), scope: str = Query("all", pattern="^(all|dataset)$")) -> dict:
    ds = _dataset_or_404(dataset_id)

    def build() -> dict:
        items = store.list_queries(search or None, category or None, tag or None, ds["id"] if scope == "dataset" else None)
        for q in items:
            q["compatibility"] = store.compatibility(q, ds)
        recs = rec.recommended(ds) if ds["status"] == "ready" else []
        if search:
            s = search.lower()
            recs = [r for r in recs if s in (r["title"] + " " + r["question"] + " " + r["sql"]).lower()]
        if category:
            recs = [r for r in recs if r["category"] == category]
        return {"dataset": {"id": ds["id"], "name": ds["name"]}, "recommended": recs, "items": items,
                "categories": list(store.CATEGORIES)}

    return await run_in_threadpool(build)


@router.post("/saved-queries", status_code=201)
async def create_saved(body: SavedQueryCreate) -> dict:
    data = body.model_dump()
    data["tags"] = _clean_tags(data["tags"])
    return await run_in_threadpool(_lib_call, store.create, data)


@router.get("/saved-queries/{qid}")
async def get_saved(qid: str, dataset_id: str | None = Query(None, pattern=registry.DATASET_ID_PATTERN.pattern)) -> dict:
    q = store.get(qid)
    if q is None:
        raise ApiError(404, "not_found", "Saved query not found.")
    q["compatibility"] = store.compatibility(q, registry.get(dataset_id or q["dataset_id"]))
    return q


@router.patch("/saved-queries/{qid}")
async def update_saved(qid: str, body: SavedQueryPatch) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "tags" in changes and changes["tags"] is not None:
        changes["tags"] = _clean_tags(changes["tags"])
    return await run_in_threadpool(_lib_call, store.update, qid, changes)


class DuplicateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)


@router.post("/saved-queries/{qid}/duplicate", status_code=201)
async def duplicate_saved(qid: str, body: DuplicateRequest) -> dict:
    return await run_in_threadpool(_lib_call, store.duplicate, qid, body.title)


@router.delete("/saved-queries/{qid}")
async def delete_saved(qid: str) -> dict:
    if not store.delete(qid):
        raise ApiError(404, "not_found", "Saved query not found.")
    return {"deleted": qid}


@router.post("/saved-queries/{qid}/run")
async def run_saved(qid: str, body: RunRequest) -> dict:
    return await run_in_threadpool(_lib_call, runner.run_saved, qid, body.dataset_id, body.parameters,
                                   body.allow_other_dataset, body.use_cache)


@router.post("/recommended-queries/{rec_id}/run")
async def run_recommended(rec_id: str, body: RunRequest) -> dict:
    ds = _dataset_or_404(body.dataset_id)
    item = next((r for r in rec.recommended(ds) if r["id"] == rec_id), None)
    if item is None:
        raise ApiError(404, "not_found", "This recommended query does not exist for the selected dataset.")
    return await run_in_threadpool(_lib_call, runner.run_definition, item, ds, body.parameters, body.use_cache)


# ----------------------------------------------------------------------------- cache
@router.get("/cache")
async def cache_status() -> dict:
    return get_cache().status()


@router.delete("/cache")
async def clear_cache(dataset_id: str | None = Query(None, pattern=registry.DATASET_ID_PATTERN.pattern)) -> dict:
    cache = get_cache()
    return {"cleared": cache.invalidate_dataset(dataset_id) if dataset_id else cache.clear(), "dataset_id": dataset_id}
