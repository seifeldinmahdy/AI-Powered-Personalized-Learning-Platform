"""Supabase / Postgres backend for ``UnifiedStudentContext`` persistence.

Drop-in replacement for the file-backed
:class:`~services.student_context_store.StudentContextStore`. Same method surface
(``save`` / ``load`` / ``exists``) and same return types, so every caller
(``get_student_context_store()`` consumers) works unchanged.

The student context is generated ONCE per (student, course) and thereafter only
read — so this is a plain upsert-by-primary-key with no summarization and no
bloat (one bounded row per student+course).

Isolation note: this store NEVER trusts a caller-supplied identity. Reads/writes
are keyed by ``(student_id, course_id)`` exactly as passed; the API layer is
responsible for ensuring that ``student_id`` came from the authenticated session
and not from the request body.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

import structlog

from schemas.student_context import UnifiedStudentContext
from services.pg_common import import_psycopg, pg_cursor, resolve_dsn

logger = structlog.get_logger(__name__)

_schema_ready: set[str] = set()
_schema_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS student_contexts (
    student_id   TEXT        NOT NULL,
    course_id    TEXT        NOT NULL,
    context_json TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, course_id)
);
"""


class PgStudentContextStore:
    """Postgres-backed persistence for student context, keyed by student+course."""

    def __init__(self, data_dir=None) -> None:
        # data_dir is irrelevant for a remote store; accepted for signature parity
        # with the file-backed StudentContextStore so the factory needs no changes.
        import_psycopg()
        self._dsn = resolve_dsn()
        self._ensure_schema()
        logger.info("pg_student_context_store_ready", backend="supabase")

    def _ensure_schema(self) -> None:
        key = self._dsn
        with _schema_lock:
            if key in _schema_ready:
                return
            try:
                with pg_cursor(self._dsn, commit=True) as cur:
                    cur.execute(_DDL)
                _schema_ready.add(key)
            except Exception as exc:
                logger.warning(
                    "pg_student_context_schema_ensure_failed",
                    error=str(exc),
                    hint="Run ai_service/sql/ai_stores_setup.sql against your Supabase DB.",
                )

    def save(self, student_id: str, course_id: str,
             context: UnifiedStudentContext) -> None:
        """Upsert a UnifiedStudentContext by (student_id, course_id)."""
        now = datetime.now(timezone.utc)
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "INSERT INTO student_contexts (student_id, course_id, context_json, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (student_id, course_id) DO UPDATE SET "
                "    context_json = EXCLUDED.context_json, "
                "    updated_at   = EXCLUDED.updated_at",
                (str(student_id), str(course_id), context.model_dump_json(), now, now),
            )
        logger.info("student_context_saved", student_id=student_id, course_id=course_id)

    def load(self, student_id: str, course_id: str) -> Optional[UnifiedStudentContext]:
        """Load a persisted context, or return None if not found."""
        try:
            with pg_cursor(self._dsn) as cur:
                cur.execute(
                    "SELECT context_json FROM student_contexts "
                    "WHERE student_id=%s AND course_id=%s",
                    (str(student_id), str(course_id)),
                )
                row = cur.fetchone()
        except Exception as exc:
            logger.error("student_context_load_failed", student_id=student_id,
                         course_id=course_id, error=str(exc))
            return None
        if not row:
            return None
        try:
            return UnifiedStudentContext.model_validate_json(row[0])
        except Exception as exc:
            logger.error("student_context_parse_failed", student_id=student_id,
                         course_id=course_id, error=str(exc))
            return None

    def exists(self, student_id: str, course_id: str) -> bool:
        """Check whether a persisted context exists."""
        try:
            with pg_cursor(self._dsn) as cur:
                cur.execute(
                    "SELECT 1 FROM student_contexts WHERE student_id=%s AND course_id=%s",
                    (str(student_id), str(course_id)),
                )
                return cur.fetchone() is not None
        except Exception as exc:
            logger.error("student_context_exists_failed", student_id=student_id,
                         course_id=course_id, error=str(exc))
            return False

    # ── Verbatim upsert used by the file→Supabase migration ──────────

    def upsert_raw(self, student_id: str, course_id: str, context_json: str) -> None:
        """Upsert a raw context JSON string verbatim (migration path)."""
        now = datetime.now(timezone.utc)
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "INSERT INTO student_contexts (student_id, course_id, context_json, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (student_id, course_id) DO UPDATE SET "
                "    context_json = EXCLUDED.context_json, "
                "    updated_at   = EXCLUDED.updated_at",
                (str(student_id), str(course_id), context_json, now, now),
            )
