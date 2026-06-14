"""Pydantic v2 data contracts for the Course Pathway Generator.

Every cross-module boundary uses one of these models.  Raw text chunks
flow between all downstream consumers (Content Specialist, MCQ service).
Page ranges are display metadata only.
"""

# NOTE: Do NOT add `from __future__ import annotations` here.
# Pydantic v2 resolves type annotations at class-definition time.  The
# future import makes all annotations lazy strings, which breaks model
# identity checks when Streamlit (or any hot-reloader) reimports the
# module — `Session` from the cached import and `Session` from the fresh
# import become different Python objects, causing ValidationError even
# though they are structurally identical.

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


# ── Student Context ──────────────────────────────────────────────


class StudentContext(BaseModel):
    """Full student context for pathway personalisation.

    When ``use_synthetic_context`` is True the personalization layer will
    ignore the supplied strengths/weaknesses and instead generate a
    plausible synthetic set via ``SyntheticContextGenerator``.
    """

    student_id: str = Field(..., description="Unique student identifier")
    course_id: str = Field(..., description="Django course identifier (system of record). Used for cache keys/logging, NOT as a retrieval filter.")
    corpus_id: str = Field(
        default="",
        description=(
            "Stable retrieval scope (Django CourseCorpus.corpus_id), resolved "
            "server-side from course_id. This is what scopes vector retrieval. "
            "Deliberately EXCLUDED from context_hash() — see context_hash()."
        ),
    )
    mastery_level: Literal["Novice", "Intermediate", "Expert"] = Field(
        ..., description="Overall mastery tier from the placement test"
    )
    composition_mode: Literal["visual_heavy", "text_heavy", "balanced"] = Field(
        default="balanced", description="Slide composition style preference"
    )
    language_proficiency: Literal["Elementary", "Intermediate", "Advanced", "Native"] = Field(
        default="Intermediate", description="English language proficiency"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Topic strings the student is strong in",
    )
    weaknesses: list[str] = Field(
        default_factory=list,
        description="Topic strings the student is weak in",
    )
    strength_concept_ids: list[str] = Field(
        default_factory=list,
        description="Django Concept.id values the student is strong in (authoritative for personalization).",
    )
    weak_concept_ids: list[str] = Field(
        default_factory=list,
        description="Django Concept.id values the student is weak in (authoritative for personalization).",
    )
    topic_performance: dict[str, float] = Field(
        default_factory=dict,
        description="Topic → score mapping (0.0–1.0)",
    )
    incorrectly_answered: list[dict] = Field(
        default_factory=list,
        description="List of dicts with keys: question, chosen_option, correct_option",
    )
    use_synthetic_context: bool = Field(
        default=False,
        description="When True, generate synthetic strengths/weaknesses for testing",
    )
    course_intent: str = Field(
        default="",
        description="Human-readable course goal, e.g. 'Introduction to Python for beginners'. "
                    "If empty, auto-inferred from book titles and topic cluster names.",
    )

    def context_hash(self) -> str:
        """SHA-256 hash of the fields that trigger plan regeneration.

        Only mastery_level, sorted weaknesses, and sorted strengths are
        included.  Minor changes (e.g. one new correct answer) do not
        change this hash.

        ``corpus_id`` is intentionally NOT part of this hash. The corpus is a
        deterministic, immutable property of the course (one corpus per course),
        not a personalization signal — folding it in would change every existing
        plan's hash and force a needless regeneration of pathways that should
        stay byte-identical after the corpus backfill. Cache keys remain
        (student_id, course_id); the resolved corpus_id only scopes *where*
        chunks are read from, not *whether* a plan must be rebuilt.
        """
        payload = json.dumps(
            {
                "mastery_level": self.mastery_level,
                "weaknesses": sorted(self.weaknesses),
                "strengths": sorted(self.strengths),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


# ── Chunk-level models ───────────────────────────────────────────


class CourseChunk(BaseModel):
    """A single chunk retrieved from ChromaDB with its full metadata."""

    chunk_id: str
    raw_text: str
    topic: str
    difficulty: str
    is_definitional: bool
    depends_on: list[str] = Field(default_factory=list)
    summary: str
    book: str
    course: str
    concept_id: str = ""
    page_start: int
    page_end: int
    chunk_index: int


# ── Section-level models ─────────────────────────────────────────


class DiscoveredSection(BaseModel):
    """A pedagogical section discovered from chunk metadata."""

    section_id: str = Field(..., description="Stable identifier for this section")
    canonical_topic: str = Field(
        ..., description="Normalised topic name (e.g. 'while loops')"
    )
    display_title: str = Field(
        default="", description="LLM-assigned human-readable title"
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="Ordered chunk IDs belonging to this section",
    )
    difficulty_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Count of chunks per difficulty tier",
    )
    has_definitional_chunks: bool = Field(
        default=False,
        description="True if at least one chunk is definitional",
    )
    prerequisite_sections: list[str] = Field(
        default_factory=list,
        description="section_ids that must come before this section",
    )


# ── LLM Curriculum Response ──────────────────────────────────────


class LLMCurriculumSession(BaseModel):
    """One session as defined by the LLM curriculum designer.

    Used to parse and validate the JSON returned by the curriculum
    design LLM call before chunks are retrieved from ChromaDB.
    """

    session_number: int = Field(..., description="1-based session index")
    session_title: str = Field(
        ..., description="Pedagogically clear session title (3-7 words)"
    )
    topics: list[str] = Field(
        ..., description="Topic strings from the ChromaDB topic list"
    )
    difficulty: str = Field(
        default="beginner",
        description="Overall difficulty tier: beginner, intermediate, expert",
    )


# ── Session-level models ─────────────────────────────────────────


class SessionChunk(BaseModel):
    """A chunk assigned to a session — this is what downstream consumers receive."""

    chunk_id: str
    raw_text: str
    concept_id: str = ""  # provenance: the concept this chunk teaches


class Session(BaseModel):
    """A single learning session in the pathway."""

    session_number: int
    session_title: str = Field(
        ..., description="Human-readable, e.g. 'Introduction to While Loops'"
    )
    chunks: list[SessionChunk]
    topics_covered: list[str] = Field(default_factory=list)
    # Provenance: which concepts (and therefore CLOs) this session teaches,
    # carried from the corpus chunks it was built from. Makes any slide traceable
    # back to a concept and a CLO.
    concept_ids: list[str] = Field(default_factory=list)
    clo_codes: list[str] = Field(default_factory=list)
    estimated_token_count: int = 0
    book: str = ""
    page_range_start: int = 0
    page_range_end: int = 0


class SessionPlan(BaseModel):
    """Complete personalised learning pathway for one student + course."""

    student_id: str
    course_id: str
    sessions: list[Session]
    total_sessions: int = 0
    total_chunks: int = 0
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    student_context_hash: str = ""
    # Versioning + determinism provenance.
    plan_version: int = 1
    is_current: bool = True
    raw_proposal_hash: str = ""  # hash of the stored raw LLM proposal it was resolved from


# ── API contracts ─────────────────────────────────────────────────


class PathwayRequest(BaseModel):
    """POST /pathway/generate request body."""

    student_context: StudentContext
    course_id: str


class PathwayResponse(BaseModel):
    """POST /pathway/generate response body."""

    plan: SessionPlan
    cached: bool = False
