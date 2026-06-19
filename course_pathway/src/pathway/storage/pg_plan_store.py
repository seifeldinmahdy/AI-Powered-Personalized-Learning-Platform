"""Supabase / Postgres backend for VERSIONED session-plan persistence.

Drop-in replacement for the SQLite :class:`~pathway.storage.plan_store.PlanStore`.
It exposes the EXACT same method surface and the same return types, so every
consumer (the pathway ``generator``, the FastAPI ``router``, the tester apps)
works unchanged. The active backend is chosen in ``plan_store.py`` from the
environment (see :func:`pathway.storage.plan_store._use_pg_plans`).

Why this exists
---------------
The SQLite ``PlanStore`` is a single on-disk file: each developer/server has its
own copy, so a plan generated on one machine is invisible to the others. Putting
the plans in the same Supabase Postgres that already hosts the corpus vectors
gives the whole team one shared, concurrently-accessible plan store.

Connection
----------
Reads the DSN from ``SUPABASE_DB_URL`` (or ``VECTOR_DB_URL``) — the SAME pooled
connection string used by the pgvector corpus store, so a single Supabase
project hosts both. One short-lived connection is opened per operation; the
Supabase pooler (port 6543) absorbs the churn.

Schema (see ``course_pathway/sql/pathway_setup.sql``) mirrors the SQLite tables
1:1, with ``is_current`` as a real ``boolean`` and the plan/proposal payloads
kept as ``text`` (the code stores ``SessionPlan.model_dump_json()`` verbatim and
reads it back with ``model_validate_json``, so no JSON re-encoding is involved).
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import structlog

from pathway.models.schemas import SessionPlan

logger = structlog.get_logger(__name__)

# Per-process "schema ensured" latch so we attempt the idempotent DDL only once.
_schema_ready: set[str] = set()
_schema_lock = threading.Lock()


def resolve_dsn() -> str:
    dsn = os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")
    if not dsn:
        raise RuntimeError(
            "PATHWAY_BACKEND is set to supabase/postgres but neither "
            "SUPABASE_DB_URL nor VECTOR_DB_URL is configured. Set it to your "
            "Supabase Postgres connection string (use the pooled URI, port 6543)."
        )
    return dsn


def _import_psycopg():
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # noqa: F401  (registers adapters)
        return psycopg2
    except Exception as exc:  # pragma: no cover - import-time guidance
        raise RuntimeError(
            "The Supabase plan store needs psycopg2. Install it with "
            "`pip install psycopg2-binary` in this service's environment."
        ) from exc


_DDL_PLANS = """
CREATE TABLE IF NOT EXISTS session_plans_v2 (
    student_id        TEXT    NOT NULL,
    course_id         TEXT    NOT NULL,
    plan_version      INTEGER NOT NULL,
    plan_json         TEXT    NOT NULL,
    context_hash      TEXT    NOT NULL,
    raw_proposal_hash TEXT    NOT NULL DEFAULT '',
    is_current        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TEXT    NOT NULL,
    PRIMARY KEY (student_id, course_id, plan_version)
);
"""

_DDL_PROPOSALS = """
CREATE TABLE IF NOT EXISTS curriculum_proposals (
    course_id      TEXT NOT NULL,
    corpus_id      TEXT NOT NULL,
    input_hash     TEXT NOT NULL,
    proposal_hash  TEXT NOT NULL,
    proposal_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (course_id, corpus_id)
);
"""


class PgPlanStore:
    """Persist and retrieve VERSIONED session plans in Supabase/Postgres."""

    def __init__(self, db_path: str | None = None) -> None:
        # db_path is irrelevant for a remote store; accepted for signature parity
        # with the SQLite PlanStore so call sites need no changes.
        self._psycopg2 = _import_psycopg()
        self._dsn = resolve_dsn()
        self._ensure_schema()
        logger.info("pg_plan_store_ready", backend="supabase")

    # ── Connection / schema ──────────────────────────────────────

    @contextmanager
    def _cursor(self, commit: bool = False):
        conn = self._psycopg2.connect(self._dsn)
        try:
            with conn.cursor() as cur:
                yield cur
            if commit:
                conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Best-effort idempotent schema creation (once per process)."""
        key = self._dsn
        with _schema_lock:
            if key in _schema_ready:
                return
            try:
                with self._cursor(commit=True) as cur:
                    cur.execute(_DDL_PLANS)
                    cur.execute(_DDL_PROPOSALS)
                _schema_ready.add(key)
            except Exception as exc:
                logger.warning(
                    "pg_plan_schema_ensure_failed",
                    error=str(exc),
                    hint="Run course_pathway/sql/pathway_setup.sql against your Supabase DB.",
                )

    # ── Writes ───────────────────────────────────────────────────

    def save_new_version(self, plan: SessionPlan) -> int:
        """Insert *plan* as a NEW current version; supersede the previous current.

        Returns the assigned ``plan_version``. The previous current row keeps its
        data but loses ``is_current`` (retained, retrievable by version). The
        whole sequence runs in one transaction so a concurrent reader never sees
        two current rows.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor(commit=True) as cur:
            cur.execute(
                "SELECT COALESCE(MAX(plan_version), 0) FROM session_plans_v2 "
                "WHERE student_id=%s AND course_id=%s",
                (plan.student_id, plan.course_id),
            )
            next_version = int(cur.fetchone()[0]) + 1

            plan.plan_version = next_version
            plan.is_current = True
            plan_json = plan.model_dump_json()

            cur.execute(
                "UPDATE session_plans_v2 SET is_current=FALSE "
                "WHERE student_id=%s AND course_id=%s",
                (plan.student_id, plan.course_id),
            )
            cur.execute(
                "INSERT INTO session_plans_v2 "
                "(student_id, course_id, plan_version, plan_json, context_hash, "
                " raw_proposal_hash, is_current, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)",
                (
                    plan.student_id, plan.course_id, next_version, plan_json,
                    plan.student_context_hash, plan.raw_proposal_hash, now,
                ),
            )

        logger.info(
            "plan_version_saved",
            student_id=plan.student_id, course_id=plan.course_id,
            plan_version=next_version, sessions=plan.total_sessions,
        )
        return next_version

    # Back-compat: legacy single-row ``save`` maps to a new version.
    def save(self, plan: SessionPlan) -> int:
        return self.save_new_version(plan)

    # ── Reads ────────────────────────────────────────────────────

    def load_current(self, student_id: str, course_id: str) -> SessionPlan | None:
        """Load the current plan version, or None."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT plan_json FROM session_plans_v2 "
                "WHERE student_id=%s AND course_id=%s AND is_current=TRUE",
                (student_id, course_id),
            )
            row = cur.fetchone()
        return SessionPlan.model_validate_json(row[0]) if row else None

    # Back-compat alias used by the session-chunks lookup.
    def load(self, student_id: str, course_id: str) -> SessionPlan | None:
        return self.load_current(student_id, course_id)

    def load_version(self, student_id: str, course_id: str, version: int) -> SessionPlan | None:
        """Load a specific (possibly superseded) version, or None."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT plan_json FROM session_plans_v2 "
                "WHERE student_id=%s AND course_id=%s AND plan_version=%s",
                (student_id, course_id, version),
            )
            row = cur.fetchone()
        return SessionPlan.model_validate_json(row[0]) if row else None

    def get_context_hash(self, student_id: str, course_id: str) -> str | None:
        """Return the CURRENT version's context hash, or None."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT context_hash FROM session_plans_v2 "
                "WHERE student_id=%s AND course_id=%s AND is_current=TRUE",
                (student_id, course_id),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def needs_regeneration(self, student_id: str, course_id: str, new_hash: str) -> bool:
        """True if no current plan exists or the context hash changed."""
        stored = self.get_context_hash(student_id, course_id)
        return stored is None or stored != new_hash

    def list_versions(self, student_id: str, course_id: str) -> list[dict]:
        """List all versions for a student+course (no full JSON)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT plan_version, context_hash, raw_proposal_hash, is_current, created_at "
                "FROM session_plans_v2 WHERE student_id=%s AND course_id=%s "
                "ORDER BY plan_version",
                (student_id, course_id),
            )
            rows = cur.fetchall()
        return [
            {
                "plan_version": r[0], "context_hash": r[1],
                "raw_proposal_hash": r[2], "is_current": bool(r[3]), "created_at": r[4],
            }
            for r in rows
        ]

    # ── Raw curriculum proposals (determinism via replay) ────────

    def load_proposal(self, course_id: str, corpus_id: str, input_hash: str) -> tuple[str, str] | None:
        """Return (proposal_json, proposal_hash) if a proposal exists for this
        course+corpus AND was produced from the same inputs (input_hash). A
        topics change (re-index) invalidates the replay and forces a re-propose.
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT proposal_json, proposal_hash FROM curriculum_proposals "
                "WHERE course_id=%s AND corpus_id=%s AND input_hash=%s",
                (course_id, corpus_id, input_hash),
            )
            row = cur.fetchone()
        return (row[0], row[1]) if row else None

    def save_proposal(self, course_id: str, corpus_id: str, input_hash: str,
                      proposal_json: str, proposal_hash: str) -> None:
        """Persist the raw LLM proposal so future generations replay it."""
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO curriculum_proposals "
                "(course_id, corpus_id, input_hash, proposal_hash, proposal_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (course_id, corpus_id) DO UPDATE SET "
                "    input_hash    = EXCLUDED.input_hash, "
                "    proposal_hash = EXCLUDED.proposal_hash, "
                "    proposal_json = EXCLUDED.proposal_json, "
                "    created_at    = EXCLUDED.created_at",
                (course_id, corpus_id, input_hash, proposal_hash, proposal_json, now),
            )

    # ── Verbatim upserts (used by the SQLite→Supabase migration) ─

    def upsert_plan_rows(self, rows: list[tuple]) -> None:
        """Copy ``session_plans_v2`` rows verbatim (preserving version/flags).

        Each tuple is
        ``(student_id, course_id, plan_version, plan_json, context_hash,
        raw_proposal_hash, is_current, created_at)``. Idempotent by primary key.
        """
        if not rows:
            return
        sql = (
            "INSERT INTO session_plans_v2 "
            "(student_id, course_id, plan_version, plan_json, context_hash, "
            " raw_proposal_hash, is_current, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (student_id, course_id, plan_version) DO UPDATE SET "
            "    plan_json         = EXCLUDED.plan_json, "
            "    context_hash      = EXCLUDED.context_hash, "
            "    raw_proposal_hash = EXCLUDED.raw_proposal_hash, "
            "    is_current        = EXCLUDED.is_current, "
            "    created_at        = EXCLUDED.created_at"
        )
        with self._cursor(commit=True) as cur:
            cur.executemany(sql, rows)
        logger.info("pg_plan_rows_upserted", count=len(rows))

    def upsert_proposal_rows(self, rows: list[tuple]) -> None:
        """Copy ``curriculum_proposals`` rows verbatim. Idempotent by PK.

        Each tuple is ``(course_id, corpus_id, input_hash, proposal_hash,
        proposal_json, created_at)``.
        """
        if not rows:
            return
        sql = (
            "INSERT INTO curriculum_proposals "
            "(course_id, corpus_id, input_hash, proposal_hash, proposal_json, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (course_id, corpus_id) DO UPDATE SET "
            "    input_hash    = EXCLUDED.input_hash, "
            "    proposal_hash = EXCLUDED.proposal_hash, "
            "    proposal_json = EXCLUDED.proposal_json, "
            "    created_at    = EXCLUDED.created_at"
        )
        with self._cursor(commit=True) as cur:
            cur.executemany(sql, rows)
        logger.info("pg_proposal_rows_upserted", count=len(rows))

    def list_plans(self, student_id: str) -> list[dict]:
        """List current plans across courses for a student (used by router)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT course_id, context_hash, created_at, plan_version "
                "FROM session_plans_v2 WHERE student_id=%s AND is_current=TRUE",
                (student_id,),
            )
            rows = cur.fetchall()
        return [
            {"course_id": r[0], "context_hash": r[1], "created_at": r[2], "plan_version": r[3]}
            for r in rows
        ]
