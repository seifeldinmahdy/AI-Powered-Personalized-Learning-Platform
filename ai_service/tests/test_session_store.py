"""
test_session_store.py — Unit & Validation Tests for SharedSessionStore.

Tests:
    Unit       — CRUD operations, singleton pattern, thread safety.
    Validation — Pydantic schema constraints on UnifiedStudentContext.
"""

import sys
import os
import threading
import time
import pytest

# ── Path setup: allow import from ai_service root ────────────────────
_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

from pydantic import ValidationError
from schemas.student_context import (
    UnifiedStudentContext,
    StudentProfileState,
    LiveSessionState,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_profile(**kwargs) -> StudentProfileState:
    return StudentProfileState(**kwargs)


def _make_live(**kwargs) -> LiveSessionState:
    return LiveSessionState(**kwargs)


def _fresh_store():
    """Return a brand-new SharedSessionStore instance with an empty in-memory dict.

    We reset the singleton state between tests so tests are fully isolated.
    """
    from services.session_store import SharedSessionStore
    # Reset the singleton so each test gets a clean slate.
    SharedSessionStore._instance = None
    store = SharedSessionStore()
    return store


# ═════════════════════════════════════════════════════════════════════
# UNIT TESTS — SharedSessionStore
# ═════════════════════════════════════════════════════════════════════


class TestSessionStoreCRUD:
    """Basic create / read / update / delete operations."""

    def test_create_returns_unified_context(self):
        store = _fresh_store()
        profile = _make_profile()
        ctx = store.create_session("s1", profile=profile)
        assert isinstance(ctx, UnifiedStudentContext)
        assert ctx.live.session_id == "s1"

    def test_get_returns_none_for_unknown_session(self):
        store = _fresh_store()
        result = store.get_session("does_not_exist")
        assert result is None

    def test_get_returns_stored_session(self):
        store = _fresh_store()
        profile = _make_profile(student_id="stu42", course_id="cs101")
        store.create_session("s2", profile=profile)
        ctx = store.get_session("s2")
        assert ctx is not None
        assert ctx.profile.student_id == "stu42"

    def test_update_live_kwargs(self):
        store = _fresh_store()
        store.create_session("s3", profile=_make_profile())
        store.update_session("s3", live_kwargs={"current_topic": "Recursion"})
        ctx = store.get_session("s3")
        assert ctx.live.current_topic == "Recursion"

    def test_update_profile_kwargs(self):
        store = _fresh_store()
        store.create_session("s4", profile=_make_profile())
        store.update_session("s4", profile_kwargs={"mastery_level": "Expert"})
        ctx = store.get_session("s4")
        assert ctx.profile.mastery_level == "Expert"

    def test_update_raises_key_error_for_missing_session(self):
        store = _fresh_store()
        with pytest.raises(KeyError):
            store.update_session("ghost", live_kwargs={"current_topic": "X"})

    def test_delete_returns_true_for_existing_session(self):
        store = _fresh_store()
        store.create_session("s5", profile=_make_profile())
        result = store.delete_session("s5")
        assert result is True

    def test_delete_returns_false_for_missing_session(self):
        store = _fresh_store()
        result = store.delete_session("never_created")
        assert result is False

    def test_delete_removes_session(self):
        store = _fresh_store()
        store.create_session("s6", profile=_make_profile())
        store.delete_session("s6")
        assert store.get_session("s6") is None

    def test_update_sets_last_updated_at(self):
        store = _fresh_store()
        store.create_session("s7", profile=_make_profile())
        before = time.time()
        store.update_session("s7", live_kwargs={"current_topic": "Loops"})
        after = time.time()
        ctx = store.get_session("s7")
        assert before <= ctx.live.last_updated_at <= after


class TestSessionStoreBuildContextString:
    """Validate build_context_string output format and content."""

    def test_returns_empty_string_for_missing_session(self):
        store = _fresh_store()
        result = store.build_context_string("nonexistent")
        assert result == ""

    def test_contains_topic_field(self):
        store = _fresh_store()
        store.create_session("ctx1", profile=_make_profile())
        store.update_session("ctx1", live_kwargs={"current_topic": "For Loops"})
        ctx_str = store.build_context_string("ctx1")
        assert "topic:For Loops" in ctx_str

    def test_contains_all_expected_keys(self):
        store = _fresh_store()
        store.create_session("ctx2", profile=_make_profile())
        ctx_str = store.build_context_string("ctx2")
        for key in ("topic:", "prev:", "ability:", "emotion:", "pace:", "slides:"):
            assert key in ctx_str, f"Missing key '{key}' in context string: {ctx_str!r}"

    def test_pace_label_slow_when_modifier_negative(self):
        store = _fresh_store()
        store.create_session("ctx3", profile=_make_profile())
        store.update_session("ctx3", live_kwargs={"pace_modifier": -10})
        ctx_str = store.build_context_string("ctx3")
        assert "pace:slow" in ctx_str

    def test_pace_label_fast_when_modifier_positive(self):
        store = _fresh_store()
        store.create_session("ctx4", profile=_make_profile())
        store.update_session("ctx4", live_kwargs={"pace_modifier": 10})
        ctx_str = store.build_context_string("ctx4")
        assert "pace:fast" in ctx_str

    def test_pace_label_normal_when_modifier_zero(self):
        store = _fresh_store()
        store.create_session("ctx5", profile=_make_profile())
        ctx_str = store.build_context_string("ctx5")
        assert "pace:normal" in ctx_str


class TestSessionStoreSingleton:
    """Singleton pattern and thread safety."""

    def test_two_calls_return_same_object(self):
        from services.session_store import SharedSessionStore
        # Reset to get a consistent baseline
        SharedSessionStore._instance = None
        store_a = SharedSessionStore()
        store_b = SharedSessionStore()
        assert store_a is store_b

    def test_get_session_store_returns_singleton(self):
        from services.session_store import get_session_store, SharedSessionStore
        SharedSessionStore._instance = None
        s1 = get_session_store()
        s2 = get_session_store()
        assert s1 is s2

    def test_concurrent_writes_do_not_corrupt_state(self):
        """10 threads each write to distinct sessions; all reads succeed."""
        store = _fresh_store()
        errors = []

        def _write(n):
            try:
                sid = f"thread_session_{n}"
                store.create_session(sid, profile=_make_profile(student_id=str(n)))
                store.update_session(sid, live_kwargs={"current_topic": f"Topic {n}"})
                ctx = store.get_session(sid)
                assert ctx.live.current_topic == f"Topic {n}"
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"


# ═════════════════════════════════════════════════════════════════════
# VALIDATION TESTS — Pydantic schema constraints
# ═════════════════════════════════════════════════════════════════════


class TestStudentProfileStateValidation:
    """Test Pydantic constraints on StudentProfileState."""

    def test_extra_fields_are_forbidden(self):
        with pytest.raises(ValidationError):
            StudentProfileState(unknown_field="bad")

    def test_mastery_level_literal(self):
        with pytest.raises(ValidationError):
            StudentProfileState(mastery_level="Genius")

    def test_valid_mastery_levels(self):
        for level in ("Novice", "Intermediate", "Expert"):
            p = StudentProfileState(mastery_level=level)
            assert p.mastery_level == level

    def test_composition_mode_literal(self):
        with pytest.raises(ValidationError):
            StudentProfileState(composition_mode="random")

    def test_language_proficiency_literal(self):
        with pytest.raises(ValidationError):
            StudentProfileState(language_proficiency="Fluent")

    def test_is_fully_hydrated_false_by_default(self):
        p = StudentProfileState()
        assert p.is_fully_hydrated() is False

    def test_is_fully_hydrated_true_when_populated(self):
        p = StudentProfileState(
            student_id="s1",
            course_id="c1",
            mastery_level="Intermediate",
        )
        assert p.is_fully_hydrated() is True


class TestLiveSessionStateValidation:
    """Test Pydantic constraints on LiveSessionState."""

    def test_extra_fields_are_forbidden(self):
        with pytest.raises(ValidationError):
            LiveSessionState(mystery_field=True)

    def test_pace_modifier_lower_bound(self):
        with pytest.raises(ValidationError):
            LiveSessionState(pace_modifier=-51)

    def test_pace_modifier_upper_bound(self):
        with pytest.raises(ValidationError):
            LiveSessionState(pace_modifier=51)

    def test_pace_modifier_boundary_values_accepted(self):
        l1 = LiveSessionState(pace_modifier=-50)
        l2 = LiveSessionState(pace_modifier=50)
        assert l1.pace_modifier == -50
        assert l2.pace_modifier == 50

    def test_tutor_transcript_cap(self):
        """Validator must truncate transcript to the last 10 entries."""
        entries = [{"role": "tutor", "text": f"chunk {i}"} for i in range(15)]
        live = LiveSessionState(tutor_transcript=entries)
        assert len(live.tutor_transcript) == 10
        # Last 10 should be chunks 5–14
        assert live.tutor_transcript[0]["text"] == "chunk 5"

    def test_default_last_updated_at_is_recent(self):
        before = time.time()
        live = LiveSessionState()
        after = time.time()
        assert before <= live.last_updated_at <= after


class TestUnifiedStudentContextSerialization:
    """JSON round-trip and conversion helpers."""

    def test_json_round_trip(self):
        profile = _make_profile(student_id="rt1", course_id="c42")
        live = _make_live(current_topic="Recursion")
        ctx = UnifiedStudentContext(profile=profile, live=live)

        json_str = ctx.model_dump_json()
        restored = UnifiedStudentContext.model_validate_json(json_str)

        assert restored.profile.student_id == "rt1"
        assert restored.live.current_topic == "Recursion"

    def test_to_slides_prompt_dict_keys(self):
        profile = _make_profile(
            mastery_level="Intermediate",
            composition_mode="visual_heavy",
            language_proficiency="Advanced",
        )
        live = _make_live()
        ctx = UnifiedStudentContext(profile=profile, live=live)
        d = ctx.to_slides_prompt_dict()
        assert "mastery_level" in d
        assert "composition_mode" in d
        assert "language_proficiency" in d
        assert d["mastery_level"] == "Intermediate"
