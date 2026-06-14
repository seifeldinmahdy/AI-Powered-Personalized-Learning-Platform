"""
plan_version resolution + guard for artifact writes (Batch 10a, stage 2).

Artifacts are keyed by ``plan_version`` so a regenerated pathway can never strand
or collide with old artifacts. The authoritative plan version lives in the
course_pathway SQLite store (``session_plans_v2``) — there is no cross-DB FK to
the Postgres artifact index. This module is the one place that bridges them:

  - ``current_plan_version`` — the current (is_current) version for a student+course.
  - ``known_plan_versions`` — every version ever generated for that pair.
  - ``validate_plan_version`` — the GUARD: if a plan_version is NOT a known
    version for the enrollment, it LOGS a warning and returns False. It never
    silently coerces to "current" — a mismatch matters for the Batch 10b resume
    timeline and must be visible, not papered over.
  - ``resolve_for_write`` — pick the plan_version to stamp on a new artifact:
    use the caller's value if given (validated + warned, NOT coerced), else the
    current version.

The PlanStore is injectable so this is unit-testable without a real SQLite file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _ensure_paths() -> None:
    for p in (str(_PROJECT_ROOT / "course_pathway"),
              str(_PROJECT_ROOT / "course_pathway" / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)


def _default_store():
    """Construct the real PlanStore from pathway settings."""
    _ensure_paths()
    from pathway.config import get_settings  # type: ignore
    from pathway.storage.plan_store import PlanStore  # type: ignore
    return PlanStore(db_path=get_settings().sqlite_db_path)


def current_plan_version(student_id: str, course_id: str, *, store=None) -> Optional[int]:
    """The current plan version for student+course, or None if no plan exists."""
    try:
        store = store or _default_store()
        plan = store.load_current(str(student_id), str(course_id))
        return int(plan.plan_version) if plan is not None else None
    except Exception as exc:
        logger.warning("plan_resolver: current_plan_version failed (student=%s course=%s): %s",
                       student_id, course_id, exc)
        return None


def known_plan_versions(student_id: str, course_id: str, *, store=None) -> set[int]:
    """Every plan version ever generated for student+course."""
    try:
        store = store or _default_store()
        return {int(v["plan_version"]) for v in store.list_versions(str(student_id), str(course_id))}
    except Exception as exc:
        logger.warning("plan_resolver: known_plan_versions failed (student=%s course=%s): %s",
                       student_id, course_id, exc)
        return set()


def validate_plan_version(student_id: str, course_id: str, plan_version: int, *, store=None) -> bool:
    """GUARD: True if ``plan_version`` is a known version for this enrollment.

    On mismatch, LOG a warning and return False — callers must NOT silently treat
    an unknown version as current (it would corrupt the resume timeline in 10b).
    """
    known = known_plan_versions(student_id, course_id, store=store)
    if plan_version in known:
        return True
    logger.warning(
        "plan_resolver: plan_version MISMATCH student=%s course=%s artifact_version=%s "
        "known=%s — recording as-is, NOT coercing to current.",
        student_id, course_id, plan_version, sorted(known),
    )
    return False


def resolve_for_write(student_id: str, course_id: str,
                      requested: Optional[int] = None, *, store=None) -> Optional[int]:
    """Pick the plan_version to stamp on a new artifact.

    - ``requested`` given: validate (warn on mismatch) but use it as-is.
    - otherwise: the current version (or None if the student has no plan yet).
    """
    if requested is not None:
        validate_plan_version(student_id, course_id, int(requested), store=store)
        return int(requested)
    return current_plan_version(student_id, course_id, store=store)
