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

import os
import re
import sys
import threading
from collections import Counter
from pathlib import Path

import requests
import structlog

logger = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RAG_DIR = _REPO_ROOT / "rag_pipeline"
_RAW_BOOKS_DIR = _RAG_DIR / "raw_books"
_CHROMA_DIR = _RAG_DIR / "data" / "chroma"
_COLLECTION = "course_chunks"

_DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api").rstrip("/")
_INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

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
                # Membership is the per-corpus flag corpus__<id> = "1" (a book can
                # belong to many corpora), not a single stamped corpus_id.
                in_corpus[b] = store.count_where(
                    {"$and": [{"book": b}, {f"corpus__{corpus_id}": "1"}]}
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


# ── Book library: index once, attach to many corpora ─────────────────────────
#
# A book is INDEXED ONCE into the shared vector library (canonical chunks). It is
# then ATTACHED to a course's corpus by setting a per-corpus membership flag
# (``corpus__<corpus_id> = "1"``) on its chunks — a fast metadata patch, no
# re-embedding. The same book can be attached to many corpora at once. Detaching
# flips the flag to "0" (chunks stay in the DB for other courses); deleting a book
# removes its chunks entirely.

def _book_chunk_ids(store, book_stem: str) -> list[str]:
    got = store.get_where(where={"book": book_stem}, include=[])
    return got.get("ids", []) if isinstance(got, dict) else []


def _extract_concepts_from_attached_book(book_stem: str, corpus_id: str, course_id: str) -> None:
    """Background concept extraction for a book that is already indexed/attached.

    Builds the LLM client lazily in a thread so the attach response is instant.
    """
    def run() -> None:
        try:
            _ensure_rag_path()
            from src.config.settings import Settings  # type: ignore
            from src.llm.client import build_client_from_settings  # type: ignore
            from src.indexing.pipeline import IndexingPipeline  # type: ignore

            settings = Settings()
            settings.chroma_db_path = str(_CHROMA_DIR)
            settings.raw_books_dir = str(_RAW_BOOKS_DIR)
            pipeline = IndexingPipeline(
                settings=settings, llm_client=build_client_from_settings(settings)
            )
            store = pipeline.store
            llm_client = getattr(pipeline.analyzer, "llm", None)
            counts = _extract_and_create_concepts(
                store, book_stem, corpus_id, course_id, llm_client
            )
            logger.info(
                "auto concept extraction completed (attach)",
                book=book_stem,
                corpus_id=corpus_id,
                course_id=course_id,
                **counts,
            )
        except Exception:
            logger.exception("auto concept extraction failed (attach)", book=book_stem)

    threading.Thread(target=run, daemon=True).start()


def attach_book_to_corpus(
    book_stem: str, corpus_id: str, course_id: str = ""
) -> dict:
    """Add an already-indexed book to a corpus (fast membership patch).

    Returns ``indexed=False`` when the book has no chunks yet (caller should
    index it first); otherwise stamps the per-corpus membership flag. If
    ``course_id`` is provided and the attach succeeds, concept extraction is
    kicked off in the background.
    """
    if not book_stem or not corpus_id:
        return {"attached": 0, "indexed": False, "detail": "book_stem and corpus_id required"}
    try:
        store = _store()
        ids = _book_chunk_ids(store, book_stem)
        if not ids:
            return {"attached": 0, "indexed": False}
        store.update_metadata(ids, [{f"corpus__{corpus_id}": "1"} for _ in ids])
        logger.info("corpus book attached", book=book_stem, corpus_id=corpus_id, chunks=len(ids))
        if course_id:
            _extract_concepts_from_attached_book(book_stem, corpus_id, course_id)
        return {"attached": len(ids), "indexed": True}
    except BaseException as exc:  # noqa: BLE001
        logger.warning("corpus attach failed", book=book_stem, error=str(exc))
        return {"attached": 0, "indexed": False, "detail": f"store error: {exc}"[:300]}


def detach_book_from_corpus(book_stem: str, corpus_id: str) -> dict:
    """Remove a book from a corpus (membership → "0"); chunks STAY in the DB.

    This is what "remove the book from this course" does — it never deletes the
    book's vectors, so other courses using the same book are unaffected.
    """
    if not book_stem or not corpus_id:
        return {"detached": 0, "detail": "book_stem and corpus_id required"}
    try:
        store = _store()
        ids = _book_chunk_ids(store, book_stem)
        if ids:
            store.update_metadata(ids, [{f"corpus__{corpus_id}": "0"} for _ in ids])
    except Exception as exc:
        logger.warning("corpus detach failed", book=book_stem, error=str(exc))
        return {"detached": 0, "detail": str(exc)[:300]}
    with _status_lock:
        _status.pop(_status_key(corpus_id, book_stem), None)
    logger.info("corpus book detached", book=book_stem, corpus_id=corpus_id, chunks=len(ids))
    return {"detached": len(ids)}


def delete_book_entirely(book_stem: str) -> dict:
    """Delete a book's chunks from the vector DB entirely (admin library action).

    Removes the book for ALL corpora — use only when retiring a book from the
    library, not when removing it from a single course (that is a detach).
    """
    if not book_stem:
        return {"deleted": 0, "detail": "book_stem required"}
    try:
        store = _store()
        removed = store.delete_where({"book": book_stem})
    except Exception as exc:
        logger.warning("corpus delete_book failed", book=book_stem, error=str(exc))
        return {"deleted": 0, "detail": str(exc)[:300]}
    with _status_lock:
        for key in [k for k in _status if k.endswith(f":{book_stem}")]:
            _status.pop(key, None)
    logger.info("corpus book deleted from library", book=book_stem, removed=removed)
    return {"deleted": int(removed)}


# ── Auto concept extraction after indexing ───────────────────────────────────

_CONCEPT_EXTRACTION_SYSTEM = """\
You are a curriculum design expert. Given a list of topics extracted from textbook chunks, produce a concise list of core course concepts.

Rules:
- Consolidate near-duplicate topics into single concept labels.
- Each concept should be 1-4 words, suitable as a course learning unit.
- Produce between 4 and 12 concepts total.
- Return ONLY a valid JSON object in this exact format:
{"concepts": ["Concept 1", "Concept 2", ...]}
No markdown, no preamble.
"""


def _topic_candidates(store, book_stem: str, corpus_id: str) -> list[tuple[str, int]]:
    """Return the most common chunk topics for a book, with occurrence counts."""
    try:
        result = store.get_where(
            where={"$and": [{"book": book_stem}, {f"corpus__{corpus_id}": "1"}]},
            include=["metadatas"],
        )
    except Exception:
        logger.exception("topic fetch failed", book=book_stem)
        return []

    if not isinstance(result, dict):
        return []
    metadatas = result.get("metadatas") or []

    topics: list[str] = []
    for meta in metadatas:
        if not isinstance(meta, dict):
            continue
        topic = str(meta.get("topic") or "").strip()
        if topic and topic.lower() != "unknown":
            topics.append(topic)

    if not topics:
        return []
    return Counter(topics).most_common(30)


def _extract_and_create_concepts(
    store,
    book_stem: str,
    corpus_id: str,
    course_id: str,
    llm_client,
) -> dict[str, int]:
    """Extract concepts from chunk topics and persist them to Django."""
    candidates = _topic_candidates(store, book_stem, corpus_id)
    if not candidates:
        logger.info("no topics to extract concepts from", book=book_stem)
        return {"extracted": 0, "created": 0, "skipped": 0}

    if llm_client is None:
        logger.info("no llm client configured; skipping concept extraction", book=book_stem)
        return {"extracted": 0, "created": 0, "skipped": 0}

    topic_lines = "\n".join(f"- {topic} (count: {count})" for topic, count in candidates)
    prompt = (
        "TOPICS extracted from the indexed book:\n"
        f"{topic_lines}\n\n"
        "Produce 4-12 core concepts for the course. Return JSON with key 'concepts'."
    )

    try:
        response = llm_client.chat_json(
            messages=[
                {"role": "system", "content": _CONCEPT_EXTRACTION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
    except Exception:
        logger.exception("llm concept extraction failed", book=book_stem)
        return {"extracted": 0, "created": 0, "skipped": 0}

    if not isinstance(response, dict):
        logger.warning("unexpected concept extraction response type", book=book_stem, response=response)
        return {"extracted": 0, "created": 0, "skipped": 0}

    concepts = response.get("concepts")
    if not isinstance(concepts, list):
        logger.warning("missing concepts key in extraction response", book=book_stem, response=response)
        return {"extracted": 0, "created": 0, "skipped": 0}

    concepts = [re.sub(r"\s+", " ", str(c)).strip() for c in concepts if str(c).strip()]
    if not concepts:
        return {"extracted": 0, "created": 0, "skipped": 0}

    if not _INTERNAL_SERVICE_KEY:
        logger.warning(
            "INTERNAL_SERVICE_KEY not set; cannot persist extracted concepts",
            book=book_stem,
        )
        return {"extracted": len(concepts), "created": 0, "skipped": 0}

    if not course_id:
        logger.warning("course_id not provided; cannot persist extracted concepts", book=book_stem)
        return {"extracted": len(concepts), "created": 0, "skipped": 0}

    try:
        url = f"{_DJANGO_API_URL}/courses/courses/{int(course_id)}/concepts/bulk-extract/"
        resp = requests.post(
            url,
            headers={"X-Service-Key": _INTERNAL_SERVICE_KEY},
            json={"labels": concepts},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "extracted": len(concepts),
                "created": data.get("created", 0),
                "skipped": data.get("skipped", 0),
            }
        logger.warning(
            "bulk-extract endpoint returned error",
            book=book_stem,
            status=resp.status_code,
            body=resp.text[:200],
        )
    except Exception:
        logger.exception("bulk-extract request failed", book=book_stem)

    return {"extracted": len(concepts), "created": 0, "skipped": 0}


def _extract_concepts_async(
    store,
    book_stem: str,
    corpus_id: str,
    course_id: str,
    llm_client,
) -> None:
    """Kick off concept extraction in a background thread after indexing."""
    def run() -> None:
        try:
            counts = _extract_and_create_concepts(
                store, book_stem, corpus_id, course_id, llm_client
            )
            logger.info(
                "auto concept extraction completed",
                book=book_stem,
                course_id=course_id,
                **counts,
            )
        except Exception:
            logger.exception("auto concept extraction failed", book=book_stem)

    threading.Thread(target=run, daemon=True).start()


# ── Index a book into a corpus (background) ──────────────────────────────────


def _try_attach_existing(
    book_stem: str, corpus_id: str, course_id: str = ""
) -> dict | None:
    """Attach *book_stem* to *corpus_id* if it is already indexed.

    Returns the status dict on success, or ``None`` if the book is not indexed
    or the vector store is unavailable. Catches ``BaseException`` because some
    ChromaDB/Rust failures surface as ``pyo3_runtime.PanicException``.
    """
    try:
        store = _store()
        if _book_chunk_ids(store, book_stem):
            res = attach_book_to_corpus(book_stem, corpus_id, course_id)
            _set_status(corpus_id, book_stem, status="indexed",
                        chunks=res.get("attached", 0), detail="attached (already indexed)")
            return get_status(corpus_id, book_stem)
    except BaseException as exc:  # noqa: BLE001
        logger.warning("corpus attach precheck failed", book=book_stem, error=str(exc))
    return None


def start_indexing(book_stem: str, corpus_id: str, course_id: str = "") -> dict:
    """Make a book available to a corpus.

    If the book is already indexed, this just ATTACHES it to the corpus
    (instant, no re-embed) — that is the book-reuse path. Otherwise it kicks off
    background indexing of the PDF and attaches the corpus on completion.
    """
    pdf = _RAW_BOOKS_DIR / f"{book_stem}.pdf"
    if not pdf.exists():
        # The PDF may have been deleted after indexing; still try to reuse.
        attached = _try_attach_existing(book_stem, corpus_id, course_id)
        if attached:
            return attached
        _set_status(corpus_id, book_stem, status="failed", detail="PDF not found on disk")
        return get_status(corpus_id, book_stem)

    # PDF exists — reuse an already-indexed book instantly.
    attached = _try_attach_existing(book_stem, corpus_id, course_id)
    if attached:
        return attached

    cur = get_status(corpus_id, book_stem)
    if cur.get("status") == "indexing":
        return cur  # already running — idempotent
    _set_status(corpus_id, book_stem, status="indexing", detail="", chunks=0)
    threading.Thread(
        target=_run_index, args=(str(pdf), book_stem, str(corpus_id), str(course_id)),
        daemon=True,
    ).start()
    return get_status(corpus_id, book_stem)


def _run_index(
    pdf_path: str, book_stem: str, corpus_id: str = "", course_id: str = ""
) -> None:
    """Worker: index one PDF canonically, then attach it to *corpus_id* (if any).

    Indexing produces the book's canonical chunks (shared library). Corpus
    membership is a separate flag set afterwards, so the same chunks can later be
    attached to other corpora without re-indexing.
    """
    _ensure_rag_path()
    try:
        from src.config.settings import Settings  # type: ignore
        from src.llm.client import build_client_from_settings  # type: ignore
        from src.indexing.pipeline import IndexingPipeline  # type: ignore

        settings = Settings()
        settings.chroma_db_path = str(_CHROMA_DIR)
        settings.raw_books_dir = str(_RAW_BOOKS_DIR)
        pipeline = IndexingPipeline(settings=settings, llm_client=build_client_from_settings(settings))

        store = pipeline.store
        result = pipeline._index_single_pdf(Path(pdf_path))

        ids = _book_chunk_ids(store, book_stem)
        if ids and corpus_id:
            # Attach this corpus (membership flag). Does NOT overwrite any other
            # corpus's membership, so a shared book keeps all its memberships.
            store.update_metadata(ids, [{f"corpus__{corpus_id}": "1"} for _ in ids])
        _set_status(corpus_id, book_stem, status="indexed",
                    chunks=len(ids), detail=f"new={result.get('new', 0)}")
        logger.info("corpus indexed", book=book_stem, corpus_id=corpus_id, chunks=len(ids))
        # Fire-and-forget concept extraction; it must not delay the indexed response.
        _extract_concepts_async(
            store, book_stem, corpus_id, course_id, getattr(pipeline.analyzer, "llm", None)
        )
    except BaseException as exc:  # noqa: BLE001
        logger.exception("corpus index failed book=%s", book_stem)
        _set_status(corpus_id, book_stem, status="failed", detail=str(exc)[:300])
