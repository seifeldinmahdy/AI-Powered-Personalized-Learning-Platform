"""SQLite-backed persistence for generated session plans.

Stores one ``SessionPlan`` per (student_id, course_id) pair with
change-detection via the context hash.  Atomic writes ensure no
corruption under concurrent requests.

The database is auto-created on first use.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import structlog

from pathway.models.schemas import SessionPlan

logger = structlog.get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS session_plans (
    student_id  TEXT    NOT NULL,
    course_id   TEXT    NOT NULL,
    plan_json   TEXT    NOT NULL,
    context_hash TEXT   NOT NULL,
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (student_id, course_id)
);
"""


class PlanStore:
    """Persist and retrieve session plans in SQLite.

    Parameters
    ----------
    db_path:
        Absolute path to the SQLite database file.
        Parent directories are created automatically.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("plan_store_ready", path=db_path)

    def _init_db(self) -> None:
        """Create the table if it doesn't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_DDL)
            conn.commit()

    def save(self, plan: SessionPlan) -> None:
        """Upsert a session plan (insert or replace)."""
        plan_json = plan.model_dump_json()
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO session_plans
                    (student_id, course_id, plan_json, context_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (student_id, course_id) DO UPDATE SET
                    plan_json    = excluded.plan_json,
                    context_hash = excluded.context_hash,
                    created_at   = excluded.created_at
                """,
                (
                    plan.student_id,
                    plan.course_id,
                    plan_json,
                    plan.student_context_hash,
                    now,
                ),
            )
            conn.commit()

        logger.info(
            "plan_saved",
            student_id=plan.student_id,
            course_id=plan.course_id,
            sessions=plan.total_sessions,
        )

    def load(self, student_id: str, course_id: str) -> SessionPlan | None:
        """Load a saved plan, or return None if not found."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT plan_json FROM session_plans WHERE student_id = ? AND course_id = ?",
                (student_id, course_id),
            ).fetchone()

        if row is None:
            return None

        return SessionPlan.model_validate_json(row[0])

    def get_context_hash(self, student_id: str, course_id: str) -> str | None:
        """Return the stored context hash, or None if no plan exists."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT context_hash FROM session_plans WHERE student_id = ? AND course_id = ?",
                (student_id, course_id),
            ).fetchone()

        return row[0] if row else None

    def needs_regeneration(
        self, student_id: str, course_id: str, new_hash: str
    ) -> bool:
        """Return True if no plan exists or the context hash has changed."""
        stored_hash = self.get_context_hash(student_id, course_id)
        if stored_hash is None:
            return True
        return stored_hash != new_hash

    def delete(self, student_id: str, course_id: str) -> bool:
        """Delete a stored plan. Returns True if a row was deleted."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM session_plans WHERE student_id = ? AND course_id = ?",
                (student_id, course_id),
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(
                "plan_deleted", student_id=student_id, course_id=course_id
            )
        return deleted

    def list_plans(self, student_id: str) -> list[dict[str, str]]:
        """List all plans for a student (summary only, no full JSON)."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT course_id, context_hash, created_at FROM session_plans WHERE student_id = ?",
                (student_id,),
            ).fetchall()

        return [
            {"course_id": r[0], "context_hash": r[1], "created_at": r[2]}
            for r in rows
        ]
