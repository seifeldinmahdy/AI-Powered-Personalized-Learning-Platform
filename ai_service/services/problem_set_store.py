"""
Local file persistence for generated problem sets.

Problem sets are keyed by student/lesson and stored as JSON under
``ai_service/data/problem_sets``. This mirrors the lightweight persistence
approach used by lab_store / student_context_store.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from schemas.problem_set import ProblemSetData, SubmissionData

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "problem_sets"


class ProblemSetStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = data_dir or _DATA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("ProblemSetStore initialised (dir=%s)", self._dir)

    # ── Key / path helpers ──────────────────────────────────────

    def _student_dir(self, student_id: str, lesson_id: str) -> Path:
        safe_student = student_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        safe_lesson = lesson_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        d = self._dir / safe_student / safe_lesson
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, student_id: str, lesson_id: str, problem_set_id: str) -> Path:
        safe_id = problem_set_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self._student_dir(student_id, lesson_id) / f"{safe_id}.json"

    # ── CRUD ────────────────────────────────────────────────────

    def save(self, data: ProblemSetData) -> None:
        path = self._path(data.student_id, data.lesson_id, data.problem_set_id)
        path.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        logger.info("problem_set_saved id=%s path=%s", data.problem_set_id, path)

    def load(self, student_id: str, lesson_id: str, problem_set_id: str) -> Optional[ProblemSetData]:
        path = self._path(student_id, lesson_id, problem_set_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ProblemSetData.model_validate(raw)
        except Exception as exc:
            logger.error("problem_set_load_failed id=%s error=%s", problem_set_id, exc)
            return None

    def find_by_student_lesson(self, student_id: str, lesson_id: str) -> list[ProblemSetData]:
        """Return all problem sets for a given student + lesson."""
        d = self._student_dir(student_id, lesson_id)
        results: list[ProblemSetData] = []
        for f in sorted(d.glob("*.json")):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                results.append(ProblemSetData.model_validate(raw))
            except Exception as exc:
                logger.warning("problem_set_skip file=%s error=%s", f, exc)
        return results

    def save_submission(
        self,
        student_id: str,
        lesson_id: str,
        problem_set_id: str,
        question_id: str,
        submission: SubmissionData,
    ) -> Optional[ProblemSetData]:
        """Save a submission for a specific question, return the updated problem set."""
        data = self.load(student_id, lesson_id, problem_set_id)
        if data is None:
            return None
        data.submissions[question_id] = submission
        self.save(data)
        return data

    def save_hint_deduction(
        self,
        student_id: str,
        lesson_id: str,
        problem_set_id: str,
        question_id: str,
        check_id: str,
        deduction: float,
        hint_number: int,
        hint_content: str,
    ) -> None:
        """Record a hint deduction immediately when a hint is revealed."""
        path = self._path(student_id, lesson_id, problem_set_id)
        if not path.exists():
            logger.warning("save_hint_deduction: problem set file not found %s", path)
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("save_hint_deduction: failed to read %s: %s", path, exc)
            return

        # Ensure hint tracking structures exist per question
        if "hint_tracking" not in raw:
            raw["hint_tracking"] = {}
        if question_id not in raw["hint_tracking"]:
            raw["hint_tracking"][question_id] = {
                "hint_deductions": {},
                "dynamic_hints_revealed": [],
            }

        tracking = raw["hint_tracking"][question_id]

        # Accumulate deduction for the check
        existing = tracking["hint_deductions"].get(check_id, 0.0)
        tracking["hint_deductions"][check_id] = existing + deduction

        # Record the hint reveal
        tracking["dynamic_hints_revealed"].append({
            "hint_number": hint_number,
            "content": hint_content,
            "targets_check_id": check_id,
            "penalty_applied": deduction,
        })

        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        logger.info(
            "hint_deduction_saved question=%s check=%s deduction=%.2f",
            question_id, check_id, deduction,
        )

    def load_submission_record(
        self,
        student_id: str,
        lesson_id: str,
        problem_set_id: str,
        question_id: str,
    ) -> dict | None:
        """Load raw submission dict for a question including hint_deductions."""
        path = self._path(student_id, lesson_id, problem_set_id)
        if not path.exists():
            return None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("load_submission_record: failed to read %s: %s", path, exc)
            return None

        # Merge hint tracking data into the submission record
        result: dict = {}

        # Get submission data if it exists
        submissions = raw.get("submissions", {})
        if question_id in submissions:
            sub = submissions[question_id]
            result.update(sub if isinstance(sub, dict) else {})

        # Get hint tracking data
        hint_tracking = raw.get("hint_tracking", {}).get(question_id, {})
        result["hint_deductions"] = hint_tracking.get("hint_deductions", {})
        result["dynamic_hints_revealed"] = hint_tracking.get("dynamic_hints_revealed", [])

        return result


# ── Module-level singleton ──────────────────────────────────────

_store: ProblemSetStore | None = None


def get_problem_set_store() -> ProblemSetStore:
    global _store
    if _store is None:
        _store = ProblemSetStore()
    return _store

