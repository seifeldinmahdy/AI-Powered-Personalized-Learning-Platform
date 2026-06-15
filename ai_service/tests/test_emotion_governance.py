"""Batch 11b (AI side) — consent enforcement (fail closed), the fuse gate,
and raw-emotion retention/purge in the durable log."""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import services.emotion_consent as ec
import services.session_event_log as sel
import routers.profiler as profiler


# ── Consent client: FAIL CLOSED ──────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp=None, raise_exc=None):
        self._resp, self._raise = resp, raise_exc

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get(self, *a, **k):
        if self._raise:
            raise self._raise
        return self._resp


@pytest.mark.asyncio
async def test_consent_granted_true_only_when_django_says_granted(monkeypatch):
    monkeypatch.setattr(ec.httpx, "AsyncClient", lambda *a, **k: _FakeClient(_Resp(200, {"granted": True})))
    ec._cache.clear()
    assert await ec.consent_granted("7") is True

    monkeypatch.setattr(ec.httpx, "AsyncClient", lambda *a, **k: _FakeClient(_Resp(200, {"granted": False})))
    ec._cache.clear()
    assert await ec.consent_granted("7") is False


@pytest.mark.asyncio
async def test_consent_fails_closed_on_error_and_does_not_cache(monkeypatch):
    ec._cache.clear()
    monkeypatch.setattr(ec.httpx, "AsyncClient", lambda *a, **k: _FakeClient(raise_exc=RuntimeError("timeout")))
    assert await ec.consent_granted("7") is False          # error → no consent
    assert "7" not in ec._cache                              # failure not cached
    # Now Django recovers and says granted → next call reflects it immediately.
    monkeypatch.setattr(ec.httpx, "AsyncClient", lambda *a, **k: _FakeClient(_Resp(200, {"granted": True})))
    assert await ec.consent_granted("7") is True


@pytest.mark.asyncio
async def test_consent_empty_student_is_false(monkeypatch):
    assert await ec.consent_granted("") is False


# ── Fuse gate: no consent → dropped, never persisted ─────────────────────────

@pytest.mark.asyncio
async def test_fuse_without_consent_drops_and_does_not_fuse(monkeypatch):
    async def _no(*a, **k):
        return False
    monkeypatch.setattr("services.emotion_consent.consent_granted", _no)

    # If the gate failed, fuse_emotions would run — make that an explicit failure.
    async def _must_not_run(*a, **k):
        raise AssertionError("fuse_emotions must not run without consent")
    monkeypatch.setattr(profiler, "fuse_emotions", _must_not_run)

    req = profiler.FuseEmotionsRequest(student_id="7", fer_emotion="confused", ser_emotion="bored")
    out = await profiler.fuse(req)
    assert out["fused_emotion"] == "uncertain"  # treated as missing


# ── Durable log: purge / retention / backlog ─────────────────────────────────

def _fresh_log(tmp_path):
    sel.SessionEventLog._instance = None
    return sel.SessionEventLog(db_path=tmp_path / "ev.db")


def test_purge_student_emotion_removes_only_that_students_emotion(tmp_path):
    log = _fresh_log(tmp_path)
    log.append("s1", "emotion", {"x": 1}, student_id="7")
    log.append("s1", "emotion", {"x": 2}, student_id="9")
    log.append("s1", "slide", {"x": 3}, student_id="7")  # non-emotion: keep
    n = log.purge_student_emotion("7")
    assert n == 1
    remaining = log.read_unconsumed("s1")
    kinds = sorted((e["event_type"], e["student_id"]) for e in remaining)
    assert kinds == [("emotion", "9"), ("slide", "7")]


def test_purge_emotion_older_than_only_touches_consumed(tmp_path):
    log = _fresh_log(tmp_path)
    log.append("s1", "emotion", {"x": 1}, student_id="7")  # will stay unconsumed
    log.append("s1", "emotion", {"x": 2}, student_id="7")
    events = log.read_unconsumed("s1")
    log.mark_consumed("s1", min(e["id"] for e in events))  # consume only the first
    # Future cutoff → all are "old", but only the CONSUMED one may be purged.
    purged = log.purge_emotion_older_than("2999-01-01T00:00:00+00:00")
    assert purged == 1
    assert len(log.read_unconsumed("s1")) == 1  # unconsumed survives (no race)


def test_purge_consumed_emotion_after_consolidation(tmp_path):
    log = _fresh_log(tmp_path)
    log.append("s1", "emotion", {"x": 1}, student_id="7")
    events = log.read_unconsumed("s1")
    log.mark_consumed("s1", max(e["id"] for e in events))
    assert log.purge_consumed_emotion("s1") == 1


def test_unattributable_backlog_purged_at_init(tmp_path):
    # Simulate the pre-fix backlog: emotion rows with empty student_id.
    log = _fresh_log(tmp_path)
    log.append("s1", "emotion", {"x": 1}, student_id="")   # legacy/unattributable
    log.append("s1", "emotion", {"x": 2}, student_id="7")  # attributable
    log.append("s1", "slide", {"x": 3}, student_id="")     # non-emotion: keep
    # Re-init over the same file → one-time backlog purge runs.
    sel.SessionEventLog._instance = None
    log2 = sel.SessionEventLog(db_path=tmp_path / "ev.db")
    remaining = log2.read_unconsumed("s1")
    kinds = sorted((e["event_type"], e["student_id"]) for e in remaining)
    assert kinds == [("emotion", "7"), ("slide", "")]  # only unattributable EMOTION purged
