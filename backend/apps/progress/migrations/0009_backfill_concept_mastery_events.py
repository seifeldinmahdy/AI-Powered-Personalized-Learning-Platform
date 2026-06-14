"""Backfill the event log from the existing concept_mastery projection.

For every existing concept_mastery entry we append one ``source="backfill"``
seed event (outcome = current score, alpha = 1.0 so the fold from the 0.5 prior
lands exactly on it; evidence_delta = prior evidence; the full prior entry —
linked_mistakes + trend — carried on seed_meta). After seeding, we RE-FOLD each
concept and assert it round-trips to the exact pre-migration entry, logging any
mismatch. This makes current mastery reproducible from the log for legacy data.

Reverse: delete all backfill seed events.
"""

from __future__ import annotations

import logging

from django.db import migrations

logger = logging.getLogger(__name__)

_PRIOR = 0.5
_EPS = 0.02


def _fold(events):
    """Standalone fold (mirrors mastery_service.fold_events) for migration use."""
    score = _PRIOR
    evidence = 0
    had_real = False
    last_real_delta = 0.0
    seed_trend = None
    mistakes = []
    for ev in events:
        new = round(score + float(ev.alpha) * (float(ev.outcome) - score), 4)
        delta = new - score
        score = new
        evidence += int(ev.evidence_delta)
        if ev.source == "backfill":
            meta = ev.seed_meta or {}
            seed_trend = meta.get("trend", seed_trend)
            for m in (meta.get("linked_mistakes") or []):
                if m and m not in mistakes:
                    mistakes.append(m)
        else:
            had_real = True
            last_real_delta = delta
            if ev.mistake_tag and float(ev.outcome) < 0.5 and ev.mistake_tag not in mistakes:
                mistakes.append(ev.mistake_tag)
    trend = ("up" if last_real_delta > _EPS else ("down" if last_real_delta < -_EPS else "flat")) if had_real else (seed_trend or "flat")
    return {"score": score, "evidence": evidence, "trend": trend, "linked_mistakes": mistakes}


def backfill(apps, schema_editor):
    StudentLearningProfile = apps.get_model("progress", "StudentLearningProfile")
    ConceptMasteryEvent = apps.get_model("progress", "ConceptMasteryEvent")

    profiles_done = 0
    concepts_done = 0
    mismatches = 0
    for profile in StudentLearningProfile.objects.exclude(concept_mastery={}):
        cm = profile.concept_mastery or {}
        if not isinstance(cm, dict) or not cm:
            continue
        for cid, entry in cm.items():
            if not isinstance(entry, dict):
                continue
            score = float(entry.get("score", _PRIOR))
            score = max(0.0, min(1.0, score))
            ConceptMasteryEvent.objects.create(
                student_id=profile.student_id, concept_id=str(cid),
                outcome=score, source="backfill", alpha=1.0,
                evidence_delta=int(entry.get("evidence", 0)),
                mistake_tag="",
                seed_meta={
                    "linked_mistakes": entry.get("linked_mistakes", []),
                    "trend": entry.get("trend", "flat"),
                },
            )
            concepts_done += 1

            # ── Round-trip verification on real data ──
            rows = list(
                ConceptMasteryEvent.objects
                .filter(student_id=profile.student_id, concept_id=str(cid))
                .order_by("created_at", "id")
            )
            folded = _fold(rows)
            ok = (
                abs(folded["score"] - score) < 1e-9
                and folded["evidence"] == int(entry.get("evidence", 0))
                and folded["trend"] == entry.get("trend", "flat")
                and folded["linked_mistakes"] == list(entry.get("linked_mistakes", []))
            )
            if not ok:
                mismatches += 1
                logger.warning(
                    "backfill_roundtrip_mismatch student=%s concept=%s before=%s after=%s",
                    profile.student_id, cid, entry, folded,
                )
        profiles_done += 1

    logger.info(
        "concept_mastery_backfill_complete profiles=%s concepts=%s mismatches=%s",
        profiles_done, concepts_done, mismatches,
    )


def unbackfill(apps, schema_editor):
    ConceptMasteryEvent = apps.get_model("progress", "ConceptMasteryEvent")
    ConceptMasteryEvent.objects.filter(source="backfill").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("progress", "0008_conceptmasteryevent"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
