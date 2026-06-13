"""
test_slides_personalization.py — slide-generation personalization is derived
server-side from the student's STORED context, not from client-sent literals.

Proves the acceptance criterion: a student whose placement yields
Intermediate/Expert drives different slide-generation inputs — the value that
reaches the generator equals the stored profile value.
"""

import os
import sys

# ── Path setup: allow import from ai_service root ────────────────────
_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

from schemas.student_context import (
    UnifiedStudentContext,
    StudentProfileState,
    LiveSessionState,
)
from routers.slides import SlideGenerateRequest, _resolve_student_context


def _make_request(**kwargs) -> SlideGenerateRequest:
    base = dict(
        session_number=1,
        session_title="Recursion",
        topics_covered=["Recursion"],
        book="PythonLearn",
        chunks=[],
    )
    base.update(kwargs)
    return SlideGenerateRequest(**base)


def _expert_context(student_id: str, course_id: str) -> UnifiedStudentContext:
    profile = StudentProfileState(
        student_id=student_id,
        course_id=course_id,
        mastery_level="Expert",
        composition_mode="text_heavy",
        language_proficiency="Advanced",
        topic_performance={"Recursion": 0.9},
    )
    return UnifiedStudentContext(profile=profile, live=LiveSessionState())


@pytest.fixture
def seeded_store(tmp_path, monkeypatch):
    """Seed a StudentContextStore (tmp dir) with an Expert context and make it
    the process-wide singleton used by the slides resolver."""
    import services.student_context_store as scs

    store = scs.StudentContextStore(data_dir=tmp_path)
    store.save("42", "cs101", _expert_context("42", "cs101"))
    monkeypatch.setattr(scs, "_store", store)
    return store


def test_resolves_stored_context_over_defaults(seeded_store):
    """Server-side resolution loads the stored profile (Expert), ignoring the
    deprecated literal defaults (Novice / visual_heavy / Elementary)."""
    req = _make_request(student_id="42", course_id="cs101")

    resolved = _resolve_student_context(req)

    assert resolved is not None
    assert resolved.profile.mastery_level == "Expert"
    # The exact dict that reaches the slide generator must reflect the stored
    # profile, not the request defaults.
    prompt_dict = resolved.to_slides_prompt_dict()
    assert prompt_dict["mastery_level"] == "Expert"
    assert prompt_dict["composition_mode"] == "Text_Heavy"
    assert prompt_dict["language_proficiency"] == "Advanced"
    # And the request defaults are unchanged Novice/visual_heavy/Elementary,
    # proving the generator does NOT use them when a stored context exists.
    assert req.mastery_level == "Novice"
    assert req.composition_mode == "visual_heavy"


def test_intermediate_and_expert_drive_distinct_inputs(tmp_path, monkeypatch):
    """Two students with different placement results resolve to different
    generator inputs."""
    import services.student_context_store as scs

    store = scs.StudentContextStore(data_dir=tmp_path)
    # Intermediate student
    inter = StudentProfileState(
        student_id="7", course_id="cs101", mastery_level="Intermediate",
        composition_mode="balanced", language_proficiency="Intermediate",
    )
    store.save("7", "cs101", UnifiedStudentContext(profile=inter, live=LiveSessionState()))
    # Expert student
    store.save("42", "cs101", _expert_context("42", "cs101"))
    monkeypatch.setattr(scs, "_store", store)

    inter_resolved = _resolve_student_context(_make_request(student_id="7", course_id="cs101"))
    expert_resolved = _resolve_student_context(_make_request(student_id="42", course_id="cs101"))

    assert inter_resolved.profile.mastery_level == "Intermediate"
    assert expert_resolved.profile.mastery_level == "Expert"
    assert inter_resolved.profile.mastery_level != expert_resolved.profile.mastery_level


def test_explicit_student_context_takes_priority(seeded_store):
    """An explicitly-passed student_context wins over the stored one
    (back-compat path for internal callers)."""
    explicit = StudentProfileState(
        student_id="42", course_id="cs101", mastery_level="Novice",
    )
    req = _make_request(
        student_id="42", course_id="cs101",
        student_context=UnifiedStudentContext(profile=explicit, live=LiveSessionState()),
    )

    resolved = _resolve_student_context(req)
    assert resolved.profile.mastery_level == "Novice"


def test_missing_context_falls_back_to_none(seeded_store):
    """No stored context for this student → resolver returns None so the caller
    can fall back to defaults and slides still render (graceful default)."""
    req = _make_request(student_id="does_not_exist", course_id="nope")
    assert _resolve_student_context(req) is None


def test_no_identifiers_returns_none(seeded_store):
    """No student_id/course_id and no explicit context → None (graceful)."""
    req = _make_request()
    assert _resolve_student_context(req) is None
