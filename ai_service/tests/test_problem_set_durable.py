"""Batch 10a stage 4 — durable problem sets: regen weighting, mastery source,
and the durable-persist wiring (generation stamping + best-effort).

The LLM-driven generate/evaluate paths are not exercised here; we test the
deterministic seams: the mastery weight policy, that source+alpha flow through to
the single writer, and that _persist_problem_set records the set and stamps the
authoritative generation_index / plan_version back.
"""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import services.problem_set_service as pss
import services.mastery as mastery
from schemas.problem_set import ProblemSetData, ProblemSetQuestion


# ── Reduced-alpha-per-set policy ──────────────────────────────────────────────

def test_mastery_weight_original_vs_regenerated():
    assert pss.mastery_weight_for_generation(0) == (pss.ORIGINAL_MASTERY_ALPHA, "problem_set")
    a, s = pss.mastery_weight_for_generation(1)
    assert a == pss.REGEN_MASTERY_ALPHA and s == "problem_set_regen"
    # A regenerated win moves mastery LESS than an equivalent original win.
    assert pss.REGEN_MASTERY_ALPHA < pss.ORIGINAL_MASTERY_ALPHA


@pytest.mark.asyncio
async def test_eval_update_passes_source_and_alpha(monkeypatch):
    sent = {}

    async def fake_post(student_id, events):
        sent["student_id"] = student_id
        sent["events"] = events

    monkeypatch.setattr(mastery, "post_mastery_events", fake_post)
    rubric = [{"concept_id": "c1", "category": "logic",
               "checks": [{"result": True, "weight": 1.0}]}]
    await mastery.update_concept_mastery_from_eval(
        "7", rubric, alpha=pss.REGEN_MASTERY_ALPHA, source="problem_set_regen")
    assert sent["events"][0]["source"] == "problem_set_regen"
    assert sent["events"][0]["alpha"] == pss.REGEN_MASTERY_ALPHA


# ── Durable persist wiring ────────────────────────────────────────────────────

def _ps():
    return ProblemSetData(
        problem_set_id="ps-1", student_id="7", course_id="3", lesson_id="9",
        questions=[ProblemSetQuestion(id="q1", topic="t", title="T",
                                      scenario_framing="", problem_statement="p",
                                      starter_code="", analogy_explanation="a")],
    )


@pytest.mark.asyncio
async def test_persist_stamps_generation_from_response(monkeypatch):
    captured = {}

    async def fake_create(student_id, course_id, lesson_id, *, plan_version, ps_uid,
                          content_json, regenerate):
        captured.update(plan_version=plan_version, ps_uid=ps_uid, regenerate=regenerate,
                        content_json=content_json)
        return {"plan_version": plan_version, "generation_index": 2 if regenerate else 0}

    monkeypatch.setattr("services.plan_resolver.current_plan_version",
                        lambda sid, cid: 5)
    monkeypatch.setattr("services.artifact_client.create_problem_set", fake_create)

    ps = _ps()
    await pss._persist_problem_set(ps, regenerate=True)
    assert captured["plan_version"] == 5 and captured["regenerate"] is True
    assert captured["content_json"]["questions"][0]["id"] == "q1"
    assert ps.plan_version == 5 and ps.generation_index == 2  # stamped back


@pytest.mark.asyncio
async def test_persist_skips_when_no_plan_version(monkeypatch):
    called = {"n": 0}

    async def fake_create(*a, **k):
        called["n"] += 1
        return {}

    monkeypatch.setattr("services.plan_resolver.current_plan_version", lambda sid, cid: None)
    monkeypatch.setattr("services.artifact_client.create_problem_set", fake_create)
    await pss._persist_problem_set(_ps(), regenerate=False)
    assert called["n"] == 0  # no plan → not recorded, not invented


@pytest.mark.asyncio
async def test_persist_regen_raises_when_not_recorded(monkeypatch):
    async def fake_create(*a, **k):
        return None  # durable write rejected/failed

    monkeypatch.setattr("services.plan_resolver.current_plan_version", lambda sid, cid: 5)
    monkeypatch.setattr("services.artifact_client.create_problem_set", fake_create)
    with pytest.raises(RuntimeError):
        await pss._persist_problem_set(_ps(), regenerate=True)
