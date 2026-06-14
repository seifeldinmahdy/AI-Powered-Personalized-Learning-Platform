"""Batch 10a stage 5 — durable labs + the PlacementAttempt event.

Lab generation/completion and placement submit are LLM/flow-heavy; we test the
durable seams: persist_lab upserts a StudentArtifact(type=lab) with the resolved
plan_version (and skips rather than inventing one), and the placement-event client
call builds the correct append-only payload.
"""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import services.lab_service as lab_service
import services.artifact_client as ac


# ── persist_lab ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_lab_upserts_with_resolved_plan_version(monkeypatch):
    captured = {}

    async def fake_upsert(student_id, course_id, artifact_type, **kw):
        captured.update(student_id=student_id, course_id=course_id,
                        artifact_type=artifact_type, **kw)
        return {"id": 1}

    monkeypatch.setattr("services.plan_resolver.current_plan_version", lambda sid, cid: 4)
    monkeypatch.setattr("services.artifact_client.upsert_artifact", fake_upsert)

    await lab_service.persist_lab("7", "3", "9", {"lab": {"cells": []}}, status="completed")
    assert captured["artifact_type"] == "lab"
    assert captured["plan_version"] == 4
    assert captured["lesson_id"] == 9            # numeric lesson id coerced to int
    assert captured["status"] == "completed"
    assert captured["content_json"] == {"lab": {"cells": []}}


@pytest.mark.asyncio
async def test_persist_lab_skips_without_plan_version(monkeypatch):
    called = {"n": 0}

    async def fake_upsert(*a, **k):
        called["n"] += 1
        return {}

    monkeypatch.setattr("services.plan_resolver.current_plan_version", lambda sid, cid: None)
    monkeypatch.setattr("services.artifact_client.upsert_artifact", fake_upsert)
    await lab_service.persist_lab("7", "3", "9", {"lab": {}})
    assert called["n"] == 0  # not invented


@pytest.mark.asyncio
async def test_persist_lab_skips_without_keys(monkeypatch):
    called = {"n": 0}

    async def fake_upsert(*a, **k):
        called["n"] += 1
        return {}

    monkeypatch.setattr("services.artifact_client.upsert_artifact", fake_upsert)
    await lab_service.persist_lab("7", "", "9", {"lab": {}})  # no course
    assert called["n"] == 0


# ── PlacementAttempt event payload ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_placement_attempt_contract(monkeypatch):
    captured = {}

    async def fake_request(method, path, *, student_id, json=None, params=None,
                           expected=(200, 201), timeout=15.0):
        captured.update(method=method, path=path, student_id=student_id, json=json)
        return True, {"id": 1}

    monkeypatch.setattr(ac, "_request", fake_request)
    await ac.post_placement_attempt(
        "7", "3", answers=[{"q": 1}],
        per_question=[{"is_correct": True}], score=80, concept_results={"c1": 0.8})

    assert captured["method"] == "POST"
    assert captured["path"] == "/placement-attempts/"
    assert captured["student_id"] == "7"
    assert captured["json"]["score"] == 80
    assert captured["json"]["concept_results"] == {"c1": 0.8}
    assert captured["json"]["course_id"] == "3"
