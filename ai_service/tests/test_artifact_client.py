"""Batch 10a stage 2 — artifact HTTP client + plan_version resolver/guard.

The client's public methods are tested by capturing the centralized _request
(URL/json/params/headers contract); _request's own error handling is tested with
a fake httpx client. The plan_resolver guard is tested with an injected fake
PlanStore (no real SQLite).
"""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import services.artifact_client as ac
import services.plan_resolver as pr


# ── _request capture fixture ─────────────────────────────────────────────────

@pytest.fixture
def calls(monkeypatch):
    captured = []

    async def fake_request(method, path, *, student_id, json=None, params=None,
                           expected=(200, 201), timeout=15.0):
        captured.append({"method": method, "path": path, "student_id": student_id,
                         "json": json, "params": params, "expected": expected})
        return True, {"echo": True}

    monkeypatch.setattr(ac, "_request", fake_request)
    return captured


# ── Public method contracts ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_problem_set_contract(calls):
    await ac.create_problem_set("7", "3", "9", plan_version=2, ps_uid="ps-1",
                                content_json={"questions": []}, regenerate=True)
    c = calls[0]
    assert c["method"] == "POST" and c["path"] == "/problem-sets/"
    assert c["student_id"] == "7"
    assert c["json"]["regenerate"] is True
    assert c["json"]["plan_version"] == 2
    assert c["expected"] == (201,)  # create must require 201


@pytest.mark.asyncio
async def test_submit_hot_path_is_one_get_one_post(calls):
    # Resolve (GET) then append (POST) — exactly two calls, no extra round-trips.
    await ac.get_problem_set("7", "ps-1")
    await ac.append_attempt("7", "ps-1", question_id="q1", code="x",
                            evaluated_rubric=[], hints_used=0, score=80)
    assert len(calls) == 2
    assert calls[0]["method"] == "GET" and calls[0]["path"] == "/problem-sets/ps-1/"
    assert calls[1]["method"] == "POST" and calls[1]["path"] == "/problem-sets/ps-1/attempts/"
    assert calls[1]["json"]["score"] == 80


@pytest.mark.asyncio
async def test_upsert_artifact_contract(calls):
    await ac.upsert_artifact("7", "3", "slides", plan_version=2, session_number=1,
                             content_json={"slides": []})
    c = calls[0]
    assert c["path"] == "/" and c["json"]["artifact_type"] == "slides"
    assert c["json"]["session_number"] == 1 and c["json"]["plan_version"] == 2


@pytest.mark.asyncio
async def test_best_score_omits_plan_version_when_none(calls):
    await ac.get_best_score("7", "3", "9")
    assert "plan_version" not in calls[0]["params"]
    await ac.get_best_score("7", "3", "9", plan_version=4)
    assert calls[1]["params"]["plan_version"] == 4


# ── _request error handling ──────────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp=None, raise_exc=None):
        self._resp = resp
        self._raise = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, *a, **k):
        if self._raise:
            raise self._raise
        return self._resp


@pytest.mark.asyncio
async def test_request_returns_data_on_expected_status(monkeypatch):
    monkeypatch.setattr(ac.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(_Resp(200, {"ok": 1})))
    ok, data = await ac._request("GET", "/x/", student_id="7")
    assert ok and data == {"ok": 1}


@pytest.mark.asyncio
async def test_request_degrades_on_bad_status(monkeypatch):
    monkeypatch.setattr(ac.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(_Resp(500)))
    ok, data = await ac._request("GET", "/x/", student_id="7")
    assert ok is False and data is None


@pytest.mark.asyncio
async def test_request_degrades_on_transport_error(monkeypatch):
    monkeypatch.setattr(ac.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(raise_exc=RuntimeError("conn refused")))
    ok, data = await ac._request("POST", "/x/", student_id="7", json={})
    assert ok is False and data is None


@pytest.mark.asyncio
async def test_request_sends_ownership_headers(monkeypatch):
    seen = {}

    class _Capture(_FakeClient):
        async def request(self, method, url, *, json=None, params=None, headers=None):
            seen.update(headers=headers, url=url)
            return _Resp(200, {})

    monkeypatch.setenv("INTERNAL_SERVICE_KEY", "k3y")
    monkeypatch.setattr(ac.httpx, "AsyncClient", lambda *a, **k: _Capture())
    await ac._request("GET", "/y/", student_id="42")
    assert seen["headers"]["X-Student-ID"] == "42"
    assert seen["headers"]["X-Service-Key"] == "k3y"
    assert seen["url"].endswith("/artifacts/y/")


# ── plan_resolver guard ──────────────────────────────────────────────────────

class _FakeStore:
    def __init__(self, versions, current=None):
        self._versions = versions
        self._current = current

    def list_versions(self, student_id, course_id):
        return [{"plan_version": v} for v in self._versions]

    def load_current(self, student_id, course_id):
        if self._current is None:
            return None
        return type("P", (), {"plan_version": self._current})()


def test_validate_known_version_true():
    store = _FakeStore([1, 2, 3])
    assert pr.validate_plan_version("7", "3", 2, store=store) is True


def test_validate_unknown_version_warns_and_false(caplog):
    store = _FakeStore([1, 2])
    import logging
    with caplog.at_level(logging.WARNING):
        assert pr.validate_plan_version("7", "3", 9, store=store) is False
    assert any("MISMATCH" in r.message for r in caplog.records)


def test_resolve_for_write_uses_requested_without_coercion():
    store = _FakeStore([1, 2], current=2)
    # An unknown requested version is RETURNED AS-IS (guard warns, never coerces).
    assert pr.resolve_for_write("7", "3", requested=9, store=store) == 9


def test_resolve_for_write_falls_back_to_current():
    store = _FakeStore([1, 2], current=2)
    assert pr.resolve_for_write("7", "3", store=store) == 2


def test_current_plan_version_none_when_no_plan():
    store = _FakeStore([], current=None)
    assert pr.current_plan_version("7", "3", store=store) is None
