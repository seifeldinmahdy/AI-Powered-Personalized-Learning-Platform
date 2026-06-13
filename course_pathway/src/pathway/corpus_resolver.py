"""Resolve a Django ``course_id`` to its stable ``corpus_id``.

This runs inside the AI-service process and is the single place the
``course_id -> corpus_id`` mapping is obtained. The mapping is **immutable**
(a course's corpus_id never changes), so it is cached forever after first
lookup. Both the pathway router and the assessment generator import this, so
there is exactly one resolver shared across every retrieval consumer.

It lives under ``pathway/`` (rather than ai_service) because both consumers
already import from ``pathway.*`` and this avoids a course_pathway <-> ai_service
circular import — consistent with how ``pathway.llm.naming`` /
``pathway.chromadb_reader`` are already shared.

Why resolve server-side instead of trusting a client-sent corpus_id: scope is a
security/correctness boundary. Resolving it from the SoR (Django) means a
browser can never widen or spoof its retrieval scope.
"""

from __future__ import annotations

import os
import threading

import httpx
import structlog

logger = structlog.get_logger(__name__)

# course_id (str) -> corpus_id (str). Immutable mapping → cache for process life.
_cache: dict[str, str] = {}
_lock = threading.Lock()

_DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")
_TIMEOUT = float(os.getenv("CORPUS_RESOLVE_TIMEOUT", "10"))


class CorpusResolutionError(RuntimeError):
    """Raised when a course's corpus cannot be resolved."""


def resolve_corpus_id(course_id: str) -> str | None:
    """Return the ``corpus_id`` for *course_id*, or ``None`` if undefined.

    Result is cached; ``None`` is **not** cached so a corpus created later is
    picked up without a restart.
    """
    key = str(course_id)
    cached = _cache.get(key)
    if cached:
        return cached

    corpus_id = _fetch_corpus_id(key)
    if corpus_id:
        with _lock:
            _cache[key] = corpus_id
    return corpus_id


def _fetch_corpus_id(course_id: str) -> str | None:
    url = f"{_DJANGO_API_URL}/courses/courses/{course_id}/corpus/"
    try:
        resp = httpx.get(url, timeout=_TIMEOUT)
    except Exception as exc:  # network/Django down — let caller surface a clear error
        logger.warning("corpus_resolve_request_failed", course_id=course_id, error=str(exc))
        return None

    if resp.status_code == 404:
        logger.warning("corpus_not_defined", course_id=course_id)
        return None
    if resp.status_code != 200:
        logger.warning("corpus_resolve_bad_status", course_id=course_id, status=resp.status_code)
        return None

    try:
        corpus_id = resp.json().get("corpus_id")
    except Exception:
        return None

    if not corpus_id:
        return None
    logger.info("corpus_resolved", course_id=course_id, corpus_id=corpus_id)
    return corpus_id


def clear_cache() -> None:
    """Clear the resolver cache (tests only)."""
    with _lock:
        _cache.clear()
