"""The ONE writer of the learning profile (profile_data claims + summary).

All three profilers (session/lab/problem_set) funnel their structured CLAIMS
through ``apply_claims``. Writes are ADDITIVE and serialized with a row lock, so
profilers never clobber each other (the old frontend read-modify-write overwrite
is gone). Provenance + confidence on every claim let a stronger signal supersede
a weaker one by rule.

No competence here: a claim whose field is a competence verdict is rejected
(defense-in-depth — the ai_service schema already drops them). Competence lives
in the mastery model (concept_mastery).

Mirrors the constants in ai_service/schemas/profile.py (separate codebase).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from django.db import transaction

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
SINGLETON_FIELDS = {"pace", "preferred_modality", "engagement", "emotional_tendencies"}
LIST_FIELDS = {"recurrent_process_mistake", "unresolved_question", "recommended_approach", "neutral_context"}
ALLOWED_FIELDS = SINGLETON_FIELDS | LIST_FIELDS
SOURCE_AUTHORITY = {"problem_set": 3, "session": 2, "lab": 1, "legacy": 0}
PER_FIELD_CAP = 8
NEAR_DUP_RATIO = 0.82


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (value or "").lower())).strip()


def _rank(c: dict) -> tuple:
    return (
        SOURCE_AUTHORITY.get(c.get("source", "legacy"), 0),
        float(c.get("confidence", 0.0)),
        c.get("created_at", ""),
    )


def _same_subject(incoming: dict, existing: dict) -> bool:
    """Whether two claims describe the same thing (→ supersession candidate)."""
    if incoming.get("field") != existing.get("field"):
        return False
    field = incoming["field"]
    if field in SINGLETON_FIELDS:
        return True  # one live claim per singleton field
    a, b = incoming.get("value", ""), existing.get("value", "")
    if _normalize(a) == _normalize(b):
        return True
    # Fuzzy near-duplicate so re-stated mistakes collapse instead of accumulate.
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio() >= NEAR_DUP_RATIO


def apply_claims(student_id: int, claims: list[dict],
                 summary: str | None = None, summary_source: str | None = None) -> dict:
    """Apply structured claims additively under a row lock. Returns the profile_data.

    Resolution: for a same-subject collision, the higher (authority, confidence,
    recency) claim stays live and the other is marked ``superseded`` (kept for
    audit). List fields are capped so they can't grow unbounded.
    """
    from apps.progress.models import StudentLearningProfile

    # Structural guard at the writer too: drop anything outside the remit.
    clean: list[dict] = []
    for c in claims or []:
        if not isinstance(c, dict) or c.get("field") not in ALLOWED_FIELDS:
            logger.warning("apply_claims: rejected out-of-remit claim: %s", c)
            continue
        if not str(c.get("value", "")).strip():
            continue
        clean.append({
            "field": c["field"],
            "value": str(c["value"]).strip(),
            "source": c.get("source", "session"),
            "evidence": c.get("evidence", ""),
            "confidence": max(0.0, min(1.0, float(c.get("confidence", 0.5)))),
            "created_at": c.get("created_at") or _now(),
            "superseded": False,
        })

    with transaction.atomic():
        StudentLearningProfile.objects.get_or_create(student_id=student_id)
        profile = StudentLearningProfile.objects.select_for_update().get(student_id=student_id)

        pd = profile.profile_data if isinstance(profile.profile_data, dict) else {}
        existing: list[dict] = list(pd.get("claims", []))

        for inc in clean:
            live_same = [
                e for e in existing
                if not e.get("superseded") and _same_subject(inc, e)
            ]
            if live_same:
                best = max(live_same, key=_rank)
                if _rank(inc) >= _rank(best):
                    for e in live_same:
                        e["superseded"] = True   # incoming supersedes prior live
                    existing.append(inc)
                else:
                    inc["superseded"] = True       # weaker than current; keep for audit
                    existing.append(inc)
            else:
                existing.append(inc)

        # Per-field cap on LIVE list-field claims.
        for field in LIST_FIELDS:
            live = [e for e in existing if e.get("field") == field and not e.get("superseded")]
            if len(live) > PER_FIELD_CAP:
                for e in sorted(live, key=_rank)[: len(live) - PER_FIELD_CAP]:
                    e["superseded"] = True

        profile.profile_data = {"schema_version": SCHEMA_VERSION, "claims": existing}
        # Summary is session-authored only, with the optimistic version guard.
        if summary is not None and summary_source == "session":
            profile.profile_summary = summary
        profile.profile_version = int(profile.profile_version or 0) + 1
        profile.save(update_fields=["profile_data", "profile_summary", "profile_version", "last_updated"])

    logger.info(
        "profile_claims_applied student=%s applied=%d version=%d",
        student_id, len(clean), profile.profile_version,
    )
    return profile.profile_data
