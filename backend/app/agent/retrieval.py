"""Retrieval of verified SQL examples and short notes for the LLM prompt.

Backends (RETRIEVAL_BACKEND):
  * "bge-faiss" - BAAI/bge-large-en-v1.5 embeddings (sentence-transformers) in a FAISS
                  inner-product index over L2-normalised vectors (= cosine similarity).
  * "keyword"   - dependency-free token-overlap scoring (BM25-style weighting).
  * "none"      - retrieval disabled.
If "bge-faiss" cannot load (package or model missing), the keyword backend is used and the
status says why.

Safety: the full schema and every business rule are always in the system prompt; retrieval only
adds examples and notes. All documents are repository content, every example SQL passes the
validator (tests/test_retrieval.py), and retrieved text is placed in the prompt as reference
data. Generated SQL is validated regardless of what was retrieved.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from app.agent.examples import EXAMPLES, NOTES
from app.config import get_settings

log = logging.getLogger(__name__)
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "of", "in", "by", "for", "and", "to", "with", "what", "which", "is", "are", "was",
        "were", "how", "much", "many", "our", "we", "did", "do", "does", "on", "at", "from", "me", "show"}


@dataclass
class Doc:
    id: str
    kind: str  # example | note
    text: str  # what is embedded / matched
    question: str | None = None
    sql: str | None = None


def documents() -> list[Doc]:
    docs = [Doc(e["id"], "example", e["question"], e["question"], e["sql"]) for e in EXAMPLES]
    docs += [Doc(n["id"], "note", n["text"]) for n in NOTES]
    return docs


def _tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


class KeywordRetriever:
    name = "keyword"

    def __init__(self, docs: list[Doc]) -> None:
        self.docs = docs
        self.tf = [Counter(_tokens(d.text + " " + (d.sql or ""))) for d in docs]
        df = Counter(t for tf in self.tf for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, query: str, k: int) -> list[tuple[Doc, float]]:
        q = _tokens(query)
        scored = []
        for doc, tf in zip(self.docs, self.tf):
            s = sum(self.idf.get(t, 0) * (tf[t] / (tf[t] + 1.2)) for t in q if t in tf)
            if s > 0:
                scored.append((doc, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


class BgeFaissRetriever:
    name = "bge-faiss"

    def __init__(self, docs: list[Doc], model_name: str) -> None:
        import os

        # Use the PyTorch path only; a TensorFlow/Keras 3 install would otherwise break transformers.
        os.environ.setdefault("USE_TF", "0")
        os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
        import faiss  # noqa: F401  (import errors surface as fallback)
        import numpy as np
        from sentence_transformers import SentenceTransformer

        t0 = time.perf_counter()
        self.docs = docs
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")
        vecs = self.model.encode([d.text for d in docs], normalize_embeddings=True, convert_to_numpy=True)
        self.index = faiss.IndexFlatIP(vecs.shape[1])
        self.index.add(np.asarray(vecs, dtype="float32"))
        self.dim = int(vecs.shape[1])
        self.load_seconds = round(time.perf_counter() - t0, 1)

    def search(self, query: str, k: int) -> list[tuple[Doc, float]]:
        import numpy as np

        q = self.model.encode([BGE_QUERY_PREFIX + query], normalize_embeddings=True, convert_to_numpy=True)
        scores, idx = self.index.search(np.asarray(q, dtype="float32"), min(k, len(self.docs)))
        return [(self.docs[i], float(s)) for s, i in zip(scores[0], idx[0]) if i >= 0]


_lock = threading.Lock()
_status: dict = {"backend": None, "state": "not_loaded", "note": None}


@lru_cache(maxsize=1)
def get_retriever():
    settings = get_settings()
    choice = settings.retrieval_backend.lower().strip()
    docs = documents()
    with _lock:
        if choice == "none":
            _status.update(backend="none", state="disabled", note="Retrieval disabled by configuration.")
            return None
        if choice == "bge-faiss":
            try:
                r = BgeFaissRetriever(docs, settings.embedding_model)
                _status.update(backend=r.name, state="ready", model=r.model_name, dim=r.dim, documents=len(docs),
                               load_seconds=r.load_seconds, note=None)
                return r
            except Exception as exc:  # missing package / model download failure
                log.warning("BGE/FAISS retrieval unavailable, falling back to keyword: %s", exc)
                _status.update(note=f"bge-faiss unavailable ({type(exc).__name__}); using keyword retrieval.")
        r = KeywordRetriever(docs)
        _status.update(backend=r.name, state="ready", documents=len(docs), model=None)
        return r


def status() -> dict:
    return dict(_status)


def warm_up_in_background() -> None:
    threading.Thread(target=get_retriever, daemon=True, name="retrieval-warmup").start()


def retrieve(query: str, k_examples: int = 4, k_notes: int = 3) -> dict:
    r = get_retriever()
    if r is None:
        return {"backend": "none", "examples": [], "notes": []}
    hits = r.search(query, k_examples + k_notes + 6)
    examples = [(d, s) for d, s in hits if d.kind == "example"][:k_examples]
    notes = [(d, s) for d, s in hits if d.kind == "note"][:k_notes]
    return {
        "backend": r.name,
        "examples": [{"id": d.id, "question": d.question, "sql": d.sql, "score": round(s, 3)} for d, s in examples],
        "notes": [{"id": d.id, "text": d.text, "score": round(s, 3)} for d, s in notes],
    }
