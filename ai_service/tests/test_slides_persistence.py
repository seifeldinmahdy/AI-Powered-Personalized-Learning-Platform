"""Batch 10a stage 3 — slides are persisted at generation + resume read-through.

We avoid loading the heavy slide-generation models by stubbing the orchestrator;
the focus is the persistence wiring: plan_version is resolved (guarded, not
coerced) and the deck is upserted as StudentArtifact(type=slides), and the
/persisted resume path returns a saved deck.
"""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import routers.slides as slides


def _req(**kw):
    base = dict(session_number=1, session_title="Loops", topics_covered=["for"],
                book="", chunks=[], student_id="7", course_id="3", plan_version=2)
    base.update(kw)
    return slides.SlideGenerateRequest(**base)


def _resp():
    return slides.SlideGenerateResponse(
        session_number=1, session_title="Loops", total_slides=1,
        slides=[slides.SlideOut(slide_number=1, slide_type="Title", layout="List_View",
                                title="Loops")],
        generation_time_seconds=0.1,
    )


@pytest.mark.asyncio
async def test_persist_deck_upserts_with_resolved_plan_version(monkeypatch):
    captured = {}

    async def fake_upsert(student_id, course_id, artifact_type, **kw):
        captured.update(student_id=student_id, course_id=course_id,
                        artifact_type=artifact_type, **kw)
        return {"id": 1}

    # plan_resolver is consulted (client-supplied version honored, validated).
    monkeypatch.setattr("services.plan_resolver.resolve_for_write",
                        lambda sid, cid, requested=None, store=None: requested or 99)
    monkeypatch.setattr("services.artifact_client.upsert_artifact", fake_upsert)

    await slides._persist_deck(_req(plan_version=2), _resp())

    assert captured["artifact_type"] == "slides"
    assert captured["plan_version"] == 2          # client value honored
    assert captured["session_number"] == 1
    assert captured["content_json"]["total_slides"] == 1


@pytest.mark.asyncio
async def test_persist_deck_skips_without_student_or_course(monkeypatch):
    called = {"n": 0}

    async def fake_upsert(*a, **k):
        called["n"] += 1
        return {}

    monkeypatch.setattr("services.artifact_client.upsert_artifact", fake_upsert)
    await slides._persist_deck(_req(student_id=None), _resp())
    assert called["n"] == 0  # nothing to key on → not persisted


@pytest.mark.asyncio
async def test_persist_deck_skips_when_no_plan_version(monkeypatch):
    called = {"n": 0}

    async def fake_upsert(*a, **k):
        called["n"] += 1
        return {}

    # No plan resolvable (student has no plan yet) → do NOT invent one.
    monkeypatch.setattr("services.plan_resolver.resolve_for_write",
                        lambda *a, **k: None)
    monkeypatch.setattr("services.artifact_client.upsert_artifact", fake_upsert)
    await slides._persist_deck(_req(plan_version=None), _resp())
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_persisted_endpoint_returns_saved_deck(monkeypatch):
    async def fake_get(student_id, *, course_id, session_number, plan_version):
        assert session_number == 1 and plan_version == 2
        return {"total_slides": 3}

    monkeypatch.setattr("services.artifact_client.get_slides_artifact", fake_get)
    out = await slides.persisted_slides("7", "3", 1, plan_version=2)
    assert out == {"total_slides": 3}


@pytest.mark.asyncio
async def test_persisted_endpoint_404_when_missing(monkeypatch):
    from fastapi import HTTPException

    async def fake_get(student_id, *, course_id, session_number, plan_version):
        return None

    monkeypatch.setattr("services.artifact_client.get_slides_artifact", fake_get)
    with pytest.raises(HTTPException) as ei:
        await slides.persisted_slides("7", "3", 1, plan_version=2)
    assert ei.value.status_code == 404
