"""AI admin-authoring: corpus listing/upload/index-status + course-desc draft."""

import os
import sys

_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)

import pytest

import services.corpus_indexing as ci
import routers.authoring as authoring


# ── corpus_indexing ──────────────────────────────────────────────────────────

def test_save_upload_writes_pdf_and_returns_stem(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "_RAW_BOOKS_DIR", tmp_path)
    stem = ci.save_upload("Intro To Python.pdf", b"%PDF-1.4 fake")
    assert stem == "Intro To Python"
    assert (tmp_path / "Intro To Python.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_save_upload_rejects_non_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "_RAW_BOOKS_DIR", tmp_path)
    with pytest.raises(ValueError):
        ci.save_upload("notes.txt", b"hello")


def test_list_books_falls_back_to_disk_when_store_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "_RAW_BOOKS_DIR", tmp_path)
    (tmp_path / "alpha.pdf").write_bytes(b"%PDF")
    (tmp_path / "beta.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(ci, "_store", lambda: (_ for _ in ()).throw(RuntimeError("no chroma")))
    books = ci.list_books(corpus_id="c1")
    stems = {b["book_stem"] for b in books}
    assert {"alpha", "beta"} <= stems
    assert all(b["file_present"] for b in books)
    assert all(b["indexed_chunks"] == 0 for b in books)


def test_list_books_uses_store_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "_RAW_BOOKS_DIR", tmp_path)
    (tmp_path / "alpha.pdf").write_bytes(b"%PDF")

    class _FakeStore:
        def get_all_metadata_values(self, field):
            return ["alpha"]
        def count_where(self, where):
            # in-corpus query is the $and one
            return 5 if "$and" in where else 12

    monkeypatch.setattr(ci, "_store", lambda: _FakeStore())
    books = {b["book_stem"]: b for b in ci.list_books(corpus_id="c1")}
    assert books["alpha"]["indexed_chunks"] == 12
    assert books["alpha"]["in_corpus_chunks"] == 5


def test_status_default_and_missing_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "_RAW_BOOKS_DIR", tmp_path)
    assert ci.get_status("c1", "ghost")["status"] == "unknown"
    out = ci.start_indexing("ghost", "c1", "9")  # no PDF on disk
    assert out["status"] == "failed"
    assert "not found" in out["detail"].lower()


# ── course-description draft ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_course_description_fallback_without_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    req = authoring.CourseDescriptionRequest(title="Intro to Python", topics=["loops", "functions"])
    out = await authoring.draft_course_description(req)
    assert out.source == "fallback"
    assert "Intro to Python" in out.description
    assert "loops" in out.description
