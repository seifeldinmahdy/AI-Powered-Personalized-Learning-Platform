"""Batch 5 — CLO/concept taxonomy unification tests.

Covers:
- Backward-designed generation: every CLO concept is probed by >=1 question.
- Placement is concept-keyed: seeds concept_mastery, concept-label
  strengths/weaknesses, derived mastery_level, NO topic_performance.
- mastery_level derivation changes as concept mastery changes.
- §2.3 checkpoint endpoint is neutered: no topic_performance source-of-truth.
"""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

from services.mastery import derive_mastery_level


# ── derive_mastery_level (acceptance: level changes as mastery changes) ──

def test_derive_mastery_level_thresholds_and_change():
    assert derive_mastery_level({}) == "Novice"
    cm = {"1": {"score": 0.30, "evidence": 1}}
    assert derive_mastery_level(cm) == "Novice"
    # Apply an update that lifts mastery across the Intermediate threshold.
    cm["1"] = {"score": 0.60, "evidence": 2}
    assert derive_mastery_level(cm) == "Intermediate"
    cm["2"] = {"score": 0.90, "evidence": 3}
    assert derive_mastery_level(cm) == "Expert"  # mean (0.6+0.9)/2 = 0.75


def test_derive_ignores_zero_evidence_and_scopes_to_course():
    cm = {"1": {"score": 0.9, "evidence": 0}, "2": {"score": 0.8, "evidence": 1}}
    assert derive_mastery_level(cm) == "Expert"  # only concept 2 has evidence
    # Scope restricts which concepts count.
    assert derive_mastery_level(cm, course_concept_ids={"99"}) == "Novice"


# ── Backward-designed generation coverage ──

@pytest.mark.asyncio
async def test_generate_clo_questions_covers_every_concept(monkeypatch):
    import services.assessment_service as asvc

    # LLM returns a question for only ONE of the two concepts in the group.
    class _FakeClient:
        def chat_json(self, messages, **kwargs):
            return {"questions": [{
                "question": "What is a loop?",
                "options": ["a", "b", "c", "d"],
                "correct_answer": "a",
                "concept_id": "c10",
                "topic": "loops",
            }]}

    monkeypatch.setattr(asvc, "_get_ollama_client", lambda: _FakeClient())

    plan = [{
        "name": "CLO1", "description": "Control flow",
        "concepts": [{"id": "c10", "label": "loops"}, {"id": "c11", "label": "recursion"}],
    }]
    result = await asvc.generate_clo_questions("Python", plan, total_questions=4)

    covered = {q["concept_id"] for cat in result for q in cat["questions"]}
    # Coverage guarantee: BOTH concepts probed, even though the LLM skipped c11.
    assert covered == {"c10", "c11"}


# ── Concept-keyed placement ──

class _FakeStore:
    def __init__(self):
        self.saved = None

    def save(self, student_id, course_id, context):
        self.saved = context


@pytest.mark.asyncio
async def test_submit_placement_is_concept_keyed(monkeypatch):
    import routers.assessments as ra
    import services.mastery as mastery

    posted = []

    async def fake_fetch(student_id):
        return {}

    async def fake_post(student_id, events):
        posted.extend(events)

    monkeypatch.setattr(mastery, "fetch_concept_mastery", fake_fetch)
    monkeypatch.setattr(mastery, "post_mastery_events", fake_post)
    # submit_placement imports these names inside the function, so also patch the
    # module-local references it pulls in.
    store = _FakeStore()
    monkeypatch.setattr(ra, "get_student_context_store", lambda: store)

    req = ra.SubmitPlacementRequest(
        student_id="7", course_id="3", course_title="Python", enrollment_id=1,
        answers=[
            ra.AnswerItem(question_id=1, question="q1", topic="Loops", concept_id="c10",
                          chosen_option="a", correct_option="a", is_correct=True),
            ra.AnswerItem(question_id=2, question="q2", topic="Loops", concept_id="c10",
                          chosen_option="b", correct_option="a", is_correct=True),
            ra.AnswerItem(question_id=3, question="q3", topic="Recursion", concept_id="c11",
                          chosen_option="b", correct_option="a", is_correct=False),
        ],
    )
    resp = await ra.submit_placement(req)

    # Mastery is recorded via the single writer as concept-keyed 'assessment' events.
    by_concept = {e["concept_id"]: e for e in posted}
    assert "c10" in by_concept and "c11" in by_concept
    assert by_concept["c10"]["source"] == "assessment"
    assert by_concept["c10"]["outcome"] > by_concept["c11"]["outcome"]  # loops correct > recursion wrong
    # strengths/weaknesses are concept LABELS, not topic strings from chunks.
    assert "Loops" in resp.strengths
    assert "Recursion" in resp.weaknesses
    # No parallel topic signal is produced.
    assert resp.topic_performance == {}
    saved = store.saved
    assert saved.profile.topic_performance == {}
    assert saved.profile.strength_concept_ids == ["c10"]
    assert saved.profile.weak_concept_ids == ["c11"]
    # mastery_level is derived from the seeded concept mastery.
    assert resp.mastery_level in ("Novice", "Intermediate", "Expert")


# ── §2.3 checkpoint → single writer (no parallel topic_performance) ──

@pytest.mark.asyncio
async def test_update_performance_records_checkpoint_events(monkeypatch):
    import routers.student_context as sc
    import services.mastery as mastery
    from schemas.student_context import (
        UnifiedStudentContext, StudentProfileState, LiveSessionState,
    )

    ctx = UnifiedStudentContext(
        profile=StudentProfileState(
            student_id="7", course_id="3", strengths=["Loops"], weaknesses=["Recursion"],
        ),
        live=LiveSessionState(),
    )

    class _Store:
        def load(self, s, c):
            return ctx

    monkeypatch.setattr(sc, "get_student_context_store", lambda: _Store())

    posted = []

    async def fake_post(student_id, events):
        posted.extend(events)

    monkeypatch.setattr(mastery, "post_mastery_events", fake_post)

    body = sc.TopicPerformanceUpdate(
        session_scores={"loops": 0.9}, session_number=1, session_topic="Loops",
    )
    resp = await sc.update_performance("7", "3", body)

    # Recorded as a checkpoint event (topic+course for server-side mapping);
    # no parallel topic_performance signal is returned/maintained.
    assert len(posted) == 1
    assert posted[0]["source"] == "checkpoint"
    assert posted[0]["topic"] == "loops" and posted[0]["course_id"] == "3"
    assert resp.updated_topic_performance == {}
