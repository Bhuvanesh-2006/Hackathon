"""Single execution path for validated SQL against one dataset, with result caching."""
from __future__ import annotations

import time
from typing import Any

from app.cache import get_cache, make_key
from app.config import get_settings
from app.database import connection
from app.datasets import registry
from app.security.sql_validator import ValidatedSQL, validate_sql


def validate_for(ds: dict[str, Any], sql: str) -> ValidatedSQL:
    """Validate against the selected dataset's own table and columns only."""
    return validate_sql(sql, registry.allowed_tables(ds), registry.allowed_columns(ds))


def execute(ds: dict[str, Any], validated: ValidatedSQL, *, use_cache: bool = True,
            params_for_key: Any = None) -> tuple[connection.QueryResult, dict[str, Any]]:
    """Run already-validated SQL on the dataset's own read-only storage. Only successes are cached."""
    max_rows = get_settings().max_result_rows
    version = registry.version_key(ds)
    key = make_key(validated.sql, ds["id"], version, params_for_key, max_rows)
    cache = get_cache()
    if use_cache:
        entry = cache.get(key)
        if entry is not None:
            age = time.time() - entry.created
            return entry.value, {"hit": True, "cached_at": entry.created, "age_seconds": round(age, 1),
                                 "dataset_version": entry.dataset_version, "ttl_seconds": cache.ttl}
    result = connection.run_query(validated.sql, db_path=registry.storage_path(ds), max_rows=max_rows)
    if use_cache:
        cache.put(key, ds["id"], version, result)
    return result, {"hit": False, "cached_at": time.time(), "age_seconds": 0.0, "dataset_version": version,
                    "ttl_seconds": cache.ttl, "stored": use_cache}
