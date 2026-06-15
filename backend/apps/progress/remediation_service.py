"""
Post-generation adaptivity — the remediation trigger (Batch 11a).

When a concept's event-sourced mastery (Batch 6) drops below the trigger
threshold, a review step is inserted into the student's plan as an OVERLAY: it
references the current plan_version + concept but never mutates the immutable,
versioned pathway and never changes plan_version. The resume timeline positions
it after the session that teaches the concept.

Reads the EXISTING mastery read-model (StudentLearningProfile.concept_mastery,
the projection the single fold writer maintains) — not a new signal.

Determinism + bounding:
  - ``evaluate`` is a pure function of (current mastery state, thresholds): the
    same state yields the same inserts/resolves; re-running is idempotent.
  - "Crosses below" is realized as "below the floor AND no open step" + auto
    "resolve on recovery to the resolve bar". Together that is exactly one
    remediation per downward crossing, without storing the previous score.
  - A DB partial-unique (one 'pending' per enrollment/plan_version/concept)
    backstops concurrent posts: the loser's insert is caught as 'already pending'
    rather than raising an unhandled IntegrityError.
"""

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import RemediationStep, StudentLearningProfile

logger = logging.getLogger(__name__)


def _trigger_threshold() -> float:
    return float(getattr(settings, "REMEDIATION_TRIGGER_THRESHOLD", 0.45))


def _resolve_threshold() -> float:
    return float(getattr(settings, "REMEDIATION_RESOLVE_THRESHOLD", 0.55))


def evaluate(student_id: int, enrollment, plan_version: int, concept_scores: dict) -> dict:
    """Insert/resolve remediation for the given concepts from the mastery state.

    ``concept_scores``: ``{concept_id(str): score(float)}`` — typically the subset
    just updated by record_events (already the read-model's fold result). Returns
    ``{"inserted": [concept_id...], "resolved": [concept_id...]}``. Deterministic
    and idempotent for a given state.
    """
    trigger = _trigger_threshold()
    resolve_bar = _resolve_threshold()
    inserted, resolved = [], []

    for concept_id, score in concept_scores.items():
        cid = str(concept_id)
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue

        if score < trigger:
            if _insert_if_absent(student_id, enrollment, plan_version, cid, trigger, score):
                inserted.append(cid)
        elif score >= resolve_bar:
            if _resolve_open(enrollment, plan_version, cid):
                resolved.append(cid)
        # Between trigger and resolve_bar: hysteresis band — leave state as-is
        # (no new insert, no premature resolve), so the step doesn't flap.

    if inserted or resolved:
        logger.info(
            "remediation evaluate student=%s plan_v=%s inserted=%s resolved=%s",
            student_id, plan_version, inserted, resolved,
        )
    return {"inserted": inserted, "resolved": resolved}


def evaluate_from_request(student_id, enrollment, plan_version, updated: dict) -> dict:
    """Adapt record_events' ``{concept_id: {score, ...}}`` to evaluate()."""
    concept_scores = {
        cid: entry.get("score")
        for cid, entry in (updated or {}).items()
        if isinstance(entry, dict) and "score" in entry
    }
    if not concept_scores:
        return {"inserted": [], "resolved": []}
    return evaluate(student_id, enrollment, int(plan_version), concept_scores)


def _insert_if_absent(student_id, enrollment, plan_version, concept_id, trigger, score) -> bool:
    """Create one pending step unless one already exists. Returns True if created.

    Concurrency-safe: the existence check is best-effort; the DB partial-unique is
    the real backstop, and a racing duplicate insert is caught as 'already
    pending' (no unhandled IntegrityError).
    """
    base = dict(enrollment=enrollment, plan_version=int(plan_version), concept_id=int(concept_id))
    if RemediationStep.objects.filter(status=RemediationStep.PENDING, **base).exists():
        return False
    try:
        with transaction.atomic():  # contain the IntegrityError so the txn survives
            RemediationStep.objects.create(
                student_id=student_id, course_id=enrollment.course_id,
                kind="review", trigger_threshold=float(trigger),
                score_at_trigger=float(score), status=RemediationStep.PENDING, **base,
            )
        return True
    except IntegrityError:
        # A near-simultaneous post won the partial-unique race — already pending.
        logger.info(
            "remediation insert race: already pending (enrollment=%s plan_v=%s concept=%s)",
            enrollment.id, plan_version, concept_id,
        )
        return False


def _resolve_open(enrollment, plan_version, concept_id) -> bool:
    """Resolve any open step for this concept (mastery recovered). Idempotent."""
    updated = RemediationStep.objects.filter(
        enrollment=enrollment, plan_version=int(plan_version),
        concept_id=int(concept_id), status=RemediationStep.PENDING,
    ).update(status=RemediationStep.RESOLVED, resolved_at=timezone.now())
    return updated > 0


def pending_for_enrollment(enrollment, plan_version):
    """Index-light queryset of pending steps for the resume timeline (no content)."""
    return (
        RemediationStep.objects
        .filter(enrollment=enrollment, plan_version=int(plan_version), status=RemediationStep.PENDING)
        .values("id", "concept_id", "kind", "status", "score_at_trigger", "created_at")
    )
