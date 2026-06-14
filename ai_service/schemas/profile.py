"""Versioned learning-profile schema (v2) — the single typed contract.

Every profiler validates its output against this. Two invariants are baked in:

1. PROVENANCE + CONFIDENCE per claim, so contradictions resolve by rule (a
   strong, rubric-grounded signal supersedes a weak inferred one) instead of
   silently.
2. NO concept-competence field. "Knows / weak at concept X" is owned SOLELY by
   the mastery model (Batch 6). Qualitative profilers may only describe HOW the
   student learns: pace, modality, engagement, recurrent PROCESS mistakes,
   unresolved questions, recommended approaches (+ neutral context).

profile_data shape:  {"schema_version": 2, "claims": [Claim, ...]}
"""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 2

# How-the-student-LEARNS fields only. There is intentionally NO competence field.
SINGLETON_FIELDS = {"pace", "preferred_modality", "engagement", "emotional_tendencies"}
LIST_FIELDS = {
    "recurrent_process_mistake", "unresolved_question",
    "recommended_approach", "neutral_context",
}
ALLOWED_FIELDS = SINGLETON_FIELDS | LIST_FIELDS

# neutral_context is NEVER an inference — readers must not derive traits from it.
NON_INFERENCE_FIELDS = {"neutral_context"}

ClaimField = Literal[
    "pace", "preferred_modality", "engagement", "emotional_tendencies",
    "recurrent_process_mistake", "unresolved_question",
    "recommended_approach", "neutral_context",
]
ClaimSource = Literal["session", "lab", "problem_set", "legacy"]

# Authority ∝ evidence quality (mastery model is separate; it owns competence).
SOURCE_AUTHORITY = {"problem_set": 3, "session": 2, "lab": 1, "legacy": 0}

# The lab profiler is junior: everything it writes is low-confidence.
LAB_MAX_CONFIDENCE = 0.4
# Bound list fields so near-dupes that slip the fuzzy match can't grow unbounded.
PER_FIELD_CAP = 8
# difflib ratio at/above which two list-field values are the SAME subject.
NEAR_DUP_RATIO = 0.82


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (value or "").lower())).strip()


class Claim(BaseModel):
    model_config = {"extra": "forbid"}

    field: ClaimField
    value: str
    source: ClaimSource
    evidence: str = ""
    confidence: float = 0.5
    created_at: str = Field(default_factory=_now)
    superseded: bool = False

    @field_validator("value")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("claim value must be non-empty")
        return v.strip()

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def subject_key(self) -> str:
        """Identity used for collision/supersession.

        Singleton fields collapse to one live claim (key = field). List fields
        key on the normalized value, so the same mistake re-stated supersedes
        rather than accumulates (fuzzy near-dup handled in the writer's merge).
        """
        if self.field in SINGLETON_FIELDS:
            return self.field
        return f"{self.field}::{_normalize(self.value)}"


def validate_claims(raw: list[dict], source: ClaimSource) -> list[Claim]:
    """Parse + structurally guard LLM output into Claims.

    - Unknown/competence fields are DROPPED (a profiler cannot emit outside its
      remit even if the LLM tries).
    - ``source`` is forced (a profiler can't spoof a higher authority).
    - Lab claims are capped at LAB_MAX_CONFIDENCE.
    Invalid items are skipped (caller logs counts).
    """
    out: list[Claim] = []
    for item in raw or []:
        try:
            data = dict(item)
            data["source"] = source
            if data.get("field") not in ALLOWED_FIELDS:
                continue  # structural guard: no competence / unknown fields
            if source == "lab":
                data["confidence"] = min(float(data.get("confidence", LAB_MAX_CONFIDENCE)), LAB_MAX_CONFIDENCE)
            out.append(Claim(**data))
        except Exception:
            continue
    return out


def _rank(claim: dict) -> tuple:
    """Higher is better: authority, then confidence, then recency."""
    return (
        SOURCE_AUTHORITY.get(claim.get("source", "legacy"), 0),
        float(claim.get("confidence", 0.0)),
        claim.get("created_at", ""),
    )


def flatten_profile_for_readers(profile_data: dict) -> dict:
    """Collapse claims into a simple shape for tutor/lab/ps readers.

    Returns only HOW-to-learn signals (NO competence — readers get that from the
    mastery model). Singleton fields → best single value or None; list fields →
    list of values (best first). neutral_context is returned separately and is
    never to be treated as a trait.
    """
    claims = (profile_data or {}).get("claims", []) if isinstance(profile_data, dict) else []
    live = [c for c in claims if isinstance(c, dict) and not c.get("superseded")]

    out: dict = {
        "pace": None, "preferred_modality": None, "engagement": None,
        "emotional_tendencies": None,
        "recurrent_process_mistakes": [], "unresolved_questions": [],
        "recommended_approaches": [], "neutral_context": [],
    }
    plural = {
        "recurrent_process_mistake": "recurrent_process_mistakes",
        "unresolved_question": "unresolved_questions",
        "recommended_approach": "recommended_approaches",
        "neutral_context": "neutral_context",
    }
    for f in SINGLETON_FIELDS:
        cands = [c for c in live if c.get("field") == f]
        if cands:
            out[f] = max(cands, key=_rank)["value"]
    for f, key in plural.items():
        vals = [c for c in live if c.get("field") == f]
        out[key] = [c["value"] for c in sorted(vals, key=_rank, reverse=True)]
    return out


def near_duplicate(a: str, b: str) -> bool:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio() >= NEAR_DUP_RATIO
