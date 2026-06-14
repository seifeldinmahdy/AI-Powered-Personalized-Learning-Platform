"""Batch 7 — claims-based profilers: lab conservatism + durable/idempotent session."""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import services.profiler_service as ps
import services.session_event_log as sel


class _FakeClient:
    def __init__(self, payload, capture=None):
        self._payload = payload
        self._capture = capture

    def chat_json(self, messages, **kwargs):
        if self._capture is not None:
            self._capture["messages"] = messages
        return self._payload


@pytest.fixture
def captured_posts(monkeypatch):
    posts = []

    async def fake_post(student_id, claims, summary=None, summary_source=None):
        posts.append({"student_id": student_id,
                      "claims": [c.model_dump() if hasattr(c, "model_dump") else c for c in claims],
                      "summary": summary, "summary_source": summary_source})

    monkeypatch.setattr(ps, "post_profile_claims", fake_post)
    return posts


# ── Lab profiler: evidence floor ──────────────────────────────────

@pytest.mark.asyncio
async def test_lab_evidence_floor_declines(monkeypatch, captured_posts):
    lab_data = {  # no notes, all questions unasked → zero positive signal
        "cells": [{"title": "C1", "cell_type": "task", "student_notes": [],
                   "suggested_questions": [{"question": "What is a loop?", "was_asked": False}]}],
        "general_notes": [],
    }

    class _Store:
        def get_lab_notes_for_profiler(self, lab_id):
            return lab_data

    monkeypatch.setattr("services.lab_store.get_coding_lab_store", lambda: _Store())
    monkeypatch.setattr(ps, "_get_ollama_client", lambda: pytest.fail("LLM must not be called below the floor"))

    result = await ps.run_lab_profiler("7", "lab1", "3", "9")
    assert result.get("declined") is True
    assert captured_posts == []  # nothing applied


# ── Lab profiler: ignores are never interpreted ───────────────────

@pytest.mark.asyncio
async def test_lab_ignores_unasked_questions(monkeypatch, captured_posts):
    monkeypatch.setenv("OLLAMA_API_KEY", "x")
    IGNORED = "What is recursion?"
    lab_data = {
        "cells": [{
            "title": "C1", "cell_type": "task",
            "student_notes": [{"content": "I tried a for loop here.", "timestamp": "t"}],  # positive signal
            "suggested_questions": [{"question": IGNORED, "was_asked": False}],
        }],
        "general_notes": [],
    }

    class _Store:
        def get_lab_notes_for_profiler(self, lab_id):
            return lab_data

    cap = {}
    monkeypatch.setattr("services.lab_store.get_coding_lab_store", lambda: _Store())
    monkeypatch.setattr(ps, "_get_ollama_client",
                        lambda: _FakeClient({"claims": [{"field": "recommended_approach",
                                                         "value": "hands-on tasks", "confidence": 0.3}]}, cap))

    result = await ps.run_lab_profiler("7", "lab1", "3", "9")

    # The ignored question text is NEVER fed to the LLM (no inference possible).
    prompt = " ".join(m["content"] for m in cap["messages"])
    assert IGNORED not in prompt
    # And no emitted claim references the ignored question; the only place ignores
    # may be MENTIONED is a neutral_context note (never a trait).
    claims = captured_posts[0]["claims"]
    for c in claims:
        if c["field"] != "neutral_context":
            assert IGNORED.lower() not in c["value"].lower()
    assert any(c["field"] == "neutral_context" for c in claims)
    assert result["positive_signal"] >= 1


# ── Session profiler: durable + idempotent ────────────────────────

@pytest.mark.asyncio
async def test_session_consolidation_durable_and_idempotent(tmp_path, monkeypatch, captured_posts):
    monkeypatch.setenv("OLLAMA_API_KEY", "x")
    # Fresh durable log (simulates a clean process that only has the durable log).
    sel.SessionEventLog._instance = None
    log = sel.SessionEventLog(db_path=tmp_path / "ev.db")
    log.append("sess1", "slide", {"slide_index": 0, "slide_title": "Loops"})
    log.append("sess1", "emotion", {"slide_index": 0, "slide_title": "Loops", "fused_emotion": "confused"})

    monkeypatch.setattr(ps, "_get_ollama_client",
                        lambda: _FakeClient({"claims": [{"field": "engagement",
                                                         "value": "low on Loops", "confidence": 0.6}],
                                             "summary": "Goes slower on loops."}))

    # First run consolidates from the DURABLE log (no SharedSessionStore needed).
    r1 = await ps.run_session_profiler("sess1", "7", "Loops lesson")
    assert r1["claims"] == 1
    assert len(captured_posts) == 1
    assert captured_posts[0]["summary_source"] == "session"

    # Second run is idempotent: events are consumed → nothing re-applied.
    r2 = await ps.run_session_profiler("sess1", "7", "Loops lesson")
    assert r2["claims"] == 0
    # post may be called with [] (no-op) but no NEW non-empty application happened.
    nonempty = [p for p in captured_posts if p["claims"]]
    assert len(nonempty) == 1


# ── Tutor reads the flattener's empty path gracefully (new student) ──

def test_tutor_profile_context_handles_no_claims():
    from services.tutor_service import _build_profile_context, TutorSession
    s = TutorSession(session_id="s", topics=[{"name": "Loops", "subtopics": ["for"]}])

    # New student: v2 profile with zero claims must not crash any reader.
    s.student_profile_data = {"schema_version": 2, "claims": []}
    s.student_profile_summary = ""
    assert _build_profile_context(s) is None  # nothing to inject, no error

    # Summary-only still works.
    s.student_profile_summary = "Teach with examples."
    ctx = _build_profile_context(s)
    assert ctx and "Teach with examples." in ctx
