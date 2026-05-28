"""
Local file persistence for generated coding labs.

Labs are keyed by student/course/lesson and stored as JSON under
``ai_service/data/coding_labs``. This mirrors the lightweight persistence
approach used by student_context_store without involving Django.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from schemas.coding import CodingLabGenerateResponse

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "coding_labs"


class CodingLabStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = data_dir or _DATA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("CodingLabStore initialised (dir=%s)", self._dir)

    def lab_id(self, student_id: str, course_id: str, lesson_id: str) -> str:
        raw = f"{student_id or 'anonymous'}_{course_id}_{lesson_id}"
        return raw.replace("/", "_").replace("\\", "_").replace(":", "_")

    def _path(self, lab_id: str) -> Path:
        safe = lab_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self._dir / f"{safe}.json"

    def save(self, response: CodingLabGenerateResponse) -> None:
        path = self._path(response.lab_id)
        path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        logger.info("coding_lab_saved lab_id=%s path=%s", response.lab_id, path)

    def _load_raw(self, lab_id: str) -> dict | None:
        """Load raw JSON dict from disk (no model validation)."""
        path = self._path(lab_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("coding_lab_load_raw_failed lab_id=%s error=%s", lab_id, exc)
            return None

    def _save_raw(self, lab_id: str, data: dict) -> None:
        """Save raw JSON dict to disk."""
        path = self._path(lab_id)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self, lab_id: str) -> Optional[CodingLabGenerateResponse]:
        path = self._path(lab_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return CodingLabGenerateResponse.model_validate(data)
        except Exception as exc:
            logger.error("coding_lab_load_failed lab_id=%s error=%s", lab_id, exc)
            return None

    # ── Notes & questions ────────────────────────────────────────

    def save_cell_note(
        self,
        lab_id: str,
        cell_id: str,
        content: str,
        timestamp: str,
    ) -> None:
        """Append a note to a specific cell's student_notes list and save."""
        data = self._load_raw(lab_id)
        if data is None:
            logger.warning("save_cell_note: lab not found lab_id=%s", lab_id)
            return
        for cell in data.get("lab", {}).get("cells", []):
            if cell.get("id") == cell_id:
                if "student_notes" not in cell:
                    cell["student_notes"] = []
                cell["student_notes"].append({"content": content, "timestamp": timestamp})
                break
        self._save_raw(lab_id, data)
        logger.info("cell_note_saved lab_id=%s cell_id=%s", lab_id, cell_id)

    def save_general_note(
        self,
        lab_id: str,
        content: str,
        timestamp: str,
    ) -> None:
        """Append a note to the lab's general_notes list and save."""
        data = self._load_raw(lab_id)
        if data is None:
            logger.warning("save_general_note: lab not found lab_id=%s", lab_id)
            return
        lab = data.get("lab", {})
        if "general_notes" not in lab:
            lab["general_notes"] = []
        lab["general_notes"].append({"content": content, "timestamp": timestamp})
        self._save_raw(lab_id, data)
        logger.info("general_note_saved lab_id=%s", lab_id)

    def mark_question_asked(
        self,
        lab_id: str,
        cell_id: str,
        question_text: str,
    ) -> None:
        """Set was_asked=True for a suggested question matching question_text."""
        data = self._load_raw(lab_id)
        if data is None:
            logger.warning("mark_question_asked: lab not found lab_id=%s", lab_id)
            return
        for cell in data.get("lab", {}).get("cells", []):
            if cell.get("id") == cell_id:
                for q in cell.get("suggested_questions", []):
                    if q.get("question") == question_text:
                        q["was_asked"] = True
                        break
                break
        self._save_raw(lab_id, data)
        logger.info("question_marked_asked lab_id=%s cell_id=%s", lab_id, cell_id)

    def mark_completed(self, lab_id: str) -> None:
        """Set completed_at timestamp on the lab response."""
        data = self._load_raw(lab_id)
        if data is None:
            logger.warning("mark_completed: lab not found lab_id=%s", lab_id)
            return
        data["completed_at"] = datetime.utcnow().isoformat() + "Z"
        self._save_raw(lab_id, data)
        logger.info("lab_marked_completed lab_id=%s", lab_id)

    def get_lab_notes_for_profiler(self, lab_id: str) -> dict:
        """
        Return everything the profiler needs from this lab.
        This is the ONLY method that includes timestamps.
        """
        data = self._load_raw(lab_id)
        if data is None:
            return {}
        lab = data.get("lab", {})
        cells_out = []
        for cell in lab.get("cells", []):
            cells_out.append({
                "cell_id": cell.get("id", ""),
                "cell_type": cell.get("cell_type", "unknown"),
                "title": cell.get("title", ""),
                "student_notes": cell.get("student_notes", []),
                "suggested_questions": cell.get("suggested_questions", []),
                "completed": bool(cell.get("completed", False)),
            })
        return {
            "general_notes": lab.get("general_notes", []),
            "cells": cells_out,
        }


_store: CodingLabStore | None = None


def get_coding_lab_store() -> CodingLabStore:
    global _store
    if _store is None:
        _store = CodingLabStore()
    return _store

