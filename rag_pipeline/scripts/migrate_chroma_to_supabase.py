"""Copy every course chunk from the local ChromaDB into Supabase/pgvector.

One-time migration so an already-indexed local corpus becomes the shared corpus.
Reads directly from Chroma (bypassing the backend selector) and writes verbatim
to pgvector — preserving the FULL metadata (corpus_id / course_id / concept_id
stamped after indexing), which a plain re-index would not carry.

Usage (from the rag_pipeline/ directory):

    # 1. create the schema first (Supabase SQL editor): sql/pgvector_setup.sql
    # 2. point at your Supabase DB and run:
    set SUPABASE_DB_URL=postgresql://...:6543/postgres?sslmode=require   # PowerShell: $env:SUPABASE_DB_URL=...
    python scripts/migrate_chroma_to_supabase.py

Options:
    --chroma-dir DIR     local Chroma path (default: $CHROMA_DB_PATH or ./data/chroma)
    --collection NAME    collection/table name (default: $CHROMA_COLLECTION_NAME or course_chunks)
    --batch N            rows per batch (default: 500)

Idempotent: re-running upserts by id (no duplicates).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `src` importable when run from rag_pipeline/.
_RAG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAG_ROOT))


def _load_env() -> None:
    """Load rag_pipeline/.env so config lives in the file, not the shell.

    Nothing else in rag_pipeline auto-loads dotenv, so without this the script
    would only see shell variables. We do NOT override variables already set in
    the environment (override=False), so an explicit `set SUPABASE_DB_URL=...`
    still wins if you want it to.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return  # python-dotenv not installed → fall back to shell env only
    load_dotenv(_RAG_ROOT / ".env")


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chroma-dir", default=os.getenv("CHROMA_DB_PATH", "./data/chroma"))
    ap.add_argument("--collection", default=os.getenv("CHROMA_COLLECTION_NAME", "course_chunks"))
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    if not (os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")):
        print("ERROR: set SUPABASE_DB_URL (or VECTOR_DB_URL) to your Supabase connection string.")
        return 2

    if not Path(args.chroma_dir).exists():
        print(f"ERROR: local Chroma directory not found: {args.chroma_dir}")
        return 2

    import chromadb
    from src.indexing.pgvector_store import PgVectorStore

    client = chromadb.PersistentClient(path=args.chroma_dir)
    col = client.get_or_create_collection(
        name=args.collection, metadata={"hnsw:space": "cosine"},
    )
    total = col.count()
    print(f"Source Chroma collection '{args.collection}': {total} chunks")
    if total == 0:
        print("Nothing to migrate.")
        return 0

    dest = PgVectorStore(collection_name=args.collection)

    migrated = 0
    offset = 0
    while offset < total:
        batch = col.get(
            limit=args.batch, offset=offset,
            include=["embeddings", "documents", "metadatas"],
        )
        ids = batch.get("ids")
        if ids is None or len(ids) == 0:
            break
        # NB: Chroma returns embeddings as a numpy array, so `x or default`
        # would force an ambiguous array truth-value check. Use explicit
        # None checks and normalize each row to a plain list.
        documents = batch.get("documents")
        if documents is None:
            documents = [""] * len(ids)
        embeddings = batch.get("embeddings")
        if embeddings is None:
            embeddings = []
        metadatas = batch.get("metadatas")
        if metadatas is None:
            metadatas = [{}] * len(ids)
        dest.upsert_raw(
            ids,
            documents,
            [list(e) for e in embeddings],
            metadatas,
        )
        migrated += len(ids)
        offset += len(ids)
        print(f"  migrated {migrated}/{total}")

    print(f"Done. Upserted {migrated} chunks into Supabase table '{dest.table}'.")
    print("Now set VECTOR_BACKEND=supabase + SUPABASE_DB_URL in each service's .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
