"""Batch: pathway determinism, CLO coverage, versioning, provenance.

Uses a fake reader + no LLM (resolution falls back to the deterministic
alphabetical grouping), so the whole pipeline is deterministic and offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_RAG = Path(__file__).resolve().parent.parent.parent / "rag_pipeline"
if str(_RAG) not in sys.path:
    sys.path.insert(0, str(_RAG))

from pathway.generator import PathwayGenerator, CoverageError
from pathway.config import PathwaySettings
from pathway.personalization.personalizer import Personalizer
from pathway.session.grouper import SessionGrouper
from pathway.models.synthetic import SyntheticContextGenerator
from pathway.storage.plan_store import PlanStore
from pathway.models.schemas import CourseChunk, StudentContext


def _chunk(idx, topic, concept_id, difficulty="beginner", is_def=False):
    return CourseChunk(
        chunk_id=f"ch_{idx}", raw_text=f"This is chunk {idx} about {topic}. " * 12,
        topic=topic, difficulty=difficulty, is_definitional=is_def, depends_on=[],
        summary=f"covers {topic}", book="bookA", course="3", concept_id=concept_id,
        page_start=idx, page_end=idx + 1, chunk_index=idx,
    )


CHUNKS = [
    _chunk(0, "loops", "c1", "beginner", is_def=True),
    _chunk(1, "loops", "c1", "expert"),
    _chunk(2, "recursion", "c2", "expert", is_def=True),
    _chunk(3, "recursion", "c2", "beginner"),
    _chunk(4, "strings", "c3", "beginner", is_def=True),
]


class _FakeReader:
    def __init__(self, chunks):
        self._chunks = chunks

    def get_all_chunks(self, scope):
        return list(self._chunks)

    def get_chunks_for_concept(self, scope, concept_id):
        return [c for c in self._chunks if c.concept_id == str(concept_id)]

    def get_topics_by_difficulty(self, scope, difficulty):
        return sorted({c.topic for c in self._chunks if c.difficulty == difficulty})


def _make_generator(tmp_path, chunks=CHUNKS):
    settings = PathwaySettings()
    gen = PathwayGenerator.__new__(PathwayGenerator)
    gen._settings = settings
    gen._reader = _FakeReader(chunks)
    gen._store = PlanStore(db_path=str(tmp_path / "plans.db"))
    gen._llm = None
    gen._personalizer = Personalizer()
    gen._grouper = SessionGrouper(max_sessions=settings.max_sessions,
                                  target_sessions=settings.target_session_count)
    gen._synthetic_gen = SyntheticContextGenerator()
    return gen


def _ctx(mastery="Novice", **kw):
    return StudentContext(student_id="s1", course_id="3", corpus_id="corpusA",
                          mastery_level=mastery, **kw)


CLOS = [
    {"concept_id": "c1", "label": "loops", "clo_code": "CLO1"},
    {"concept_id": "c2", "label": "recursion", "clo_code": "CLO1"},
    {"concept_id": "c3", "label": "strings", "clo_code": "CLO2"},
]


def _content(plan):
    """Plan content excluding volatile metadata (timestamp, version)."""
    return plan.model_dump(exclude={"generated_at", "plan_version", "is_current"})


# ── Determinism ──────────────────────────────────────────────────

def test_two_generations_are_byte_identical(tmp_path):
    g1 = _make_generator(tmp_path / "a")
    g2 = _make_generator(tmp_path / "b")
    p1 = g1.generate(_ctx(), clo_concepts=CLOS, force_regenerate=True).plan
    p2 = g2.generate(_ctx(), clo_concepts=CLOS, force_regenerate=True).plan
    assert _content(p1) == _content(p2)


# ── CLO coverage guarantee ───────────────────────────────────────

def test_every_clo_concept_is_covered(tmp_path):
    gen = _make_generator(tmp_path)
    plan = gen.generate(_ctx(), clo_concepts=CLOS, force_regenerate=True).plan
    covered = set()
    for s in plan.sessions:
        covered.update(s.concept_ids)
    assert {"c1", "c2", "c3"} <= covered


def test_uncovered_clo_concept_rejected(tmp_path):
    gen = _make_generator(tmp_path)
    clos = CLOS + [{"concept_id": "c99", "label": "monads", "clo_code": "CLO3"}]
    with pytest.raises(CoverageError) as exc:
        gen.generate(_ctx(), clo_concepts=clos, force_regenerate=True)
    assert "monads" in str(exc.value) and "c99" in str(exc.value)


# ── Provenance ───────────────────────────────────────────────────

def test_provenance_concepts_and_clos_recorded(tmp_path):
    gen = _make_generator(tmp_path)
    plan = gen.generate(_ctx(), clo_concepts=CLOS, force_regenerate=True).plan
    # every session that has concepts also lists the CLOs they map to
    for s in plan.sessions:
        for cid in s.concept_ids:
            if cid in {"c1", "c2"}:
                assert "CLO1" in s.clo_codes
            if cid == "c3":
                assert "CLO2" in s.clo_codes


# ── Versioning ───────────────────────────────────────────────────

def test_same_context_no_new_version(tmp_path):
    gen = _make_generator(tmp_path)
    gen.generate(_ctx(), clo_concepts=CLOS).plan          # v1
    r2 = gen.generate(_ctx(), clo_concepts=CLOS)          # unchanged → current
    assert r2.cached is True
    assert len(gen._store.list_versions("s1", "3")) == 1


def test_changed_context_creates_retained_new_version(tmp_path):
    gen = _make_generator(tmp_path)
    p1 = gen.generate(_ctx(mastery="Novice"), clo_concepts=CLOS).plan
    assert p1.plan_version == 1
    # Changing mastery changes the context hash → new version.
    p2 = gen.generate(_ctx(mastery="Expert"), clo_concepts=CLOS).plan
    assert p2.plan_version == 2
    versions = gen._store.list_versions("s1", "3")
    assert len(versions) == 2
    # old version retained + retrievable; current flag flipped to v2
    assert gen._store.load_version("s1", "3", 1) is not None
    assert gen._store.load_current("s1", "3").plan_version == 2
    assert [v for v in versions if v["is_current"]][0]["plan_version"] == 2


# ── Strength-compression keeps a concept's last chunk (condition 5) ──

# ── Permissions: generation is service-key gated (students get 403) ──

def test_generation_requires_service_key(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `import router`
    import router
    from fastapi import HTTPException

    monkeypatch.setenv("INTERNAL_SERVICE_KEY", "secret")
    # No key (a student's browser) → 403, never a silent regeneration.
    with pytest.raises(HTTPException) as e:
        router._require_service_key(None)
    assert e.value.status_code == 403
    # Wrong key → 403.
    with pytest.raises(HTTPException):
        router._require_service_key("nope")
    # Correct internal key → allowed.
    router._require_service_key("secret")


def test_strength_compression_keeps_last_chunk_per_concept():
    # All of concept c2's chunks are non-definitional + beginner; an Expert
    # treating c2 as a strength compresses to expert/definitional only — c2 must
    # still retain at least one chunk.
    chunks = [
        _chunk(0, "loops", "c1", "expert", is_def=True),
        _chunk(1, "recursion", "c2", "beginner"),
        _chunk(2, "recursion", "c2", "beginner"),
    ]
    selected = Personalizer._select_chunks_for_strength(chunks, strength_diffs=["expert"])
    kept_concepts = {c.concept_id for c in selected}
    assert "c2" in kept_concepts  # last chunk of c2 not dropped
