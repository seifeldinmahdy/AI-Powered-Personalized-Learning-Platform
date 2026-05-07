"""
Local file persistence for generated coding labs.

Labs are keyed by student/course/lesson and stored as JSON under
``ai_service/data/coding_labs``. This mirrors the lightweight persistence
approach used by student_context_store without involving Django.
"""

from __future__ import annotations

import json
import logging
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


_store: CodingLabStore | None = None


def get_coding_lab_store() -> CodingLabStore:
    global _store
    if _store is None:
        _store = CodingLabStore()
    return _store
