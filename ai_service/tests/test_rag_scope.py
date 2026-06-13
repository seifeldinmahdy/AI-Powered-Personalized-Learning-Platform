"""/rag/ask scope + grounding tests.

Acceptance:
- A tutor answer in course A can only cite/use sources from course A's corpus:
  /rag/ask resolves the course to its corpus and passes THAT scope to the single
  RetrievalService (whose A/B leakage isolation is proven in
  rag_pipeline/tests/test_retrieval_service.py). Here we prove /rag/ask uses the
  resolved corpus_id as the scope and never an unscoped query.
- Graceful: a course with no corpus returns grounded=False / no passages.
"""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import routers.rag as rag

# Ensure pathway/rag_pipeline are importable, then grab the resolver module.
rag._ensure_paths()
import pathway.corpus_resolver as cres  # type: ignore  # noqa: E402


class _FakeChunk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_service(captured):
    class FakeService:
        _store = type("S", (), {"count": 3})()

        def semantic_search(self, scope, query=None, topic=None, difficulty=None, top_k=5):
            captured["corpus_id"] = scope.corpus_id
            captured["course_id"] = scope.course_id
            captured["query"] = query
            return [
                _FakeChunk(
                    chunk_id="a1", raw_text="text from corpus A", book="BookA",
                    page_start=1, page_end=2, topic="loops", relevance_score=0.8,
                )
            ]

    return FakeService()


@pytest.mark.asyncio
async def test_rag_ask_scopes_to_resolved_corpus(monkeypatch):
    captured = {}
    monkeypatch.setattr(cres, "resolve_corpus_id", lambda cid: "corpusA")
    monkeypatch.setattr(rag, "get_retrieval_service", lambda: _fake_service(captured))

    resp = await rag.ask_rag(rag.RAGRequest(question="what is a loop? (scopetest1)", course_id="3"))

    # The query was scoped to the corpus resolved from course_id=3 — not unscoped.
    assert captured["corpus_id"] == "corpusA"
    assert captured["course_id"] == "3"
    assert resp.grounded is True
    assert resp.passages[0].book == "BookA"
    assert resp.passages[0].text == "text from corpus A"
    # Citations flow through.
    assert resp.passages[0].page_start == 1 and resp.passages[0].topic == "loops"


@pytest.mark.asyncio
async def test_rag_ask_no_corpus_is_graceful(monkeypatch):
    monkeypatch.setattr(cres, "resolve_corpus_id", lambda cid: None)
    # If it tried to retrieve it would explode — assert it short-circuits instead.
    monkeypatch.setattr(rag, "get_retrieval_service", lambda: (_ for _ in ()).throw(AssertionError("must not retrieve without a corpus")))

    resp = await rag.ask_rag(rag.RAGRequest(question="anything (scopetest2)", course_id="999"))

    assert resp.grounded is False
    assert resp.passages == []
