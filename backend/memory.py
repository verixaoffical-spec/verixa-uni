"""QA Memory (UC8): what Verixa learned from earlier runs and decisions, searched when new work arrives.

Embeddings: with EMBEDDING_MODEL empty, a local hashed word vector is used, so no failure text leaves the server.
Set EMBEDDING_MODEL (for example gemini/text-embedding-004) to use a provider through LiteLLM instead.
A memory that cannot be reached never stops a run (Req 8.8, BR17): every function here fails soft.
"""
import hashlib
import json
import logging
import math
import re

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from agents.redact import hide_secrets

from .qa_db import MemoryEntry, vector_ready
from .settings import settings

log = logging.getLogger(__name__)
MAX_TEXT = 2000


def _local_vector(value: str) -> list[float]:
    """Each word (and each pair of neighbouring words) adds to one of EMBEDDING_DIM slots. Similar failures share words,
    so their vectors point the same way. Simple, fast, and the same on every machine."""
    dim = max(8, settings.embedding_dim)
    words = re.findall(r"[a-z][a-z0-9_]{2,}", value.lower())
    vector = [0.0] * dim
    for token in words + [a + " " + b for a, b in zip(words, words[1:])]:
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dim] += 1.0 if digest[4] % 2 else -1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 5) for v in vector]


def embed(value: str) -> list[float]:
    if settings.embedding_model:
        try:
            import litellm
            data = litellm.embedding(model=settings.embedding_model, input=[value[:MAX_TEXT]],
                                     dimensions=settings.embedding_dim).data[0]
            vector = data["embedding"] if isinstance(data, dict) else data.embedding
            if len(vector) == settings.embedding_dim:
                return vector
            log.warning("embedding model returned %s numbers, expected %s. Using the local vector", len(vector), settings.embedding_dim)
        except Exception as exc:
            log.warning("embedding model failed (%s). Using the local vector", type(exc).__name__)
    return _local_vector(value)


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def remember(db: Session, project_id: int, repo: str, kind: str, value: str, module: str | None = None,
             pr_number: int | None = None, decision: str | None = None, user_id: int | None = None) -> int | None:
    """Saves one memory entry, with secrets removed first (Req 8.7). Returns its id, or None if memory is unavailable."""
    try:
        clean = hide_secrets(value)[0][:MAX_TEXT]
        vector = embed(clean)
        entry = MemoryEntry(project_id=project_id, repo=repo, kind=kind, text=clean, module=(module or None),
                            pr_number=pr_number, decision=decision, user_id=user_id, embedding=json.dumps(vector))
        db.add(entry)
        db.flush()
        if vector_ready():
            db.execute(text("UPDATE memory_entries SET embedding_vec = CAST(:v AS vector) WHERE id = :id"),
                       {"v": json.dumps(vector), "id": entry.id})
        return entry.id
    except Exception as exc:
        log.warning("could not save to QA Memory: %s", exc)
        return None


def similar(db: Session, project_id: int, value: str, kinds: tuple[str, ...] = ("real_bug",),
            limit: int | None = None) -> list[dict]:
    """The past entries most like this text, best first, above the similarity floor. [] when memory is unavailable."""
    limit = limit or settings.memory_top_k
    try:
        query = embed(hide_secrets(value)[0][:MAX_TEXT])
        if vector_ready():
            rows = db.execute(text(
                "SELECT id, 1 - (embedding_vec <=> CAST(:q AS vector)) AS score FROM memory_entries "
                "WHERE project_id = :p AND kind = ANY(:k) AND embedding_vec IS NOT NULL "
                "ORDER BY embedding_vec <=> CAST(:q AS vector) LIMIT :n"),
                {"q": json.dumps(query), "p": project_id, "k": list(kinds), "n": limit}).all()
            scores = {r.id: float(r.score) for r in rows}
            entries = db.scalars(select(MemoryEntry).where(MemoryEntry.id.in_(scores))).all()
        else:
            entries = db.scalars(select(MemoryEntry).where(MemoryEntry.project_id == project_id,
                                                           MemoryEntry.kind.in_(kinds))).all()
            scores = {e.id: cosine(query, json.loads(e.embedding)) for e in entries}
        found = [{**entry_json(e), "similarity": round(scores[e.id], 3)} for e in entries
                 if scores.get(e.id, 0) >= settings.memory_min_similarity]
        return sorted(found, key=lambda e: -e["similarity"])[:limit]
    except Exception as exc:
        log.warning("QA Memory search failed: %s", exc)
        return []


def real_bugs_in_module(repo: str, module: str) -> int:
    """How many real bugs Verixa itself found in this module. The Analysis Agent adds it to the module's bug history."""
    from .db import SessionLocal
    try:
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(MemoryEntry).where(
                MemoryEntry.repo == repo, MemoryEntry.module == module, MemoryEntry.kind == "real_bug")) or 0
    except Exception:
        return 0


def entry_json(e: MemoryEntry) -> dict:
    return {"id": e.id, "kind": e.kind, "module": e.module, "pr_number": e.pr_number, "text": e.text,
            "decision": e.decision, "created_at": e.created_at.isoformat() if e.created_at else None}
