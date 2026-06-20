"""
Corpus authoring endpoints (admin, service-key). List/upload books and index a
book into a course's corpus. Django proxies these behind admin auth.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/corpus", tags=["corpus-authoring"])


def _require_service_key(x_service_key: str | None) -> None:
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=403, detail="Service key required")


@router.get("/available-books")
def available_books(corpus_id: str = "", x_service_key: str | None = Header(default=None)):
    """Books available to attach: PDFs on disk + their index state.

    Sync ``def`` on purpose: it hits the (blocking) vector store, so FastAPI runs
    it in a threadpool and a slow DB call can't freeze the event loop.
    """
    _require_service_key(x_service_key)
    from services.corpus_indexing import list_books
    return {"books": list_books(corpus_id or None)}


@router.post("/upload")
async def upload_book(file: UploadFile = File(...), x_service_key: str | None = Header(default=None)):
    """Save an uploaded PDF so it can be selected/indexed. Returns book_stem."""
    _require_service_key(x_service_key)
    from services.corpus_indexing import save_upload
    try:
        data = await file.read()
        stem = save_upload(file.filename or "book.pdf", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"book_stem": stem}


class IndexRequest(BaseModel):
    book_stem: str
    corpus_id: str
    course_id: str


@router.post("/index")
def index_book(req: IndexRequest, x_service_key: str | None = Header(default=None)):
    """Index a book into a corpus (background). Returns the initial status."""
    _require_service_key(x_service_key)
    from services.corpus_indexing import start_indexing
    return start_indexing(req.book_stem, req.corpus_id, req.course_id)


@router.get("/index-status")
async def index_status(corpus_id: str, book_stem: str, x_service_key: str | None = Header(default=None)):
    """Indexing status for a (corpus, book)."""
    _require_service_key(x_service_key)
    from services.corpus_indexing import get_status
    return get_status(corpus_id, book_stem)


class CorpusBookRequest(BaseModel):
    book_stem: str
    corpus_id: str
    course_id: str | None = None


@router.post("/attach")
def attach_book(req: CorpusBookRequest, x_service_key: str | None = Header(default=None)):
    """Add an already-indexed book to a corpus (fast; no re-index).

    If the book isn't indexed yet, this kicks off indexing and attaches on
    completion (same as /index) — so a 2nd course reusing the book is instant.
    When ``course_id`` is supplied and the book is already indexed, concepts are
    extracted in the background and persisted to Django.
    """
    _require_service_key(x_service_key)
    from services.corpus_indexing import attach_book_to_corpus, start_indexing
    course_id = req.course_id or ""
    res = attach_book_to_corpus(req.book_stem, req.corpus_id, course_id)
    if not res.get("indexed"):
        # Not in the library yet — index it (background) and attach when done.
        return start_indexing(req.book_stem, req.corpus_id, course_id)
    return res


@router.post("/detach")
def detach_book(req: CorpusBookRequest, x_service_key: str | None = Header(default=None)):
    """Remove a book from a corpus (membership only). Chunks stay in the DB."""
    _require_service_key(x_service_key)
    from services.corpus_indexing import detach_book_from_corpus
    return detach_book_from_corpus(req.book_stem, req.corpus_id)


class DeleteBookRequest(BaseModel):
    book_stem: str


@router.post("/delete-book")
def delete_book(req: DeleteBookRequest, x_service_key: str | None = Header(default=None)):
    """Delete a book's chunks from the vector library ENTIRELY (all corpora)."""
    _require_service_key(x_service_key)
    from services.corpus_indexing import delete_book_entirely
    return delete_book_entirely(req.book_stem)
