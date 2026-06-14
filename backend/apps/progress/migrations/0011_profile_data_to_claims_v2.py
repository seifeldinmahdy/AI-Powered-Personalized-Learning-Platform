"""Fold legacy flat profile_data into the v2 claims schema.

Legacy HOW-to-learn fields become claims (source="legacy", low confidence):
  learning_style_signals, recommended_approaches → recommended_approach
  emotional_tendencies{description,notable_patterns} → emotional_tendencies (singleton)
  engagement_patterns{high,low}                     → engagement (singleton)
  notable_intentions                                → neutral_context
  unresolved_questions                              → unresolved_question
  recurrent_mistakes                                → recurrent_process_mistake

COMPETENCE fields (topics_of_difficulty / topics_of_strength) are DROPPED — that
signal is owned by the mastery model (concept_mastery), not the qualitative
profile. profile_summary is preserved untouched. Odd/unexpected shapes are
LOGGED and skipped (never silently emptied). Reverse is a no-op (lossy forward).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.db import migrations

logger = logging.getLogger(__name__)

_LOW = 0.3  # legacy claims are low-confidence; real signals supersede them.


def _now():
    return datetime.now(timezone.utc).isoformat()


def _claim(field, value, conf=_LOW):
    return {"field": field, "value": str(value).strip(), "source": "legacy",
            "evidence": "migrated from legacy profile_data", "confidence": conf,
            "created_at": _now(), "superseded": False}


def forward(apps, schema_editor):
    SLP = apps.get_model("progress", "StudentLearningProfile")
    converted = dropped_competence = odd = 0
    for p in SLP.objects.all():
        pd = p.profile_data
        if not isinstance(pd, dict):
            odd += 1
            logger.warning("profile_v2: non-dict profile_data for student=%s (%r) — skipped",
                           p.student_id, type(pd).__name__)
            continue
        if pd.get("schema_version") == 2:
            continue  # already migrated

        claims = []

        def _list(name):
            v = pd.get(name, [])
            if v and not isinstance(v, list):
                logger.warning("profile_v2: %s not a list for student=%s — skipped", name, p.student_id)
                return []
            return v or []

        for v in _list("learning_style_signals"):
            claims.append(_claim("recommended_approach", v))
        for v in _list("recommended_approaches"):
            claims.append(_claim("recommended_approach", v))
        for v in _list("notable_intentions"):
            claims.append(_claim("neutral_context", v))
        for v in _list("unresolved_questions"):
            claims.append(_claim("unresolved_question", v))
        for v in _list("recurrent_mistakes"):
            claims.append(_claim("recurrent_process_mistake", v))

        et = pd.get("emotional_tendencies")
        if isinstance(et, dict):
            desc = et.get("description", "")
            pats = et.get("notable_patterns", []) or []
            text = "; ".join([t for t in ([desc] + [str(x) for x in pats]) if t])
            if text:
                claims.append(_claim("emotional_tendencies", text))
        elif et:
            logger.warning("profile_v2: emotional_tendencies odd shape student=%s — skipped", p.student_id)

        eng = pd.get("engagement_patterns")
        if isinstance(eng, dict):
            high = ", ".join(str(x) for x in (eng.get("high") or []))
            low = ", ".join(str(x) for x in (eng.get("low") or []))
            parts = []
            if high:
                parts.append(f"high when: {high}")
            if low:
                parts.append(f"low when: {low}")
            if parts:
                claims.append(_claim("engagement", "; ".join(parts)))
        elif eng:
            logger.warning("profile_v2: engagement_patterns odd shape student=%s — skipped", p.student_id)

        if pd.get("topics_of_difficulty") or pd.get("topics_of_strength"):
            dropped_competence += 1  # competence is mastery-owned now

        p.profile_data = {"schema_version": 2, "claims": claims}
        p.save(update_fields=["profile_data"])
        converted += 1

    logger.info("profile_v2_migration: converted=%s odd=%s competence_dropped=%s",
                converted, odd, dropped_competence)


def reverse(apps, schema_editor):
    # Lossy forward migration; nothing to restore.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("progress", "0010_studentlearningprofile_profile_version"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
