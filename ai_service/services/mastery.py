"""
Deterministic concept-mastery update helper.

This is the ONLY module allowed to change numeric mastery scores.
The LLM never emits mastery scores or grades — it only provides binary
pass/fail judgments. This module converts those into EMA-smoothed scores.

All functions are pure (no I/O) except for the async helpers that talk
to Django, which are kept at the bottom and clearly marked.
"""

from __future__ import annotations

import math
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

ALPHA = 0.3          # EMA smoothing factor
EPSILON = 0.02       # minimum delta to declare trend change


# ── Pure math ────────────────────────────────────────────────────

def update(old_score: float, outcome: float, alpha: float = ALPHA) -> float:
    """Exponential moving average: new = old + alpha*(outcome - old).
    outcome is 0.0 (fail) or 1.0 (pass) from a binary check.
    """
    return round(old_score + alpha * (outcome - old_score), 4)


def time_decay(score: float, days_since: float, half_life: float = 30.0) -> float:
    """Decay score toward 0.5 (neutral) when evidence stops arriving.
    After `half_life` days with no evidence, the distance from 0.5 halves.
    """
    decay = math.exp(-math.log(2) * days_since / half_life)
    return round(0.5 + (score - 0.5) * decay, 4)


def derive_trend(old_score: float, new_score: float, epsilon: float = EPSILON) -> str:
    if new_score > old_score + epsilon:
        return "up"
    if new_score < old_score - epsilon:
        return "down"
    return "flat"


def derive_mastery_level(
    concept_mastery: dict,
    course_concept_ids: set[str] | None = None,
    *,
    expert_threshold: float = 0.75,
    intermediate_threshold: float = 0.45,
) -> str:
    """Derive the overall mastery_level from per-concept mastery.

    mastery_level is a DERIVED aggregate of concept mastery that moves as the
    student progresses: the mean score over concepts PRESENT in the projection
    (optionally restricted to the course's concept set), thresholded.

    Post-event-sourcing, a concept is present iff it has at least one event, so
    "present" already means "has data". We therefore do NOT gate on evidence>0 —
    that would make an assist-only concept (evidence_delta 0, but a real,
    lowered score) read as "no data" and silently drop out of the mean. Such a
    concept SHOULD count (the student needed help on it).

    Returns "Novice" when the student has no concept data at all.
    """
    scores = [
        float(v.get("score", 0.0))
        for k, v in (concept_mastery or {}).items()
        if (course_concept_ids is None or str(k) in course_concept_ids)
        and isinstance(v, dict) and "score" in v
    ]
    if not scores:
        return "Novice"
    mean = sum(scores) / len(scores)
    if mean >= expert_threshold:
        return "Expert"
    if mean >= intermediate_threshold:
        return "Intermediate"
    return "Novice"


def top_weak_concepts(concept_mastery: dict, n: int = 3) -> list[dict]:
    """Return up to n weakest concepts, sorted by (score asc, evidence asc).

    Low score first; ties broken by low evidence (uncertain = also worth targeting).
    """
    entries = [{"concept_id": k, **v} for k, v in concept_mastery.items()]
    return sorted(
        entries,
        key=lambda e: (e.get("score", 0.5), e.get("evidence", 0)),
    )[:n]


def outcomes_from_eval(evaluated_rubric: list) -> list[dict]:
    """Aggregate evaluated rubric criteria into per-concept OUTCOMES (no EMA).

    Pure. The EMA + persistence now live behind the single Django writer
    (mastery_service.record_events); here we only produce
    ``[{concept_id, outcome, mistake_tag}]`` to send it.
    """
    per_concept: dict[str, list[float]] = {}
    per_concept_tag: dict[str, str] = {}
    for crit in evaluated_rubric:
        crit_dict = crit if isinstance(crit, dict) else crit.model_dump()
        concept_id = crit_dict.get("concept_id")
        if not concept_id:
            continue
        checks = crit_dict.get("checks", [])
        if not checks:
            continue
        avg_outcome = sum(1.0 if c.get("result") is True else 0.0 for c in checks) / len(checks)
        per_concept.setdefault(str(concept_id), []).append(avg_outcome)
        if avg_outcome < 0.5:
            per_concept_tag[str(concept_id)] = crit_dict.get("category", "")

    return [
        {
            "concept_id": cid,
            "outcome": sum(outs) / len(outs),
            "mistake_tag": per_concept_tag.get(cid, ""),
        }
        for cid, outs in per_concept.items()
    ]


# ── Async helpers (I/O) ──────────────────────────────────────────

DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")


async def post_mastery_events(student_id: str, events: list[dict]) -> None:
    """POST mastery events to the SINGLE Django writer (/progress/mastery/record).

    This is how ai_service mutates concept mastery — it no longer computes EMA or
    PATCHes the projection. ``events`` items: ``{concept_id|topic+course_id,
    outcome, source, alpha?, evidence_delta?, mistake_tag?}``.
    """
    if not events:
        return
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{DJANGO_API_URL}/progress/mastery/record/",
                json={"events": events},
                headers={"X-Student-ID": str(student_id), "X-Service-Key": service_key},
            )
            if resp.status_code not in (200, 201):
                logger.warning("mastery/record returned %d for student %s", resp.status_code, student_id)
    except Exception as e:
        logger.warning("Could not POST mastery events for student %s: %s", student_id, e)


async def fetch_concept_mastery(student_id: str) -> dict:
    """Fetch the student's concept_mastery dict from Django profile."""
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{DJANGO_API_URL}/progress/learning-profile/",
                headers={"X-Student-ID": student_id, "X-Service-Key": service_key},
            )
            if resp.status_code == 200:
                return resp.json().get("concept_mastery", {})
    except Exception as e:
        logger.warning("Could not fetch concept_mastery for student %s: %s", student_id, e)
    return {}


async def fetch_course_concepts(course_id: str) -> list[dict]:
    """Fetch [{id, label}] list of concepts for a course from Django."""
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{DJANGO_API_URL}/courses/courses/{course_id}/concepts/",
                headers={"X-Service-Key": service_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data) if isinstance(data, dict) else data
                return [{"id": str(c["id"]), "label": c["label"]} for c in results]
    except Exception as e:
        logger.warning("Could not fetch concepts for course %s: %s", course_id, e)
    return []


async def update_concept_mastery_from_eval(
    student_id: str,
    evaluated_rubric: list,
    alpha: float = 0.3,
) -> None:
    """Fire-and-forget: send problem-set outcomes to the single mastery writer.

    ``alpha`` is the per-call EMA weight — Batch 10's attempt policy passes a
    down-weighted alpha for regenerated-set attempts; this code stays unaware of
    why. No EMA/RMW here: the Django writer folds it.
    """
    try:
        outcomes = outcomes_from_eval(evaluated_rubric)
        events = [
            {**o, "source": "problem_set", "alpha": alpha}
            for o in outcomes
        ]
        if events:
            await post_mastery_events(student_id, events)
            logger.info(
                "Recorded problem-set mastery for student %s: %d concept(s)",
                student_id, len(events),
            )
    except Exception:
        logger.exception("concept_mastery update failed for student %s", student_id)
