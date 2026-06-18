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
    print(f"DEBUG: expected='{expected}', received='{x_service_key}'")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=403, detail="Service key required")


@router.get("/available-books")
async def available_books(corpus_id: str = "", x_service_key: str | None = Header(default=None)):
    """Books available to attach: PDFs on disk + their index state."""
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
async def index_book(req: IndexRequest, x_service_key: str | None = Header(default=None)):
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
