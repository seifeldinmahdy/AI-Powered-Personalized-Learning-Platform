"""Supabase / Postgres backend for the durable session-event log.

Drop-in replacement for the SQLite :class:`~services.session_event_log.SessionEventLog`.
It exposes the EXACT same method surface and the same return shapes, and — for
this step — the EXACT same retention behavior (emotion-only purges, consume
marking). The broader purge-on-consolidation + TTL for ALL consumed events is a
SEPARATE, later step; this file deliberately does not add it.

The active backend is chosen in ``session_event_log.py`` from the environment
(``SESSION_EVENTS_BACKEND=supabase``). Reuses the SUPABASE_DB_URL of the other
shared stores. One short-lived connection per operation (pooler absorbs churn).

``created_at`` is a real ``timestamptz``; the TTL/age queries accept the same ISO
strings the SQLite store used, cast server-side.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import structlog

from services.pg_common import import_psycopg, pg_cursor, resolve_dsn

logger = structlog.get_logger(__name__)

_schema_ready: set[str] = set()
_schema_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS session_events (
    id          BIGSERIAL   PRIMARY KEY,
    session_id  TEXT        NOT NULL,
    student_id  TEXT        NOT NULL DEFAULT '',
    course_id   TEXT        NOT NULL DEFAULT '',
    event_type  TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    consumed    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DDL_INDEX = """
CREATE INDEX IF NOT EXISTS idx_session_events_sid
    ON session_events (session_id, consumed, id);
"""


class PgSessionEventLog:
    """pgvector-project Postgres implementation of the durable event log."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        import_psycopg()
        self._dsn = resolve_dsn()
        self._ensure_schema()
        logger.info("pg_session_event_log_ready", backend="supabase")
        # One-time cleanup of the UNATTRIBUTABLE emotion backlog (parity with the
        # SQLite store): emotion rows with an empty student_id can't honour a
        # consent withdrawal, so we don't keep that biometric record.
        self._purge_unattributable_emotion()

    def _ensure_schema(self) -> None:
        key = self._dsn
        with _schema_lock:
            if key in _schema_ready:
                return
            try:
                with pg_cursor(self._dsn, commit=True) as cur:
                    cur.execute(_DDL)
                    cur.execute(_DDL_INDEX)
                _schema_ready.add(key)
            except Exception as exc:
                logger.warning(
                    "pg_session_event_schema_ensure_failed",
                    error=str(exc),
                    hint="Run ai_service/sql/ai_stores_setup.sql against your Supabase DB.",
                )

    def _purge_unattributable_emotion(self) -> int:
        try:
            with pg_cursor(self._dsn, commit=True) as cur:
                cur.execute(
                    "DELETE FROM session_events WHERE event_type='emotion' "
                    "AND (student_id IS NULL OR student_id='')"
                )
                n = cur.rowcount or 0
            if n:
                logger.info("emotion_backlog_purged", unattributable_rows=n)
            return n
        except Exception as exc:
            logger.warning("emotion_backlog_purge_failed", error=str(exc))
            return 0

    # ── Append ───────────────────────────────────────────────────

    def append(self, session_id: str, event_type: str, payload: dict,
               student_id: str = "", course_id: str = "") -> None:
        if not session_id:
            return
        try:
            with pg_cursor(self._dsn, commit=True) as cur:
                cur.execute(
                    "INSERT INTO session_events "
                    "(session_id, student_id, course_id, event_type, payload, created_at) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                    (session_id, str(student_id), str(course_id), event_type,
                     json.dumps(payload, ensure_ascii=False),
                     datetime.now(timezone.utc)),
                )
        except Exception as exc:  # never let logging break the live session
            logger.warning("session_event_append_failed", session_id=session_id, error=str(exc))

    # ── Consume cycle (idempotent consolidation) ─────────────────

    def read_unconsumed(self, session_id: str) -> list[dict]:
        """Return this session's unconsumed events, oldest first."""
        with pg_cursor(self._dsn) as cur:
            cur.execute(
                "SELECT id, student_id, course_id, event_type, payload, created_at "
                "FROM session_events WHERE session_id=%s AND consumed=FALSE ORDER BY id",
                (session_id,),
            )
            rows = cur.fetchall()
        out = []
        for _id, sid, cid, etype, payload, created in rows:
            out.append({
                "id": _id, "student_id": sid, "course_id": cid,
                "event_type": etype,
                "payload": payload if isinstance(payload, dict) else {},
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
            })
        return out

    def mark_consumed(self, session_id: str, up_to_id: int) -> None:
        """Mark this session's events (id ≤ up_to_id) consumed — the idempotency
        marker. A re-run then reads nothing → no double-apply."""
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "UPDATE session_events SET consumed=TRUE "
                "WHERE session_id=%s AND id<=%s AND consumed=FALSE",
                (session_id, up_to_id),
            )

    # ── Emotion retention (parity with SQLite store; emotion-only) ──

    def purge_consumed_emotion(self, session_id: str) -> int:
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "DELETE FROM session_events "
                "WHERE session_id=%s AND event_type='emotion' AND consumed=TRUE",
                (session_id,),
            )
            return cur.rowcount or 0

    def purge_emotion_older_than(self, older_than_iso: str) -> int:
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "DELETE FROM session_events "
                "WHERE event_type='emotion' AND consumed=TRUE AND created_at < %s::timestamptz",
                (older_than_iso,),
            )
            return cur.rowcount or 0

    def purge_student_emotion(self, student_id: str) -> int:
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "DELETE FROM session_events WHERE event_type='emotion' AND student_id=%s",
                (str(student_id),),
            )
            return cur.rowcount or 0

    # ── Step 2: purge ALL consumed events (not just emotion) ─────────

    def purge_consumed_session(self, session_id: str) -> int:
        """Delete ALL of a session's CONSUMED events (any type) — after the
        derived profile is confirmed in Django."""
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "DELETE FROM session_events WHERE session_id=%s AND consumed=TRUE",
                (session_id,),
            )
            return cur.rowcount or 0

    def purge_consumed_older_than(self, older_than_iso: str) -> int:
        """TTL backstop for ALL consumed events (any type) older than the cutoff."""
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "DELETE FROM session_events WHERE consumed=TRUE AND created_at < %s::timestamptz",
                (older_than_iso,),
            )
            return cur.rowcount or 0

    def sessions_with_unconsumed(self, older_than_iso: str | None = None) -> list[str]:
        q = "SELECT DISTINCT session_id FROM session_events WHERE consumed=FALSE"
        params: tuple = ()
        if older_than_iso:
            q += " AND created_at < %s::timestamptz"
            params = (older_than_iso,)
        with pg_cursor(self._dsn) as cur:
            cur.execute(q, params)
            return [r[0] for r in cur.fetchall()]

    # ── Verbatim batch insert used by the SQLite→Supabase migration ──

    def insert_raw_batch(self, rows: list[tuple]) -> None:
        """Copy rows verbatim (preserving consumed flag + created_at).

        Each tuple is ``(session_id, student_id, course_id, event_type,
        payload_json_str, consumed_bool, created_at_iso)``.
        """
        if not rows:
            return
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.executemany(
                "INSERT INTO session_events "
                "(session_id, student_id, course_id, event_type, payload, consumed, created_at) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::timestamptz)",
                rows,
            )
        logger.info("pg_session_events_inserted", count=len(rows))
