"""Bounded, TTL-based cache of successful query results.

Key = SHA-256 of {normalised validated SQL, dataset id, dataset version/fingerprint, parameters,
metric-definition version, row limit}. Active filters are part of the SQL, so they are part of the
key. Only successful, validated, untruncated-or-truncated-as-executed results are stored; errors
and unvalidated SQL never are. Entries are invalidated per dataset on re-import, delete or rebuild,
and a new dataset version also changes the key, so a stale result can never match.

The app has no authentication, so the cache is shared application-wide (single-user deployment).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.config import get_settings


@dataclass
class CacheEntry:
    dataset_id: str
    dataset_version: str
    value: Any
    created: float


def rules_version() -> str:
    from app.database.business_rules import BUSINESS_RULES

    return hashlib.sha256(json.dumps(BUSINESS_RULES, sort_keys=True).encode()).hexdigest()[:12]


def make_key(sql: str, dataset_id: str, dataset_version: str, params: Any = None, max_rows: int | None = None) -> str:
    payload = {"sql": " ".join(sql.split()), "dataset": dataset_id, "version": dataset_version,
               "params": params, "rules": rules_version(), "max_rows": max_rows}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class ResultCache:
    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._data: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None or time.time() - entry.created > self.ttl:
                if entry is not None:
                    del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return entry

    def put(self, key: str, dataset_id: str, dataset_version: str, value: Any) -> None:
        with self._lock:
            self._data[key] = CacheEntry(dataset_id, dataset_version, value, time.time())
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def invalidate_dataset(self, dataset_id: str) -> int:
        with self._lock:
            keys = [k for k, e in self._data.items() if e.dataset_id == dataset_id]
            for k in keys:
                del self._data[k]
            return len(keys)

    def clear(self) -> int:
        with self._lock:
            n = len(self._data)
            self._data.clear()
            return n

    def status(self) -> dict[str, Any]:
        with self._lock:
            per_dataset: dict[str, int] = {}
            for e in self._data.values():
                per_dataset[e.dataset_id] = per_dataset.get(e.dataset_id, 0) + 1
            return {"entries": len(self._data), "max_entries": self.max_entries, "ttl_seconds": self.ttl,
                    "hits": self.hits, "misses": self.misses, "per_dataset": per_dataset,
                    "scope": "application-wide (no authentication)"}


_cache: ResultCache | None = None


def get_cache() -> ResultCache:
    global _cache
    if _cache is None:
        s = get_settings()
        _cache = ResultCache(s.cache_ttl_seconds, s.cache_max_entries)
    return _cache
