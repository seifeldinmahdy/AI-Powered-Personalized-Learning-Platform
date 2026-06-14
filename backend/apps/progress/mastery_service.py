"""The ONE place concept mastery is mutated.

Mastery is event-sourced: appends to ``ConceptMasteryEvent`` are the source of
truth, and the per-concept score is a deterministic FOLD over that log. The
``StudentLearningProfile.concept_mastery`` JSONField is a derived read-model,
recomputed here so existing readers (dashboard, weak-concept targeting, CLO
attainment, capstone advisor, slides) keep their shape unchanged.

Why this is safe under concurrency: appends never conflict; the projection
recompute re-reads ALL committed events for the concept under a
``select_for_update`` lock on the profile row, so two concurrent updates to the
same concept both land (no lost update) — see test_mastery_concurrency.

Every reader keeps reading ``concept_mastery``; nobody else writes it.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.db import transaction

logger = logging.getLogger(__name__)

# A brand-new concept seeds at 0.5 (maximally uncertain) and EMA-walks from
# there. This matches the pre-event-sourcing default (build_entry used
# old_score=0.5 for an unseen concept), so behaviour is unchanged post-migration.
NEUTRAL_PRIOR = 0.5
_TREND_EPSILON = 0.02


def fold_events(ordered_events: Iterable) -> dict:
    """Fold an ORDERED event sequence into a projection entry.

    Pure function. ``ordered_events`` must already be sorted by
    ``(created_at, id)`` — the id tiebreak makes same-timestamp events fold
    deterministically. Each event exposes: ``outcome, alpha, evidence_delta,
    mistake_tag, seed_mistakes``.

    Returns ``{score, evidence, trend, last_updated, linked_mistakes}`` — the
    exact shape every reader already expects.
    """
    score = NEUTRAL_PRIOR
    evidence = 0
    last_real_delta = 0.0
    had_real_event = False
    seed_trend: str | None = None
    last_updated = None
    mistakes: list[str] = []

    for ev in ordered_events:
        alpha = float(ev.alpha)
        outcome = float(ev.outcome)
        new_score = round(score + alpha * (outcome - score), 4)
        delta = new_score - score
        score = new_score
        evidence += int(ev.evidence_delta)
        is_backfill = getattr(ev, "source", "") == "backfill"

        if is_backfill:
            # Seed carries the pre-migration entry verbatim → reproduce trend +
            # mistakes exactly; the seed's own delta does NOT drive trend.
            meta = getattr(ev, "seed_meta", None) or {}
            seed_trend = meta.get("trend", seed_trend)
            for m in (meta.get("linked_mistakes") or []):
                if m and m not in mistakes:
                    mistakes.append(m)
        else:
            had_real_event = True
            last_real_delta = delta
            if ev.mistake_tag and outcome < 0.5 and ev.mistake_tag not in mistakes:
                mistakes.append(ev.mistake_tag)

        last_updated = getattr(ev, "created_at", None)

    if had_real_event:
        trend = "up" if last_real_delta > _TREND_EPSILON else ("down" if last_real_delta < -_TREND_EPSILON else "flat")
    else:
        trend = seed_trend or "flat"
    return {
        "score": score,
        "evidence": evidence,
        "trend": trend,
        "last_updated": last_updated.isoformat() if last_updated else None,
        "linked_mistakes": mistakes,
    }


def record_events(student_id: int, events: list[dict]) -> dict:
    """Append mastery events and recompute the affected concepts' projection.

    THE single mutator of ``concept_mastery``. ``events`` is a list of
    ``{concept_id, outcome, source, alpha?, evidence_delta?, mistake_tag?}``.

    Returns the updated subset ``{concept_id: entry}`` so callers can echo it.
    """
    from apps.progress.models import StudentLearningProfile, ConceptMasteryEvent

    norm: list[dict] = []
    affected: list[str] = []
    for e in events:
        cid = str(e["concept_id"])
        if not cid:
            continue
        norm.append({
            "concept_id": cid,
            "outcome": max(0.0, min(1.0, float(e["outcome"]))),
            "source": e["source"],
            "alpha": float(e.get("alpha", 0.3)),
            "evidence_delta": int(e.get("evidence_delta", 1)),
            "mistake_tag": e.get("mistake_tag", "") or "",
        })
        if cid not in affected:
            affected.append(cid)

    if not norm:
        return {}

    updated: dict[str, dict] = {}
    with transaction.atomic():
        # Lock the profile row FIRST so concurrent record_events for the same
        # student serialize before any append/fold happens.
        StudentLearningProfile.objects.get_or_create(student_id=student_id)
        profile = (
            StudentLearningProfile.objects.select_for_update().get(student_id=student_id)
        )

        ConceptMasteryEvent.objects.bulk_create([
            ConceptMasteryEvent(
                student_id=student_id, concept_id=n["concept_id"], outcome=n["outcome"],
                source=n["source"], alpha=n["alpha"], evidence_delta=n["evidence_delta"],
                mistake_tag=n["mistake_tag"],
            )
            for n in norm
        ])

        cm = dict(profile.concept_mastery or {})
        for cid in affected:
            rows = list(
                ConceptMasteryEvent.objects
                .filter(student_id=student_id, concept_id=cid)
                .order_by("created_at", "id")
            )
            entry = fold_events(rows)
            cm[cid] = entry
            updated[cid] = entry

        profile.concept_mastery = cm
        profile.save(update_fields=["concept_mastery"])

    logger.info(
        "concept_mastery_recorded student=%s concepts=%s sources=%s",
        student_id, affected, sorted({n["source"] for n in norm}),
    )
    return updated
