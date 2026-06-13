"""Tutor grounding tests.

Acceptance:
- The tutor prompt contains the RAW retrieved source passages (primary text +
  citations), not a pre-generated RAG answer.
- Graceful fallback: with no retrieved passages the tutor still answers, but the
  result is flagged ungrounded so the UI can surface "grounding unavailable".
"""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

from services import tutor_service as ts


def _make_session(sid: str) -> "ts.TutorSession":
    s = ts.TutorSession(session_id=sid, topics=[{"name": "Loops", "subtopics": ["for loops"]}])
    s.status = "lecturing"
    ts._sessions[sid] = s
    return s


@pytest.fixture()
def captured(monkeypatch):
    cap = {}

    async def fake_call(system_prompt, user_prompt, **kwargs):
        cap["system"] = system_prompt
        cap["user"] = user_prompt
        return "What do you think happens on each iteration?"

    async def fake_summary(session, qa_text):
        return None

    monkeypatch.setattr(ts, "_call_ollama", fake_call)
    monkeypatch.setattr(ts, "_update_summary", fake_summary)
    monkeypatch.setattr(ts, "_sync_to_shared_store", lambda s: None)
    yield cap
    ts._sessions.clear()


PASSAGES = [
    {
        "text": "A for loop repeats a block of code once per item in a sequence.",
        "book": "ThinkPython", "page_start": 10, "page_end": 11,
        "topic": "loops", "relevance_score": 0.91,
    },
    {
        "text": "The loop variable takes each value in turn.",
        "book": "ThinkPython", "page_start": 11, "page_end": 12,
        "topic": "loops", "relevance_score": 0.84,
    },
]


@pytest.mark.asyncio
async def test_tutor_prompt_contains_raw_passages_not_pregenerated_answer(captured):
    _make_session("g1")
    res = await ts.answer_question(
        "g1", "What is a for loop?",
        intent="On-Topic Question", grounding_passages=PASSAGES,
    )

    prompt = captured["user"]
    # Primary source text is present verbatim — not a paraphrased RAG answer.
    assert "RETRIEVED SOURCE PASSAGES" in prompt
    assert "A for loop repeats a block of code once per item in a sequence." in prompt
    assert "ThinkPython p.10-11" in prompt
    # The grounding skill is active and the answer is flagged grounded.
    assert "SOURCE_GROUNDING" in res["active_skills"]
    assert res["grounded"] is True


@pytest.mark.asyncio
async def test_ungrounded_fallback_still_answers(captured):
    _make_session("g2")
    res = await ts.answer_question(
        "g2", "What is a for loop?",
        intent="On-Topic Question", grounding_passages=None,
    )

    prompt = captured["user"]
    assert "RETRIEVED SOURCE PASSAGES" not in prompt
    assert "SOURCE_GROUNDING" not in res["active_skills"]
    assert res["grounded"] is False
    assert res["answer"]  # graceful: a plain tutor answer is still produced


def test_format_grounding_block_empty_is_blank():
    assert ts._format_grounding_block(None) == ""
    assert ts._format_grounding_block([]) == ""


def test_format_grounding_block_lists_citations():
    block = ts._format_grounding_block(PASSAGES)
    assert "[1] ThinkPython p.10-11 (loops):" in block
    assert "[2] ThinkPython p.11-12 (loops):" in block
    assert "The loop variable takes each value in turn." in block
