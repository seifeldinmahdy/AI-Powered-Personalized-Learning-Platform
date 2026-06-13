"""Offline indexing pipeline orchestrator.

Processes every PDF in raw_books/, chunks it, analyzes each chunk via
the LLM, embeds with sentence-transformers, and stores in ChromaDB.
Fully resumable — skips chunks whose IDs already exist.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from src.config.settings import Settings
from src.indexing.analyzer import ChunkAnalyzer
from src.indexing.chunker import PDFChunker
from src.indexing.embedder import ChunkEmbedder
from src.indexing.store import VectorStore
from src.llm.client import OllamaCloudClient
from src.models.schemas import IndexedChunk, RawChunk

logger = structlog.get_logger(__name__)


class IndexingPipeline:
    """End-to-end indexing: PDF → chunks → analysis → embeddings → ChromaDB."""

    def __init__(
        self,
        settings: Settings,
        llm_client: OllamaCloudClient,
    ) -> None:
        self.settings = settings
        self.chunker = PDFChunker(
            embedding_model_name=settings.embedding_model,
            chunk_min=settings.chunk_min_tokens,
            chunk_max=settings.chunk_max_tokens,
            chunk_target=settings.chunk_size_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
        self.analyzer = ChunkAnalyzer(llm_client=llm_client)
        self.embedder = ChunkEmbedder(model_name=settings.embedding_model)
        self.store = VectorStore(
            persist_dir=settings.chroma_db_path,
            collection_name=settings.chroma_collection_name,
        )

    # ── Public API ────────────────────────────────────────────────

    def run(self) -> dict[str, int]:
        """Index every PDF in ``raw_books_dir``.

        Returns a summary dict: ``{total_pdfs, total_chunks_new,
        total_chunks_skipped, total_errors}``.
        """
        books_dir = Path(self.settings.raw_books_dir)
        pdfs = sorted(books_dir.glob("*.pdf"))

        if not pdfs:
            logger.warning("no_pdfs_found", directory=str(books_dir))
            return {
                "total_pdfs": 0,
                "total_chunks_new": 0,
                "total_chunks_skipped": 0,
                "total_errors": 0,
            }

        logger.info("indexing_start", pdf_count=len(pdfs))

        stats = {
            "total_pdfs": len(pdfs),
            "total_chunks_new": 0,
            "total_chunks_skipped": 0,
            "total_errors": 0,
        }

        for pdf_path in pdfs:
            result = self._index_single_pdf(pdf_path)
            stats["total_chunks_new"] += result["new"]
            stats["total_chunks_skipped"] += result["skipped"]
            stats["total_errors"] += result["errors"]

        logger.info("indexing_complete", **stats)
        return stats

    # ── Single-PDF processing ─────────────────────────────────────

    def _index_single_pdf(self, pdf_path: Path) -> dict[str, int]:
        """Process one PDF end-to-end. Returns counts for new/skipped/errors."""
        book_stem = pdf_path.stem
        course = book_stem  # Default: filename stem = course name
        # BATCH 4 (corpus-aware ingestion): chunks must be tagged at index time
        # with the admin-defined corpus_id + course_id (and concept_id, which
        # becomes non-optional) instead of overloading the filename as `course`.
        # Until then, the `backfill_corpus_vector_tags` management command stamps
        # corpus_id/course_id onto these chunks so RetrievalService can scope them.

        logger.info("pdf_processing_start", book=book_stem, path=str(pdf_path))

        # 1. Chunk
        raw_chunks = self.chunker.chunk_pdf(pdf_path, book_stem)
        if not raw_chunks:
            logger.warning("pdf_no_chunks", book=book_stem)
            return {"new": 0, "skipped": 0, "errors": 0}

        # 2. Filter already-indexed (resumability)
        all_ids = [c.chunk_id for c in raw_chunks]
        existing_ids = self.store.get_existing_ids(all_ids)
        new_chunks = [c for c in raw_chunks if c.chunk_id not in existing_ids]
        skipped = len(existing_ids)

        if skipped:
            logger.info(
                "chunks_skipped_existing",
                book=book_stem,
                skipped=skipped,
            )

        if not new_chunks:
            logger.info("pdf_fully_indexed", book=book_stem)
            return {"new": 0, "skipped": skipped, "errors": 0}

        logger.info(
            "chunks_to_process",
            book=book_stem,
            new=len(new_chunks),
            total=len(raw_chunks),
        )

        # 3. LLM analysis (sequential, one call per chunk)
        analyzed: list[tuple[RawChunk, dict]] = []
        errors = 0
        for i, chunk in enumerate(new_chunks):
            try:
                logger.info(
                    "analyzing_chunk",
                    book=book_stem,
                    progress=f"{i + 1}/{len(new_chunks)}",
                    chunk_id=chunk.chunk_id,
                )
                metadata = self.analyzer.analyze(
                    chunk_text=chunk.text,
                    chunk_id=chunk.chunk_id,
                )
                analyzed.append((chunk, metadata.model_dump()))
            except Exception as exc:
                errors += 1
                logger.error(
                    "chunk_analysis_failed",
                    chunk_id=chunk.chunk_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        if not analyzed:
            return {"new": 0, "skipped": skipped, "errors": errors}

        # 4. Batch embed
        texts = [chunk.text for chunk, _ in analyzed]
        embeddings = self.embedder.embed_batch(texts)

        # 5. Build IndexedChunk objects
        indexed_chunks: list[IndexedChunk] = []
        for (chunk, meta), embedding in zip(analyzed, embeddings):
            indexed_chunks.append(
                IndexedChunk(
                    chunk_id=chunk.chunk_id,
                    raw_text=chunk.text,
                    embedding=embedding,
                    topic=meta["topic"],
                    difficulty=meta["difficulty"],
                    is_definitional=meta["is_definitional"],
                    depends_on=meta["depends_on"],
                    summary=meta["summary"],
                    book=book_stem,
                    course=course,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_index=chunk.chunk_index,
                )
            )

        # 6. Store in ChromaDB (batch)
        self.store.add_chunks(indexed_chunks)

        logger.info(
            "pdf_processing_complete",
            book=book_stem,
            new_stored=len(indexed_chunks),
            errors=errors,
        )
        return {
            "new": len(indexed_chunks),
            "skipped": skipped,
            "errors": errors,
        }
