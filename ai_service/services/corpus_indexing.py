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


_store_singleton = None
_store_lock = threading.Lock()


def _store():
    """Cached VectorStore (Chroma or pgvector per VECTOR_BACKEND).

    Cached per process so we don't re-run schema-ensure and a COUNT, and re-open
    the pooler, on EVERY request — that connection churn is what overwhelms
    Supabase's pooler ("server closed the connection unexpectedly"). Each
    operation still opens its own short-lived connection via the store, so the
    shared singleton is safe across the threadpool.
    """
    global _store_singleton
    if _store_singleton is None:
        with _store_lock:
            if _store_singleton is None:
                _ensure_rag_path()
                from src.indexing.store import VectorStore  # type: ignore
                _store_singleton = VectorStore(
                    persist_dir=str(_CHROMA_DIR), collection_name=_COLLECTION,
                )
    return _store_singleton


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


def attach_book_to_corpus(
    book_stem: str, corpus_id: str, course_id: str = ""
) -> dict:
    """Add an already-indexed book to a corpus (fast membership patch).

    Returns ``indexed=False`` when the book has no chunks yet (caller should
    index it first); otherwise stamps the per-corpus membership flag. Concept
    extraction is NOT triggered here — it is a separate, admin-initiated step
    (see :func:`extract_concepts`) so it can never affect indexing status.
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
        # Record status so the index-status poll reports "indexed" (this fast path
        # bypasses _run_index/_try_attach_existing, which are the other places that
        # stamp status). Concept extraction is intentionally NOT triggered here —
        # it is a separate, admin-initiated step (see :func:`extract_concepts`) so
        # it can never affect indexing status.
        _set_status(corpus_id, book_stem, status="indexed",
                    chunks=len(ids), detail="attached (already indexed)")
        return {"attached": len(ids), "indexed": True, "status": "indexed"}
    except BaseException as exc:  # noqa: BLE001
        logger.warning("corpus attach failed", book=book_stem, error=str(exc))
        return {"attached": 0, "indexed": False, "detail": f"store error: {exc}"[:300]}


def merge_concept_tags(corpus_id: str, survivor_id: str, merge_ids: list[str]) -> dict:
    """Repoint chunk concept tags from *merge_ids* to *survivor_id*.

    When the admin merges duplicate concepts, the chunks tagged
    ``concept__<corpus_id> = <merged id>`` must move to the survivor so the
    concept→topics, CLO coverage and slide grounding follow the merge.
    """
    if not corpus_id or not survivor_id or not merge_ids:
        return {"retagged": 0}
    key = f"concept__{corpus_id}"
    try:
        store = _store()
    except BaseException as exc:  # noqa: BLE001
        logger.warning("merge tags: store unavailable", error=str(exc))
        return {"retagged": 0, "detail": f"store error: {exc}"[:200]}

    total = 0
    for mid in {str(m) for m in merge_ids if str(m) != str(survivor_id)}:
        try:
            res = store.get_where(
                where={"$and": [{f"corpus__{corpus_id}": "1"}, {key: str(mid)}]},
                include=[],
            )
        except BaseException as exc:  # noqa: BLE001
            logger.warning("merge tags: fetch failed", merged=mid, error=str(exc))
            continue
        ids = res.get("ids", []) or [] if isinstance(res, dict) else []
        if ids:
            store.update_metadata(ids, [{key: str(survivor_id)} for _ in ids])
            total += len(ids)
    logger.info("concept tags merged", corpus_id=corpus_id, survivor=survivor_id,
                merged=list(merge_ids), retagged=total)
    return {"retagged": total}


def list_concept_topics(corpus_id: str, concept_id: str) -> dict:
    """Distinct chunk topics under one concept, with chunk counts.

    A "big" concept (e.g. OOP) groups many fine-grained chunk topics (classes,
    encapsulation, …) — those are the chunks tagged ``concept__<corpus_id> =
    <concept_id>`` and still in the corpus (``corpus__<corpus_id> = "1"``). This
    surfaces them so an admin can pick a subset per CLO.

    Returns ``{"topics": [{"topic", "chunks"}], "total_chunks"}`` sorted by count.
    """
    if not corpus_id or not concept_id:
        return {"topics": [], "total_chunks": 0, "detail": "corpus_id and concept_id required"}
    try:
        store = _store()
        result = store.get_where(
            where={"$and": [
                {f"corpus__{corpus_id}": "1"},
                {f"concept__{corpus_id}": str(concept_id)},
            ]},
            include=["metadatas"],
        )
    except BaseException as exc:  # noqa: BLE001
        logger.warning("concept topics fetch failed", concept_id=concept_id, error=str(exc))
        return {"topics": [], "total_chunks": 0, "detail": f"store error: {exc}"[:200]}

    metadatas = result.get("metadatas") or [] if isinstance(result, dict) else []
    counts: Counter = Counter()
    for meta in metadatas:
        if not isinstance(meta, dict):
            continue
        topic = str(meta.get("topic") or "").strip()
        if topic and topic.lower() != "unknown":
            counts[topic] += 1
    topics = [{"topic": t, "chunks": n} for t, n in counts.most_common()]
    return {"topics": topics, "total_chunks": sum(counts.values())}


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


def _build_llm_client():
    """Build the rag_pipeline LLM client WITHOUT importing the indexing pipeline.

    Concept extraction only needs the LLM (to consolidate topics) plus the vector
    store (already cached in :func:`_store`). Keeping it independent of
    ``IndexingPipeline`` means extraction does not pull in the PDF/``fitz`` stack,
    so it works even when indexing can't, and can never fail for the same reason.
    """
    _ensure_rag_path()
    from src.config.settings import Settings  # type: ignore
    from src.llm.client import build_client_from_settings  # type: ignore

    settings = Settings()
    settings.chroma_db_path = str(_CHROMA_DIR)
    settings.raw_books_dir = str(_RAW_BOOKS_DIR)
    return build_client_from_settings(settings)


_concept_embedder = None
_concept_embedder_lock = threading.Lock()
_MIN_TAG_CONFIDENCE = 0.4


def _get_concept_embedder():
    """Lazy MiniLM embedder for topic→concept matching (same model as elsewhere)."""
    global _concept_embedder
    if _concept_embedder is None:
        with _concept_embedder_lock:
            if _concept_embedder is None:
                from sentence_transformers import SentenceTransformer  # type: ignore
                _concept_embedder = SentenceTransformer(
                    "sentence-transformers/all-MiniLM-L6-v2"
                )
    return _concept_embedder


def _fetch_course_concepts(course_id: str) -> list[dict]:
    """Fetch the course's concepts (id + label) from Django for tagging."""
    if not course_id:
        return []
    try:
        resp = requests.get(
            f"{_DJANGO_API_URL}/courses/courses/{int(course_id)}/concepts/",
            headers={"X-Service-Key": _INTERNAL_SERVICE_KEY} if _INTERNAL_SERVICE_KEY else {},
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning("concept fetch for tagging failed", status=resp.status_code)
            return []
        data = resp.json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        return [{"id": str(c["id"]), "label": c["label"]}
                for c in rows if isinstance(c, dict) and c.get("label")]
    except Exception:
        logger.exception("concept fetch for tagging errored")
        return []


def _norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def _tag_corpus_chunks(store, corpus_id: str, course_id: str) -> dict:
    """Semantically tag each corpus chunk with its best-matching concept.

    Writes ``concept__<corpus_id> = <concept_id>`` onto chunks so concept-keyed
    reads (CLO coverage, slide grounding, the concept→topics picker) work. This
    is the grounding step that turns a "big" concept into its set of topic-chunks.
    Runs HERE (ai_service) because the embedder + pgvector store live here; the
    Django venv lacks those deps, so its auto_tag path cannot do it.
    """
    concepts = _fetch_course_concepts(course_id)
    if not concepts:
        return {"tagged": 0, "concepts": 0}
    try:
        res = store.get_where({f"corpus__{corpus_id}": "1"}, include=["metadatas"])
    except BaseException as exc:  # noqa: BLE001
        logger.warning("tag: corpus chunk fetch failed", error=str(exc))
        return {"tagged": 0, "concepts": len(concepts)}

    ids = res.get("ids", []) or []
    metas = res.get("metadatas", []) or []
    if not ids:
        return {"tagged": 0, "concepts": len(concepts)}

    import numpy as np  # local: heavy, only needed when tagging
    from sklearn.metrics.pairwise import cosine_similarity

    embedder = _get_concept_embedder()
    labels = [c["label"] for c in concepts]
    norm_labels = [_norm_label(c["label"]) for c in concepts]
    label_emb = embedder.encode(labels, convert_to_numpy=True, show_progress_bar=False)

    topics = [str((m or {}).get("topic") or "").strip() for m in metas]
    uniq = sorted({t for t in topics if t and t.lower() != "unknown"})

    match_for: dict[str, str] = {}
    if uniq:
        q = embedder.encode(uniq, convert_to_numpy=True, show_progress_bar=False)
        sims = cosine_similarity(q, label_emb)
        for i, t in enumerate(uniq):
            nt = _norm_label(t)
            exact = next((concepts[j]["id"] for j, nl in enumerate(norm_labels) if nl and nl == nt), None)
            if exact:
                match_for[t] = exact
                continue
            j = int(np.argmax(sims[i]))
            if float(sims[i][j]) >= _MIN_TAG_CONFIDENCE:
                match_for[t] = concepts[j]["id"]

    key = f"concept__{corpus_id}"
    upd_ids: list[str] = []
    upd_metas: list[dict] = []
    for chunk_id, t in zip(ids, topics):
        concept_id = match_for.get(t)
        if concept_id:
            upd_ids.append(chunk_id)
            upd_metas.append({key: concept_id})
    if upd_ids:
        store.update_metadata(upd_ids, upd_metas)
    logger.info("corpus chunks tagged with concepts", corpus_id=corpus_id,
                tagged=len(upd_ids), concepts=len(concepts), topics=len(uniq))
    return {"tagged": len(upd_ids), "concepts": len(concepts)}


def extract_concepts(book_stem: str, corpus_id: str, course_id: str = "") -> dict:
    """Run concept extraction for an already-indexed book (manual, on-demand).

    Reads the book's chunk topics from the vector store, asks the LLM to
    consolidate near-duplicate topics into a deduplicated concept list, and
    persists the new concepts to Django (existing labels are skipped). This is
    fully separate from indexing — it never touches the vectors and does not need
    the PDF pipeline — so it can be re-run any time without re-embedding.
    """
    if not book_stem or not corpus_id:
        return {"ok": False, "detail": "book_stem and corpus_id required",
                "extracted": 0, "created": 0, "skipped": 0}
    try:
        store = _store()
        llm_client = _build_llm_client()
    except BaseException as exc:  # noqa: BLE001
        logger.exception("concept extraction setup failed", book=book_stem)
        return {"ok": False, "detail": f"setup error: {exc}"[:300],
                "extracted": 0, "created": 0, "skipped": 0}

    counts = _extract_and_create_concepts(store, book_stem, corpus_id, course_id, llm_client)
    # Ground the chunks: tag each with its best-matching concept so the
    # concept→topics picker, CLO coverage and slide grounding all have data.
    tagged = 0
    try:
        tag_result = _tag_corpus_chunks(store, corpus_id, course_id)
        tagged = tag_result.get("tagged", 0)
    except BaseException:  # noqa: BLE001 — tagging must not fail the extraction
        logger.exception("concept tagging failed", book=book_stem, corpus_id=corpus_id)
    logger.info("manual concept extraction completed", book=book_stem,
                corpus_id=corpus_id, course_id=course_id, tagged=tagged, **counts)
    return {"ok": True, "tagged": tagged, **counts}


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
        # Concept extraction is a separate, admin-initiated step (extract_concepts);
        # it is intentionally NOT fired here so it can never affect indexing status.
    except BaseException as exc:  # noqa: BLE001
        logger.exception("corpus index failed book=%s", book_stem)
        _set_status(corpus_id, book_stem, status="failed", detail=str(exc)[:300])
