"""SQLite-backed, VERSIONED persistence for generated session plans.

A plan is never overwritten in place. Each generation that changes the input
context produces a NEW ``plan_version`` row; the latest is flagged
``is_current=1`` and prior versions are retained (superseded) so artifacts born
under an old version still resolve by version.

One authoritative copy lives here (the server-side store). Determinism: a new
version only appears when the context hash (or the LLM raw-proposal hash)
changes — identical input returns the existing current plan unchanged.

The database is auto-created and lazily migrated on first use.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import structlog

from pathway.models.schemas import SessionPlan

logger = structlog.get_logger(__name__)


def _use_pg_plans() -> bool:
    """Whether the shared Supabase/Postgres plan backend is selected.

    Resolution (explicit opt-in — moving per-student plans is consequential, so
    unlike the vector store we do NOT auto-switch merely because a DSN exists):
      - ``PATHWAY_BACKEND=supabase`` / ``postgres`` / ``pg`` → True.
      - anything else (incl. unset, ``sqlite``, ``local``)   → False.

    The DSN itself is shared with the corpus vector store (``SUPABASE_DB_URL`` /
    ``VECTOR_DB_URL``), so one Supabase project hosts both.
    """
    backend = os.getenv("PATHWAY_BACKEND", "").strip().lower()
    return backend in ("supabase", "postgres", "pg", "pgvector")

_DDL = """
CREATE TABLE IF NOT EXISTS session_plans_v2 (
    student_id        TEXT    NOT NULL,
    course_id         TEXT    NOT NULL,
    plan_version      INTEGER NOT NULL,
    plan_json         TEXT    NOT NULL,
    context_hash      TEXT    NOT NULL,
    raw_proposal_hash TEXT    NOT NULL DEFAULT '',
    is_current        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL,
    PRIMARY KEY (student_id, course_id, plan_version)
);
"""

# Raw LLM curriculum proposals, keyed by the corpus signature they were produced
# from. The plan is RE-RESOLVED deterministically from the stored proposal, so a
# regeneration never depends on the LLM provider being bit-reproducible — the
# proposal is captured once and replayed.
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


class PlanStore:
    """Persist and retrieve VERSIONED session plans in SQLite.

    Backed by a local SQLite file by default, or by the shared Supabase/Postgres
    store when configured (see :func:`_use_pg_plans`). Both backends expose the
    identical method surface; the Postgres backend is returned transparently from
    ``__new__`` so every caller is unchanged and SQLite stays the default/fallback
    (fully reversible via env).
    """

    def __new__(cls, db_path: str | None = None):
        # Transparently swap in the shared Supabase plan store when configured.
        if cls is PlanStore and _use_pg_plans():
            from pathway.storage.pg_plan_store import PgPlanStore
            return PgPlanStore(db_path=db_path)
        return super().__new__(cls)

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("plan_store_ready", path=db_path)

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_DDL)
            conn.execute(_DDL_PROPOSALS)
            conn.commit()
            self._migrate_legacy(conn)

    def _migrate_legacy(self, conn: sqlite3.Connection) -> None:
        """Copy rows from the legacy single-row table into the versioned one.

        The legacy ``session_plans`` table keyed (student_id, course_id) becomes
        version 1 / is_current=1. Idempotent: only runs when v2 has no row for a
        given (student, course).
        """
        legacy = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_plans'"
        ).fetchone()
        if not legacy:
            return
        rows = conn.execute(
            "SELECT student_id, course_id, plan_json, context_hash, created_at FROM session_plans"
        ).fetchall()
        migrated = 0
        for student_id, course_id, plan_json, context_hash, created_at in rows:
            exists = conn.execute(
                "SELECT 1 FROM session_plans_v2 WHERE student_id=? AND course_id=? LIMIT 1",
                (student_id, course_id),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO session_plans_v2
                   (student_id, course_id, plan_version, plan_json, context_hash,
                    raw_proposal_hash, is_current, created_at)
                   VALUES (?, ?, 1, ?, ?, '', 1, ?)""",
                (student_id, course_id, plan_json, context_hash, created_at),
            )
            migrated += 1
        if migrated:
            conn.commit()
            logger.info("plan_store_legacy_migrated", rows=migrated)

    # ── Writes ───────────────────────────────────────────────────

    def save_new_version(self, plan: SessionPlan) -> int:
        """Insert *plan* as a NEW current version; supersede the previous current.

        Returns the assigned ``plan_version``. The previous current row keeps its
        data but loses ``is_current`` (retained, retrievable by version).
        """
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(plan_version), 0) FROM session_plans_v2 "
                "WHERE student_id=? AND course_id=?",
                (plan.student_id, plan.course_id),
            ).fetchone()
            next_version = int(row[0]) + 1

            plan.plan_version = next_version
            plan.is_current = True
            plan_json = plan.model_dump_json()

            conn.execute(
                "UPDATE session_plans_v2 SET is_current=0 "
                "WHERE student_id=? AND course_id=?",
                (plan.student_id, plan.course_id),
            )
            conn.execute(
                """INSERT INTO session_plans_v2
                   (student_id, course_id, plan_version, plan_json, context_hash,
                    raw_proposal_hash, is_current, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    plan.student_id, plan.course_id, next_version, plan_json,
                    plan.student_context_hash, plan.raw_proposal_hash, now,
                ),
            )
            conn.commit()

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
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT plan_json FROM session_plans_v2 "
                "WHERE student_id=? AND course_id=? AND is_current=1",
                (student_id, course_id),
            ).fetchone()
        return SessionPlan.model_validate_json(row[0]) if row else None

    # Back-compat alias used by the session-chunks lookup.
    def load(self, student_id: str, course_id: str) -> SessionPlan | None:
        return self.load_current(student_id, course_id)

    def load_version(self, student_id: str, course_id: str, version: int) -> SessionPlan | None:
        """Load a specific (possibly superseded) version, or None."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT plan_json FROM session_plans_v2 "
                "WHERE student_id=? AND course_id=? AND plan_version=?",
                (student_id, course_id, version),
            ).fetchone()
        return SessionPlan.model_validate_json(row[0]) if row else None

    def get_context_hash(self, student_id: str, course_id: str) -> str | None:
        """Return the CURRENT version's context hash, or None."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT context_hash FROM session_plans_v2 "
                "WHERE student_id=? AND course_id=? AND is_current=1",
                (student_id, course_id),
            ).fetchone()
        return row[0] if row else None

    def needs_regeneration(self, student_id: str, course_id: str, new_hash: str) -> bool:
        """True if no current plan exists or the context hash changed."""
        stored = self.get_context_hash(student_id, course_id)
        return stored is None or stored != new_hash

    def list_versions(self, student_id: str, course_id: str) -> list[dict]:
        """List all versions for a student+course (no full JSON)."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT plan_version, context_hash, raw_proposal_hash, is_current, created_at "
                "FROM session_plans_v2 WHERE student_id=? AND course_id=? "
                "ORDER BY plan_version",
                (student_id, course_id),
            ).fetchall()
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
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT proposal_json, proposal_hash FROM curriculum_proposals "
                "WHERE course_id=? AND corpus_id=? AND input_hash=?",
                (course_id, corpus_id, input_hash),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def save_proposal(self, course_id: str, corpus_id: str, input_hash: str,
                      proposal_json: str, proposal_hash: str) -> None:
        """Persist the raw LLM proposal so future generations replay it."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO curriculum_proposals
                   (course_id, corpus_id, input_hash, proposal_hash, proposal_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (course_id, corpus_id) DO UPDATE SET
                       input_hash    = excluded.input_hash,
                       proposal_hash = excluded.proposal_hash,
                       proposal_json = excluded.proposal_json,
                       created_at    = excluded.created_at""",
                (course_id, corpus_id, input_hash, proposal_hash, proposal_json, now),
            )
            conn.commit()

    def list_plans(self, student_id: str) -> list[dict]:
        """List current plans across courses for a student (used by router)."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT course_id, context_hash, created_at, plan_version "
                "FROM session_plans_v2 WHERE student_id=? AND is_current=1",
                (student_id,),
            ).fetchall()
        return [
            {"course_id": r[0], "context_hash": r[1], "created_at": r[2], "plan_version": r[3]}
            for r in rows
        ]
