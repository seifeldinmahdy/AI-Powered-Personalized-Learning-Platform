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
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from schemas.student_context import UnifiedStudentContext, StudentProfileState, LiveSessionState

logger = logging.getLogger(__name__)


class SharedSessionStore:
    """Thread-safe session store shared across AI subsystems.

    All writes are guarded by a ``threading.Lock`` so concurrent requests
    targeting the same ``session_id`` never produce torn reads/writes.

    Parameters
    ----------
    use_redis : bool
        If *True* **and** ``REDIS_URL`` is set, back the store with Redis
        instead of a plain dict.
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
        self._store: Dict[str, UnifiedStudentContext] = {}
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

    def create_session(
        self,
        session_id: str,
        profile: StudentProfileState,
        live: Optional[LiveSessionState] = None,
        ttl_seconds: int = 86400,
    ) -> UnifiedStudentContext:
        """Create a new session in the store.

        Parameters
        ----------
        session_id : str
            The unique session identifier.
        profile : StudentProfileState
            The student's global profile state.
        live : LiveSessionState, optional
            The initial live session state. Defaults to empty.
        ttl_seconds : int
            Time-to-live for the session in seconds (if using Redis).
        """
        if live is None:
            live = LiveSessionState(session_id=session_id)
        else:
            live.session_id = session_id
            
        context = UnifiedStudentContext(profile=profile, live=live)

        with self._lock:
            if self._use_redis:
                prof_key = f"session:{session_id}:profile"
                live_key = f"session:{session_id}:live"
                self._redis.set(prof_key, context.profile.model_dump_json(), ex=ttl_seconds)
                self._redis.set(live_key, context.live.model_dump_json(), ex=ttl_seconds)
            else:
                self._store[session_id] = copy.deepcopy(context)
                
            logger.info("SharedSessionStore: created session %s", session_id)
            return context

    def get_session(self, session_id: str) -> Optional[UnifiedStudentContext]:
        """Return the session context, or ``None`` if missing.

        Parameters
        ----------
        session_id : str
            The unique session identifier.

        Returns
        -------
        UnifiedStudentContext or None
            A copy of the stored session state.
        """
        with self._lock:
            if self._use_redis:
                prof_key = f"session:{session_id}:profile"
                live_key = f"session:{session_id}:live"
                
                prof_data = self._redis.get(prof_key)
                live_data = self._redis.get(live_key)
                
                if prof_data is None or live_data is None:
                    return None
                    
                profile = StudentProfileState.model_validate_json(prof_data)
                live = LiveSessionState.model_validate_json(live_data)
                return UnifiedStudentContext(profile=profile, live=live)
            else:
                data = self._store.get(session_id)
                if data is None:
                    return None
                return copy.deepcopy(data)

    def update_session(
        self,
        session_id: str,
        live_kwargs: Optional[Dict[str, Any]] = None,
        profile_kwargs: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = 86400,
    ) -> UnifiedStudentContext:
        """Update a session's profile or live state.

        Parameters
        ----------
        session_id : str
            The unique session identifier.
        live_kwargs : dict, optional
            Fields to update in LiveSessionState.
        profile_kwargs : dict, optional
            Fields to update in StudentProfileState.
        ttl_seconds : int
            Time-to-live for the session in seconds (if using Redis).

        Returns
        -------
        UnifiedStudentContext
            The updated session context.
            
        Raises
        ------
        KeyError
            If the session does not exist.
        ValidationError
            If the provided kwargs violate Pydantic schema validation.
        """
        with self._lock:
            context = None
            if self._use_redis:
                prof_key = f"session:{session_id}:profile"
                live_key = f"session:{session_id}:live"
                prof_data = self._redis.get(prof_key)
                live_data = self._redis.get(live_key)
                if prof_data is None or live_data is None:
                    raise KeyError(f"Session {session_id} not found.")
                context = UnifiedStudentContext(
                    profile=StudentProfileState.model_validate_json(prof_data),
                    live=LiveSessionState.model_validate_json(live_data),
                )
            else:
                if session_id not in self._store:
                    raise KeyError(f"Session {session_id} not found.")
                context = copy.deepcopy(self._store[session_id])

            if live_kwargs:
                live_kwargs["last_updated_at"] = time.time()
                updated_live = context.live.model_copy(update=live_kwargs)
                context.live = LiveSessionState.model_validate(updated_live.model_dump())

            if profile_kwargs:
                updated_profile = context.profile.model_copy(update=profile_kwargs)
                context.profile = StudentProfileState.model_validate(updated_profile.model_dump())

            if self._use_redis:
                prof_key = f"session:{session_id}:profile"
                live_key = f"session:{session_id}:live"
                self._redis.set(prof_key, context.profile.model_dump_json(), ex=ttl_seconds)
                self._redis.set(live_key, context.live.model_dump_json(), ex=ttl_seconds)
            else:
                self._store[session_id] = copy.deepcopy(context)

            return copy.deepcopy(context)

    def delete_session(self, session_id: str) -> bool:
        """Remove a session from the store.

        Parameters
        ----------
        session_id : str
            The unique session identifier.

        Returns
        -------
        bool
            ``True`` if the session existed and was deleted.
        """
        with self._lock:
            if self._use_redis:
                prof_key = f"session:{session_id}:profile"
                live_key = f"session:{session_id}:live"
                count = self._redis.delete(prof_key, live_key)
                return count > 0
            else:
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

        topic = data.live.current_topic or "N/A"
        subtopic = data.live.current_subtopic or ""
        emotion = data.live.fused_emotion or "neutral"
        pace_mod = data.live.pace_modifier
        slide_idx = data.live.current_slide_index
        summary = data.profile.student_profile_summary or "N/A"

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
