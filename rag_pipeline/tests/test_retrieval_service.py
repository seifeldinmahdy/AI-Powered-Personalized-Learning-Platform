"""RetrievalService scope-enforcement tests.

Acceptance: a query scoped to corpus A never returns chunks from corpus B, and
no method can run without a corpus scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.indexing.store import VectorStore
from src.retrieval.retrieval_service import (
    RetrievalScope,
    RetrievalService,
    ScopeError,
)

CORPUS_A = "corpus_aaaaaaaa"
CORPUS_B = "corpus_bbbbbbbb"


def _add_chunk(store, chunk_id, corpus_id, course_id, topic, difficulty,
               embedding, chunk_index=0, book="bookA", concept_id=""):
    # New model: per-corpus membership flag (corpus__<id>="1") and per-corpus
    # concept tag (concept__<id>=<concept_id>), so a book can belong to many
    # corpora. Legacy corpus_id/concept_id are kept to exercise the fallback.
    meta = {
        "topic": topic,
        "difficulty": difficulty,
        "is_definitional": False,
        "depends_on": "[]",
        "summary": f"summary {chunk_id}",
        "book": book,
        "course": book,
        "corpus_id": corpus_id,
        "course_id": course_id,
        "concept_id": concept_id,
        f"corpus__{corpus_id}": "1",
        "page_start": 1,
        "page_end": 2,
        "chunk_index": chunk_index,
    }
    if concept_id:
        meta[f"concept__{corpus_id}"] = concept_id
    store.collection.add(
        ids=[chunk_id],
        documents=[f"text for {chunk_id} about {topic}"],
        embeddings=[embedding],
        metadatas=[meta],
    )


@pytest.fixture()
def service(tmp_path):
    """A RetrievalService over a temp Chroma seeded with two corpora."""
    store = VectorStore(persist_dir=str(tmp_path / "chroma"), collection_name="course_chunks")
    # Corpus A: embeddings near [1,0]; concepts c10 (loops), c11 (recursion)
    _add_chunk(store, "a1", CORPUS_A, "3", "loops", "beginner", [1.0, 0.0], 0, "bookA", concept_id="c10")
    _add_chunk(store, "a2", CORPUS_A, "3", "recursion", "expert", [0.9, 0.1], 1, "bookA", concept_id="c11")
    # Corpus B: embeddings near [0,1]; concept c20 (pointers)
    _add_chunk(store, "b1", CORPUS_B, "4", "pointers", "beginner", [0.0, 1.0], 0, "bookB", concept_id="c20")
    _add_chunk(store, "b2", CORPUS_B, "4", "pointers", "expert", [0.1, 0.9], 1, "bookB", concept_id="c20")
    return RetrievalService(store=store)


def _scope(corpus_id):
    return RetrievalScope(corpus_id=corpus_id, course_id="x")


# ── Leakage: A never returns B ───────────────────────────────────

def test_get_all_chunks_is_corpus_scoped(service):
    a = service.get_all_chunks(_scope(CORPUS_A))
    assert {c.chunk_id for c in a} == {"a1", "a2"}
    assert all(c.corpus_id == CORPUS_A for c in a)


def test_get_topics_is_corpus_scoped(service):
    assert service.get_topics(_scope(CORPUS_A)) == ["loops", "recursion"]
    assert service.get_topics(_scope(CORPUS_B)) == ["pointers"]


def test_topic_summary_is_corpus_scoped(service):
    assert service.get_topic_summary(_scope(CORPUS_B)) == {"pointers": 2}


def test_topics_by_difficulty_is_corpus_scoped(service):
    assert service.get_topics_by_difficulty(_scope(CORPUS_A), "expert") == ["recursion"]
    assert service.get_topics_by_difficulty(_scope(CORPUS_B), "expert") == ["pointers"]


def test_get_chunks_by_ids_drops_foreign_ids(service):
    # Ask for a B id while scoped to A → it must not leak.
    got = service.get_chunks_by_ids(_scope(CORPUS_A), ["a1", "b1", "b2"])
    assert {c.chunk_id for c in got} == {"a1"}


def test_semantic_search_cannot_cross_corpora(service):
    # Query vector is closest to corpus A, but scoped to B → only B returned.
    results = service.semantic_search(
        _scope(CORPUS_B), query_embedding=[1.0, 0.0], top_k=5,
    )
    assert results, "expected results within corpus B"
    assert all(c.corpus_id == CORPUS_B for c in results)


# ── Scope is mandatory ───────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_scope_is_refused(service, bad):
    scope = RetrievalScope(corpus_id=bad)  # type: ignore[arg-type]
    with pytest.raises(ScopeError):
        service.get_all_chunks(scope)
    with pytest.raises(ScopeError):
        service.get_topics(scope)
    with pytest.raises(ScopeError):
        service.semantic_search(scope, query_embedding=[1.0, 0.0])


# ── Empty corpus is distinguishable ──────────────────────────────

def test_empty_corpus_counts_zero(service):
    assert service.count(_scope("corpus_that_has_no_chunks")) == 0
    assert service.get_all_chunks(_scope("corpus_that_has_no_chunks")) == []


def test_count_reflects_scope(service):
    assert service.count(_scope(CORPUS_A)) == 2
    assert service.count(_scope(CORPUS_B)) == 2


# ── Concept tagging + concept-scoped retrieval (Batch 5) ─────────

def test_get_chunks_for_concept_is_scoped(service):
    loops = service.get_chunks_for_concept(_scope(CORPUS_A), "c10")
    assert {c.chunk_id for c in loops} == {"a1"}
    assert all(c.concept_id == "c10" for c in loops)


def test_concept_chunk_counts(service):
    counts = service.get_concept_chunk_counts(_scope(CORPUS_A))
    assert counts == {"c10": 1, "c11": 1}
    assert service.get_concept_chunk_counts(_scope(CORPUS_B)) == {"c20": 2}


def test_concept_lookup_cannot_cross_corpora(service):
    # c20 belongs to corpus B; asking within corpus A must return nothing.
    assert service.get_chunks_for_concept(_scope(CORPUS_A), "c20") == []


def test_retrieved_chunk_carries_concept_id(service):
    chunks = service.get_all_chunks(_scope(CORPUS_A))
    by_id = {c.chunk_id: c for c in chunks}
    assert by_id["a1"].concept_id == "c10"
    assert by_id["a2"].concept_id == "c11"
