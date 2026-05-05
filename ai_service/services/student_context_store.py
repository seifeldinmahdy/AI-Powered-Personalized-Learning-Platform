"""
Student Context Store — JSON-file persistence for UnifiedStudentContext.

Stores student context keyed by ``{student_id}_{course_id}.json`` under
``ai_service/data/student_contexts/``.  Provides durable persistence across
server restarts without requiring a database dependency.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from schemas.student_context import (
    UnifiedStudentContext,
    StudentProfileState,
    LiveSessionState,
)

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "student_contexts"


class StudentContextStore:
    """File-backed persistence for student context, keyed by student+course."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = data_dir or _DATA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("StudentContextStore initialised (dir=%s)", self._dir)

    def _key_path(self, student_id: str, course_id: str) -> Path:
        safe_key = f"{student_id}_{course_id}".replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe_key}.json"

    def save(
        self,
        student_id: str,
        course_id: str,
        context: UnifiedStudentContext,
    ) -> None:
        """Persist a UnifiedStudentContext to disk."""
        path = self._key_path(student_id, course_id)
        path.write_text(context.model_dump_json(indent=2), encoding="utf-8")
        logger.info("student_context_saved student=%s course=%s path=%s", student_id, course_id, path)

    def load(
        self,
        student_id: str,
        course_id: str,
    ) -> Optional[UnifiedStudentContext]:
        """Load a persisted context, or return None if not found."""
        path = self._key_path(student_id, course_id)
        if not path.exists():
            logger.debug(
                "student_context_not_found",
                student_id=student_id,
                course_id=course_id,
            )
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return UnifiedStudentContext.model_validate(data)
        except Exception as exc:
            logger.error(
                "student_context_load_failed",
                student_id=student_id,
                course_id=course_id,
                error=str(exc),
            )
            return None

    def exists(self, student_id: str, course_id: str) -> bool:
        """Check whether a persisted context exists."""
        return self._key_path(student_id, course_id).exists()


# ── Module-level singleton ───────────────────────────────────────

_store: StudentContextStore | None = None


def get_student_context_store() -> StudentContextStore:
    """Get or create the global StudentContextStore singleton."""
    global _store
    if _store is None:
        _store = StudentContextStore()
    return _store
