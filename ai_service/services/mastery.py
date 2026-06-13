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


def build_entry(
    old_entry: dict,
    outcome: float,
    mistake_tag: str | None = None,
) -> dict:
    """Build a fully updated mastery entry dict ready for JSON storage.

    Args:
        old_entry: existing {score, evidence, trend, last_updated, linked_mistakes}
                   or {} if first time seeing this concept.
        outcome:   0.0 (failed) or 1.0 (passed).
        mistake_tag: rubric category string to append to linked_mistakes on failure.
    """
    old_score = float(old_entry.get("score", 0.5))
    new_score = update(old_score, outcome)
    evidence = int(old_entry.get("evidence", 0)) + 1
    trend = derive_trend(old_score, new_score)

    mistakes = list(old_entry.get("linked_mistakes", []))
    if mistake_tag and outcome == 0.0 and mistake_tag not in mistakes:
        mistakes.append(mistake_tag)

    return {
        "score": new_score,
        "evidence": evidence,
        "trend": trend,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "linked_mistakes": mistakes,
    }


def top_weak_concepts(concept_mastery: dict, n: int = 3) -> list[dict]:
    """Return up to n weakest concepts, sorted by (score asc, evidence asc).

    Low score first; ties broken by low evidence (uncertain = also worth targeting).
    """
    entries = [{"concept_id": k, **v} for k, v in concept_mastery.items()]
    return sorted(
        entries,
        key=lambda e: (e.get("score", 0.5), e.get("evidence", 0)),
    )[:n]


def compute_mastery_updates(
    evaluated_rubric: list,
    existing_concept_mastery: dict,
) -> dict:
    """Given evaluated rubric criteria (with optional concept_id) and the
    existing concept_mastery dict, return the subset of concept_mastery that
    changed and should be PATCHed to Django.

    This function is pure — no I/O. It aggregates binary outcomes per concept:
    if multiple criteria target the same concept, the outcome is averaged before
    calling update().
    """
    # Collect all (concept_id, binary_outcome, category) tuples
    per_concept: dict[str, list[float]] = {}
    per_concept_tag: dict[str, str] = {}

    for crit in evaluated_rubric:
        crit_dict = crit if isinstance(crit, dict) else crit.model_dump()
        concept_id = crit_dict.get("concept_id")
        if not concept_id:
            continue

        category = crit_dict.get("category", "")
        checks = crit_dict.get("checks", [])
        if not checks:
            continue

        # Average the binary check outcomes for this criterion
        check_outcomes = [
            1.0 if c.get("result") is True else 0.0
            for c in checks
        ]
        avg_outcome = sum(check_outcomes) / len(check_outcomes)
        per_concept.setdefault(concept_id, []).append(avg_outcome)

        # Track the most "failing" category for linked_mistakes
        if avg_outcome < 0.5:
            per_concept_tag[concept_id] = category

    updates: dict = {}
    for concept_id, outcomes in per_concept.items():
        final_outcome = sum(outcomes) / len(outcomes)
        old_entry = existing_concept_mastery.get(str(concept_id), {})
        mistake_tag = per_concept_tag.get(concept_id)
        updates[str(concept_id)] = build_entry(old_entry, final_outcome, mistake_tag)

    return updates


# ── Async helpers (I/O) ──────────────────────────────────────────

DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")


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


async def patch_concept_mastery(student_id: str, updates: dict) -> None:
    """PATCH the student's concept_mastery on Django with the provided updates."""
    if not updates:
        return
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                f"{DJANGO_API_URL}/progress/learning-profile/update/",
                json={"concept_mastery": updates},
                headers={"X-Student-ID": student_id, "X-Service-Key": service_key},
            )
            if resp.status_code not in (200, 204):
                logger.warning(
                    "concept_mastery PATCH returned %d for student %s",
                    resp.status_code, student_id,
                )
    except Exception as e:
        logger.warning("Could not PATCH concept_mastery for student %s: %s", student_id, e)


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
) -> None:
    """Fire-and-forget: fetch existing mastery, compute updates, PATCH back.

    Designed to be called as asyncio.create_task() from the submit endpoint.
    """
    try:
        existing = await fetch_concept_mastery(student_id)
        updates = compute_mastery_updates(evaluated_rubric, existing)
        if updates:
            await patch_concept_mastery(student_id, updates)
            logger.info(
                "Updated concept_mastery for student %s: %d concept(s)",
                student_id, len(updates),
            )
    except Exception:
        logger.exception("concept_mastery update failed for student %s", student_id)
