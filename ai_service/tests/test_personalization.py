"""Personalization fixes: strengths wiring + tutor concept-ID matching.

Proves adaptation by contrasting profiles where feasible:
- top_strong_concepts surfaces only real strengths (score + evidence floor);
- the tutor activates STRENGTH_TOPIC for a strong-at-X student and DIFFICULTY_TOPIC
  by concept_id even when the weak label does NOT string-match the subtopic
  (the brittleness regression);
- the problem-set prompt gains a STRONG CONCEPTS block when strengths exist;
- the lab checklist is profile-aware and the lab prompt's dead
  topics_of_difficulty/strength instructions are gone, replaced by concept targets.
"""

import os
import sys
from types import SimpleNamespace

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import services.mastery as m
import services.tutor_service as ts


# ── top_strong_concepts ──────────────────────────────────────────────────────

def test_top_strong_concepts_requires_score_and_evidence():
    cm = {
        "c1": {"score": 0.90, "evidence": 3},   # real strength
        "c2": {"score": 0.85, "evidence": 0},   # no evidence → excluded
        "c3": {"score": 0.50, "evidence": 9},   # below threshold → excluded
        "c4": {"score": 0.78, "evidence": 2},   # real strength
    }
    ids = [s["concept_id"] for s in m.top_strong_concepts(cm)]
    assert ids == ["c1", "c4"]  # sorted by score desc, evidence-floored


def test_top_strong_concepts_empty_when_none_qualify():
    cm = {"c1": {"score": 0.5, "evidence": 0}}  # 0.5 prior, no evidence
    assert m.top_strong_concepts(cm) == []


# ── tutor: concept-ID skill matching ─────────────────────────────────────────

def _sess(weak=None, strong=None, profile=None, subtopic="", topic=""):
    return SimpleNamespace(
        weak_concepts=weak or [], strong_concepts=strong or [],
        student_profile_data=profile or {}, current_subtopic=subtopic, current_topic=topic,
    )


def test_strength_topic_activates_for_strong_student_only():
    strong_sess = _sess(strong=[{"concept_id": "42", "label": "recursion"}], subtopic="loops")
    avg_sess = _sess(strong=[], subtopic="loops")
    assert "STRENGTH_TOPIC" in ts._competence_and_style_skills(strong_sess, "42")
    assert "STRENGTH_TOPIC" not in ts._competence_and_style_skills(avg_sess, "42")


def test_difficulty_activates_by_concept_id_despite_label_mismatch():
    # The weak concept's LABEL ("Big-O notation") does NOT overlap the subtopic
    # string ("performance") — old string matching would silently fail. The
    # authoritative concept_id match fixes it.
    s = _sess(weak=[{"concept_id": "7", "label": "Big-O notation"}],
              subtopic="performance", topic="algorithm analysis")
    assert "DIFFICULTY_TOPIC" in ts._competence_and_style_skills(s, "7")


def test_difficulty_does_not_overfire_for_unrelated_concept():
    s = _sess(weak=[{"concept_id": "7", "label": "Big-O"}], subtopic="loops")
    assert "DIFFICULTY_TOPIC" not in ts._competence_and_style_skills(s, "999")


def test_label_overlap_fallback_when_no_concept_id():
    # When no slide concept_id is available, fall back to label overlap (degraded).
    s = _sess(weak=[{"concept_id": "7", "label": "loops"}], subtopic="intro to loops")
    assert "DIFFICULTY_TOPIC" in ts._competence_and_style_skills(s, "")


def test_style_and_pace_skills_from_claims():
    profile = {"schema_version": 2, "claims": [
        {"field": "preferred_modality", "value": "visual diagrams", "confidence": 0.6},
        {"field": "pace", "value": "needs a slower pace", "confidence": 0.6},
    ]}
    skills = ts._competence_and_style_skills(_sess(profile=profile), "")
    assert "VISUAL_LEARNER" in skills
    assert "PACE_SLOW" in skills


# ── problem set: STRONG CONCEPTS block injected ──────────────────────────────

@pytest.mark.asyncio
async def test_problem_set_injects_strong_block(monkeypatch):
    import services.problem_set_service as pss
    from schemas.problem_set import ProblemSetGenerateRequest

    captured = {}

    class _Client:
        def chat_json(self, messages, **kw):
            captured["user"] = messages[-1]["content"]
            raise RuntimeError("stop after capture")

    monkeypatch.setattr(pss, "_get_ollama_client", lambda: _Client())

    async def _prof(sid):
        return {}
    monkeypatch.setattr(pss, "_fetch_student_profile", _prof)

    async def _cc(cid):
        return [{"id": "42", "label": "recursion"}]

    async def _cm(sid):
        return {"42": {"score": 0.9, "evidence": 3}}  # strong at recursion

    monkeypatch.setattr("services.mastery.fetch_course_concepts", _cc)
    monkeypatch.setattr("services.mastery.fetch_concept_mastery", _cm)

    req = ProblemSetGenerateRequest(
        student_id="7", course_id="3", lesson_id="9", lesson_title="Recursion",
        slides=[{"title": "Recursion", "content": "base case + recursive case"}],
    )
    with pytest.raises(RuntimeError):
        await pss.generate(req)

    assert "STRONG CONCEPTS" in captured["user"]
    assert "recursion" in captured["user"].lower()


# ── lab: checklist personalization + dead instructions removed ───────────────

def test_lab_checklist_receives_profile(monkeypatch):
    import services.lab_service as ls
    from schemas.coding import CodingLabGenerateRequest

    captured = {}

    def _capture(messages, **kw):
        captured["user"] = messages[-1]["content"]
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(ls, "_chat_json", _capture)
    req = CodingLabGenerateRequest(student_id="7", course_id="3", lesson_id="9", lesson_title="Recursion")
    profile = "Learning style: visual\nREMEDIATION TARGETS: recursion. \nSTRENGTH TARGETS: loops. "
    with pytest.raises(RuntimeError):
        ls._generate_checklist(req, {}, profile_context=profile)

    assert "STUDENT PROFILE" in captured["user"]
    assert "REMEDIATION TARGETS" in captured["user"]


def test_lab_prompt_has_concept_targets_not_dead_fields(monkeypatch):
    import services.lab_service as ls
    from schemas.coding import CodingLabGenerateRequest

    captured = {}

    def _capture(messages, **kw):
        captured["user"] = messages[-1]["content"]
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(ls, "_chat_json", _capture)
    req = CodingLabGenerateRequest(student_id="7", course_id="3", lesson_id="9", lesson_title="Recursion")
    profile = "Learning style: visual\nREMEDIATION TARGETS: recursion. \nSTRENGTH TARGETS: loops. "
    with pytest.raises(RuntimeError):
        ls._generate_lab(req, {}, checklist=[], profile_context=profile)

    prompt = captured["user"]
    assert "STRENGTH TARGETS" in prompt           # strengths now backed by data
    assert "REMEDIATION TARGETS" in prompt
    assert "topics_of_difficulty" not in prompt   # dead instruction removed
    assert "topics_of_strength" not in prompt
