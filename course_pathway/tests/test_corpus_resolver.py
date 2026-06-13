"""Tests for the server-side, cached course_id -> corpus_id resolver."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pathway import corpus_resolver


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    corpus_resolver.clear_cache()
    yield
    corpus_resolver.clear_cache()


def test_resolves_and_caches(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout=None):
        calls["n"] += 1
        return _FakeResp(200, {"corpus_id": "crp_123"})

    monkeypatch.setattr(corpus_resolver.httpx, "get", fake_get)

    assert corpus_resolver.resolve_corpus_id("3") == "crp_123"
    # Second call must be served from cache (immutable mapping) — no new request.
    assert corpus_resolver.resolve_corpus_id("3") == "crp_123"
    assert calls["n"] == 1


def test_missing_corpus_returns_none_and_is_not_cached(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout=None):
        calls["n"] += 1
        return _FakeResp(404)

    monkeypatch.setattr(corpus_resolver.httpx, "get", fake_get)

    assert corpus_resolver.resolve_corpus_id("99") is None
    # Not cached → a later lookup tries again (corpus may be created later).
    assert corpus_resolver.resolve_corpus_id("99") is None
    assert calls["n"] == 2


def test_network_error_returns_none(monkeypatch):
    def boom(url, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(corpus_resolver.httpx, "get", boom)
    assert corpus_resolver.resolve_corpus_id("3") is None
