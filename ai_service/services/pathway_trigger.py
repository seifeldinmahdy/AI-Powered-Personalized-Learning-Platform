"""One-time, server-side pathway generation triggered by placement completion.

Generation is DECOUPLED from enroll/mount: it runs exactly once here, right
after placement seeds the knowledge signal. This is also the path that sets
``Enrollment.is_pathway_ready`` — the single runtime writer of that flag.

Latency note: generation (an LLM curriculum step on first run, then replayed)
now lands on placement submit, so the submit UX shows a "building your course"
state.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")


def _ensure_paths() -> None:
    for p in (str(_PROJECT_ROOT / "course_pathway"),
              str(_PROJECT_ROOT / "course_pathway" / "src"),
              str(_PROJECT_ROOT / "rag_pipeline")):
        if p not in sys.path:
            sys.path.insert(0, p)


def generate_after_placement(student_id: str, course_id: str, profile) -> bool:
    """Generate (once) the pathway for a freshly-placed student. Returns success.

    Deterministic + versioned: re-running with the same context returns the
    current version (no duplicate). Raises nothing — failures are logged and
    reported as ``False`` so placement still succeeds and the UI can show a
    clear "pathway unavailable" state.
    """
    _ensure_paths()
    try:
        from pathway.corpus_resolver import resolve_corpus_id  # type: ignore
        from pathway.clo_fetch import fetch_clo_concepts        # type: ignore
        from pathway.models.schemas import StudentContext       # type: ignore
        from pathway.generator import CoverageError             # type: ignore
        import router as pathway_router                          # type: ignore
    except Exception as exc:
        logger.error("pathway_trigger import failed: %s", exc)
        return False

    corpus_id = resolve_corpus_id(course_id)
    if not corpus_id:
        logger.warning("pathway_trigger: no corpus for course %s — skipping generation", course_id)
        return False

    context = StudentContext(
        student_id=str(student_id),
        course_id=str(course_id),
        corpus_id=corpus_id,
        mastery_level=profile.mastery_level,
        composition_mode=profile.composition_mode,
        language_proficiency=profile.language_proficiency,
        strengths=profile.strengths,
        weaknesses=profile.weaknesses,
        strength_concept_ids=profile.strength_concept_ids,
        weak_concept_ids=profile.weak_concept_ids,
        incorrectly_answered=profile.incorrectly_answered,
        course_intent=profile.course_intent or "",
        use_synthetic_context=False,
    )
    clo_concepts = fetch_clo_concepts(str(course_id))

    try:
        gen = pathway_router._get_generator()
        response = gen.generate(context, clo_concepts=clo_concepts, force_regenerate=False)
        logger.info(
            "pathway_trigger: generated student=%s course=%s version=%s sessions=%d",
            student_id, course_id, response.plan.plan_version, response.plan.total_sessions,
        )
        return True
    except CoverageError as exc:
        logger.error("pathway_trigger: CLO coverage failed for course %s: %s", course_id, exc)
        return False
    except Exception as exc:
        logger.exception("pathway_trigger: generation failed for course %s: %s", course_id, exc)
        return False


def regenerate_for_student(student_id: str, course_id: str) -> tuple[bool, str]:
    """Admin path: force a NEW plan version from the student's STORED context.

    Loads the student's current UnifiedStudentContext (concept-mastery derived)
    and regenerates with ``force_regenerate=True``. Returns (ok, detail).
    """
    _ensure_paths()
    from services.student_context_store import get_student_context_store
    from pathway.corpus_resolver import resolve_corpus_id  # type: ignore
    from pathway.clo_fetch import fetch_clo_concepts        # type: ignore
    from pathway.models.schemas import StudentContext       # type: ignore
    from pathway.generator import CoverageError             # type: ignore
    import router as pathway_router                          # type: ignore

    unified = get_student_context_store().load(str(student_id), str(course_id))
    if unified is None:
        return False, "No student context — student must complete placement first."
    p = unified.profile

    corpus_id = resolve_corpus_id(str(course_id))
    if not corpus_id:
        return False, f"No corpus defined for course {course_id}."

    context = StudentContext(
        student_id=str(student_id), course_id=str(course_id), corpus_id=corpus_id,
        mastery_level=p.mastery_level, composition_mode=p.composition_mode,
        language_proficiency=p.language_proficiency, strengths=p.strengths,
        weaknesses=p.weaknesses, strength_concept_ids=p.strength_concept_ids,
        weak_concept_ids=p.weak_concept_ids, incorrectly_answered=p.incorrectly_answered,
        course_intent=p.course_intent or "", use_synthetic_context=False,
    )
    clo_concepts = fetch_clo_concepts(str(course_id))
    try:
        gen = pathway_router._get_generator()
        resp = gen.generate(context, clo_concepts=clo_concepts, force_regenerate=True)
        return True, f"Regenerated as version {resp.plan.plan_version}."
    except CoverageError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.exception("regenerate_for_student failed")
        return False, str(exc)


def mark_pathway_ready(enrollment_id: int, student_id: str) -> None:
    """PATCH Enrollment.is_pathway_ready=True via the service key (single writer)."""
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    base = _DJANGO_API_URL.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.patch(
                f"{base}/courses/enrollments/{enrollment_id}/",
                json={"is_pathway_ready": True},
                headers={"X-Service-Key": service_key, "X-Student-ID": str(student_id)},
            )
            if resp.status_code not in (200, 202):
                logger.warning("mark_pathway_ready: status %s for enrollment %s",
                               resp.status_code, enrollment_id)
    except Exception as exc:
        logger.warning("mark_pathway_ready failed for enrollment %s: %s", enrollment_id, exc)
