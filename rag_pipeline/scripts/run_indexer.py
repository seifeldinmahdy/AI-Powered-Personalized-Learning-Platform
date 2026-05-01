#!/usr/bin/env python3
"""CLI entry point for the offline indexing pipeline.

Usage:
    cd rag_pipeline/
    python -m scripts.run_indexer          # uses .env defaults
    RAW_BOOKS_DIR=./my_books python -m scripts.run_indexer  # override
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure project root is on sys.path regardless of how the script is invoked
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import get_settings
from src.llm.client import build_client_from_settings
from src.logger.setup import setup_logging
from src.indexing.pipeline import IndexingPipeline


def main() -> None:
    """Run the full indexing pipeline and print a summary."""
    setup_logging()

    settings = get_settings()
    llm_client = build_client_from_settings(settings)

    print("=" * 60)
    print("  RAG Indexing Pipeline")
    print("=" * 60)
    print(f"  Books directory : {Path(settings.raw_books_dir).resolve()}")
    print(f"  ChromaDB path   : {Path(settings.chroma_db_path).resolve()}")
    print(f"  Collection      : {settings.chroma_collection_name}")
    print(f"  Embedding model : {settings.embedding_model}")
    print(f"  LLM model       : {settings.ollama_model}")
    print(f"  Chunk size      : {settings.chunk_min_tokens}-{settings.chunk_max_tokens} tokens")
    print(f"  Overlap         : {settings.chunk_overlap_tokens} tokens")
    print("=" * 60)

    pipeline = IndexingPipeline(settings=settings, llm_client=llm_client)

    start = time.time()
    stats = pipeline.run()
    elapsed = time.time() - start

    print()
    print("=" * 60)
    print("  Indexing Complete")
    print("=" * 60)
    print(f"  PDFs processed     : {stats['total_pdfs']}")
    print(f"  New chunks indexed : {stats['total_chunks_new']}")
    print(f"  Chunks skipped     : {stats['total_chunks_skipped']}")
    print(f"  Errors             : {stats['total_errors']}")
    print(f"  Total time         : {elapsed:.1f}s")
    print(f"  Collection size    : {pipeline.store.count}")
    print("=" * 60)

    if stats["total_errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
