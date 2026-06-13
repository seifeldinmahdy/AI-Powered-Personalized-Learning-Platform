"""
test_intent_context.py — intent classification draws its context from the
SharedSessionStore (real emotion / pace / topic) instead of a client-built
hardcoded string.

Proves the acceptance criterion: an Emotional-State / Pace-Related utterance is
classified with the real current emotion/pace read from a seeded store entry.
"""

import os
import sys

# ── Path setup: allow import from ai_service root ────────────────────
_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

from schemas.student_context import StudentProfileState
from schemas.intent import IntentRequest


def _seed_store(session_id="sX"):
    """Reset the singleton and seed one session with real live signals."""
    from services.session_store import SharedSessionStore, get_session_store

    SharedSessionStore._instance = None
    store = get_session_store()
    profile = StudentProfileState(
        student_id="1", course_id="cs101", mastery_level="Intermediate",
        student_profile_summary="Intermediate learner; strong in loops.",
    )
    store.create_session(session_id, profile=profile)
    # Real live state the tutor would have written during the session.
    store.update_session(
        session_id,
        live_kwargs={
            "current_topic": "Recursion",
            "fused_emotion": "frustrated",
            "pace_modifier": 20,  # > 0 → "fast"
        },
    )
    return store


def test_build_context_string_reflects_real_emotion_and_pace():
    """The store-derived context string carries the real emotion/pace/topic,
    not 'emotion:neutral | pace:normal'."""
    store = _seed_store()
    ctx = store.build_context_string("sX")

    assert "emotion:frustrated" in ctx
    assert "pace:fast" in ctx
    assert "topic:Recursion" in ctx
    assert "emotion:neutral" not in ctx
    assert "pace:normal" not in ctx


@pytest.mark.asyncio
async def test_classify_endpoint_autofills_context_from_store(monkeypatch):
    """When the request sends only a session_id (empty session_context), the
    /intent/classify endpoint feeds the classifier the store-derived context."""
    _seed_store("sX")

    import routers.intent as intent_router

    captured = {}

    class _FakeService:
        classifier = object()
        model_path = "fake"

        def classify(self, student_input, session_context, split_compound=True,
                     confidence_threshold=0.65):
            captured["session_context"] = session_context
            captured["student_input"] = student_input
            prediction = {
                "text": student_input,
                "intent_name": "Emotional-State",
                "label_id": 2,
                "confidence": 0.95,
                "probabilities": {"Emotional-State": 0.95},
            }
            return [prediction], 0.01

    monkeypatch.setattr(intent_router, "get_intent_service", lambda: _FakeService())

    req = IntentRequest(student_input="I am so confused", session_id="sX")
    resp = await intent_router.classify_intent(req)

    # The classifier received the REAL store context, not a hardcoded string.
    assert "emotion:frustrated" in captured["session_context"]
    assert "pace:fast" in captured["session_context"]
    assert resp.predictions[0].intent_name == "Emotional-State"


@pytest.mark.asyncio
async def test_classify_endpoint_graceful_when_session_absent(monkeypatch):
    """No store entry for the session → empty context, but classification still
    runs (tutor still answers)."""
    from services.session_store import SharedSessionStore
    SharedSessionStore._instance = None  # empty store

    import routers.intent as intent_router

    captured = {}

    class _FakeService:
        classifier = object()
        model_path = "fake"

        def classify(self, student_input, session_context, split_compound=True,
                     confidence_threshold=0.65):
            captured["session_context"] = session_context
            return ([{
                "text": student_input,
                "intent_name": "On-Topic Question",
                "label_id": 0,
                "confidence": 0.8,
                "probabilities": {"On-Topic Question": 0.8},
            }], 0.01)

    monkeypatch.setattr(intent_router, "get_intent_service", lambda: _FakeService())

    req = IntentRequest(student_input="what is a list?", session_id="ghost")
    resp = await intent_router.classify_intent(req)

    assert captured["session_context"] == ""  # graceful default
    assert resp.success is True
