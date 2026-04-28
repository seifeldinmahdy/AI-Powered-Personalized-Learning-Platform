"""
SharedSessionStore — centralised in-memory session state shared by all AI
subsystems (Tutor, Intent, Slides, Profiler, FER/SER).

Design decisions
────────────────
• In-memory dict for single-process deployments (default).
• threading.Lock for atomic writes — FastAPI runs on a single event-loop
  thread, but background tasks / sync endpoints may still race.
• If ``REDIS_URL`` is set in the environment a Redis-backed store can be
  swapped in with zero API changes (stubbed, not implemented yet).
• The store is a module-level singleton: import ``get_session_store()`` from
  anywhere in the ai_service package.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Default session schema ──────────────────────────────────────────

_DEFAULT_SESSION: Dict[str, Any] = {
    "session_id": "",
    "student_id": "",
    "current_slide_index": 0,
    "current_slide_title": "",
    "current_topic": "",
    "current_subtopic": "",
    "running_summary": "",
    "tutor_transcript": [],   # last 10 entries
    "fused_emotion": "",
    "confidence": 0.0,
    "pace_modifier": 0,
    "student_profile_summary": "",
}


class SharedSessionStore:
    """Thread-safe in-memory session store shared across AI subsystems.

    All writes are guarded by a ``threading.Lock`` so concurrent requests
    targeting the same ``session_id`` never produce torn reads/writes.

    Parameters
    ----------
    use_redis : bool
        If *True* **and** ``REDIS_URL`` is set, back the store with Redis
        instead of a plain dict.  Currently a stub — falls back to in-memory
        if Redis is unavailable.
    """

    _instance: Optional["SharedSessionStore"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "SharedSessionStore":
        """Enforce singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self, use_redis: bool = False) -> None:
        if self._initialised:  # type: ignore[has-type]
            return
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._use_redis = use_redis and bool(os.getenv("REDIS_URL"))

        if self._use_redis:
            try:
                import redis
                self._redis = redis.from_url(os.getenv("REDIS_URL", ""))
                logger.info("SharedSessionStore: Redis backend connected")
            except Exception as exc:
                logger.warning(
                    "SharedSessionStore: Redis requested but unavailable (%s). "
                    "Falling back to in-memory store.",
                    exc,
                )
                self._use_redis = False
                self._redis = None
        else:
            self._redis = None

        self._initialised = True
        logger.info(
            "SharedSessionStore initialised (backend=%s)",
            "redis" if self._use_redis else "memory",
        )

    # ── Public API ──────────────────────────────────────────────────

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return a *deep copy* of the session dict, or ``None`` if missing.

        Parameters
        ----------
        session_id : str
            The unique session identifier.

        Returns
        -------
        dict or None
            A deep copy of the stored session state, or ``None`` if no
            session with the given ID exists.
        """
        with self._lock:
            data = self._store.get(session_id)
            if data is None:
                return None
            return copy.deepcopy(data)

    def update_session(self, session_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Create or update a session.  Only the supplied keyword arguments
        are written; all other fields retain their previous (or default)
        values.

        Parameters
        ----------
        session_id : str
            The unique session identifier.
        **kwargs
            Arbitrary key-value pairs matching the session schema fields.

        Returns
        -------
        dict
            A deep copy of the session state *after* the update.
        """
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = {
                    **copy.deepcopy(_DEFAULT_SESSION),
                    "session_id": session_id,
                }
                logger.info("SharedSessionStore: created session %s", session_id)

            session = self._store[session_id]
            for key, value in kwargs.items():
                if key in _DEFAULT_SESSION:
                    session[key] = value
                else:
                    logger.warning(
                        "SharedSessionStore: ignoring unknown key '%s' for "
                        "session %s",
                        key,
                        session_id,
                    )

            return copy.deepcopy(session)

    def delete_session(self, session_id: str) -> bool:
        """Remove a session from the store.

        Parameters
        ----------
        session_id : str
            The unique session identifier.

        Returns
        -------
        bool
            ``True`` if the session existed and was deleted, ``False``
            otherwise.
        """
        with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                logger.info("SharedSessionStore: deleted session %s", session_id)
                return True
            return False

    def build_context_string(self, session_id: str) -> str:
        """Build a compact context string from the stored session fields.

        The format matches what the Intent model was trained on::

            topic:{topic} | prev:{prev} | ability:{ability} |
            emotion:{emotion} | pace:{pace} | slides:{s-1},{s},{s+1}

        Parameters
        ----------
        session_id : str
            The unique session identifier.

        Returns
        -------
        str
            A formatted context string, or an empty string if the session
            does not exist.
        """
        data = self.get_session(session_id)
        if data is None:
            return ""

        topic = data.get("current_topic", "") or "N/A"
        subtopic = data.get("current_subtopic", "") or ""
        emotion = data.get("fused_emotion", "") or "neutral"
        pace_mod = data.get("pace_modifier", 0)
        slide_idx = data.get("current_slide_index", 0)
        summary = data.get("student_profile_summary", "") or "N/A"

        pace_label = "normal"
        if pace_mod > 0:
            pace_label = "fast"
        elif pace_mod < 0:
            pace_label = "slow"

        prev = subtopic if subtopic else "None"

        context = (
            f"topic:{topic} | "
            f"prev:{prev} | "
            f"ability:{summary[:60]} | "
            f"emotion:{emotion} | "
            f"pace:{pace_label} | "
            f"slides:{max(slide_idx - 1, 0)},{slide_idx},{slide_idx + 1}"
        )
        return context


# ── Module-level singleton accessor ─────────────────────────────────

_store_instance: Optional[SharedSessionStore] = None


def get_session_store() -> SharedSessionStore:
    """Get or create the global SharedSessionStore singleton.

    Returns
    -------
    SharedSessionStore
        The singleton store instance.
    """
    global _store_instance
    if _store_instance is None:
        _store_instance = SharedSessionStore()
    return _store_instance
