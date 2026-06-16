"""
Corpus authoring support (admin): list/upload books and index them into a
course's corpus (Batch: admin authoring backend).

Indexing is the heavy offline pipeline (PDF -> chunk -> per-chunk LLM analysis ->
embed -> ChromaDB) owned by rag_pipeline. We run it for a SINGLE book in a
background thread and then stamp the admin-defined ``corpus_id`` / ``course_id``
onto that book's chunks so RetrievalService can scope them. Status is tracked in
memory and reported to the admin UI.

Heavy deps (embedder, LLM) are imported lazily inside the worker so the router
imports cheaply and degrades gracefully when models/keys are absent.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RAG_DIR = _REPO_ROOT / "rag_pipeline"
_RAW_BOOKS_DIR = _RAG_DIR / "raw_books"
_CHROMA_DIR = _RAG_DIR / "data" / "chroma"
_COLLECTION = "course_chunks"

# Indexing status, keyed by "corpus_id:book_stem".
_status: dict[str, dict] = {}
_status_lock = threading.Lock()


def _ensure_rag_path() -> None:
    p = str(_RAG_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def _store():
    """Lazy VectorStore (ChromaDB) — used for listing/counting; no models needed."""
    _ensure_rag_path()
    from src.indexing.store import VectorStore  # type: ignore
    return VectorStore(persist_dir=str(_CHROMA_DIR), collection_name=_COLLECTION)


def _status_key(corpus_id: str, book_stem: str) -> str:
    return f"{corpus_id}:{book_stem}"


def _set_status(corpus_id: str, book_stem: str, **fields) -> None:
    with _status_lock:
        cur = _status.setdefault(_status_key(corpus_id, book_stem), {})
        cur.update(book_stem=book_stem, corpus_id=corpus_id, **fields)


def get_status(corpus_id: str, book_stem: str) -> dict:
    with _status_lock:
        return dict(_status.get(_status_key(corpus_id, book_stem), {"status": "unknown"}))


# ── Listing + upload ─────────────────────────────────────────────────────────

def list_books(corpus_id: str | None = None) -> list[dict]:
    """Books available to attach: PDFs on disk + their ChromaDB index state.

    Each entry: {book_stem, file_present, indexed_chunks, in_corpus_chunks}.
    """
    _RAW_BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    on_disk = {p.stem for p in _RAW_BOOKS_DIR.glob("*.pdf")}

    indexed_books: list[str] = []
    counts: dict[str, int] = {}
    in_corpus: dict[str, int] = {}
    try:
        store = _store()
        indexed_books = sorted(set(store.get_all_metadata_values("book")))
        for b in set(indexed_books) | on_disk:
            counts[b] = store.count_where({"book": b})
            if corpus_id:
                in_corpus[b] = store.count_where(
                    {"$and": [{"book": b}, {"corpus_id": str(corpus_id)}]}
                )
    except Exception as exc:  # ChromaDB absent/empty → list disk only
        logger.warning("corpus list_books store unavailable", error=str(exc))

    stems = sorted(on_disk | set(indexed_books))
    return [
        {
            "book_stem": s,
            "file_present": s in on_disk,
            "indexed_chunks": counts.get(s, 0),
            "in_corpus_chunks": in_corpus.get(s, 0) if corpus_id else None,
        }
        for s in stems
    ]


def save_upload(filename: str, data: bytes) -> str:
    """Persist an uploaded PDF into raw_books_dir. Returns the book_stem."""
    _RAW_BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name
    if not safe.lower().endswith(".pdf"):
        raise ValueError("Only .pdf uploads are supported.")
    dest = _RAW_BOOKS_DIR / safe
    dest.write_bytes(data)
    logger.info("corpus book uploaded", book=dest.stem, bytes=len(data))
    return dest.stem


# ── Index a book into a corpus (background) ──────────────────────────────────

def start_indexing(book_stem: str, corpus_id: str, course_id: str) -> dict:
    """Kick off background indexing of one book into a corpus. Returns status."""
    pdf = _RAW_BOOKS_DIR / f"{book_stem}.pdf"
    if not pdf.exists():
        _set_status(corpus_id, book_stem, status="failed", detail="PDF not found on disk")
        return get_status(corpus_id, book_stem)
    cur = get_status(corpus_id, book_stem)
    if cur.get("status") == "indexing":
        return cur  # already running — idempotent
    _set_status(corpus_id, book_stem, status="indexing", detail="", chunks=0)
    threading.Thread(
        target=_run_index, args=(str(pdf), book_stem, str(corpus_id), str(course_id)),
        daemon=True,
    ).start()
    return get_status(corpus_id, book_stem)


def _run_index(pdf_path: str, book_stem: str, corpus_id: str, course_id: str) -> None:
    """Worker: index one PDF, then stamp corpus_id/course_id on its chunks."""
    _ensure_rag_path()
    try:
        from src.config.settings import Settings  # type: ignore
        from src.llm.client import build_client_from_settings  # type: ignore
        from src.indexing.pipeline import IndexingPipeline  # type: ignore

        settings = Settings()
        settings.chroma_db_path = str(_CHROMA_DIR)
        settings.raw_books_dir = str(_RAW_BOOKS_DIR)
        pipeline = IndexingPipeline(settings=settings, llm_client=build_client_from_settings(settings))

        result = pipeline._index_single_pdf(Path(pdf_path))

        # Stamp the admin-defined corpus_id/course_id onto this book's chunks so
        # scoped retrieval can find them (mirrors backfill_corpus_vector_tags).
        store = pipeline.store
        got = store.get_where(where={"book": book_stem}, include=[])
        ids = got.get("ids", []) if isinstance(got, dict) else []
        if ids:
            store.update_metadata(
                ids, [{"corpus_id": str(corpus_id), "course_id": str(course_id)} for _ in ids]
            )
        _set_status(corpus_id, book_stem, status="indexed",
                    chunks=len(ids), detail=f"new={result.get('new', 0)}")
        logger.info("corpus indexed", book=book_stem, corpus_id=corpus_id, chunks=len(ids))
    except Exception as exc:
        logger.exception("corpus index failed book=%s", book_stem)
        _set_status(corpus_id, book_stem, status="failed", detail=str(exc)[:300])
