"""Supabase / Postgres ``pgvector`` backend for the course-chunk vector store.

This is a drop-in replacement for the local ChromaDB :class:`VectorStore`
(``src/indexing/store.py``). It exposes the EXACT same method surface and the
same Chroma-shaped return values, so every consumer (the indexing pipeline,
``RetrievalService``, the pathway ``ChromaDBReader``, corpus indexing, and the
Django concept auto-tagger) works unchanged.

Why this exists
---------------
The local Chroma store is a single on-disk SQLite/HNSW directory. Each developer
has their own copy, so a corpus indexed by one teammate is invisible to the
others, and concurrent access to the local files is unsafe. Putting the vectors
in Supabase (managed Postgres + the ``vector`` extension) gives the whole team a
single shared, concurrently-accessible corpus.

Selection
---------
The active backend is chosen in ``store.py`` from the environment:
  - ``VECTOR_BACKEND=supabase`` (or ``pgvector``/``postgres``) → this store.
  - ``VECTOR_BACKEND=chroma`` (or unset with no DSN) → the local Chroma store.
  - Unset but ``SUPABASE_DB_URL``/``VECTOR_DB_URL`` present → this store (auto).

Connection
----------
Reads the DSN from ``SUPABASE_DB_URL`` (or ``VECTOR_DB_URL``). Use Supabase's
*pooled* connection string (the "Connection pooling" URI, port 6543) so many
processes/threads share the database safely. One short-lived connection is opened
per operation — simple and robust across threads/processes; the pooler absorbs
the churn.

Schema (see ``rag_pipeline/sql/pgvector_setup.sql``)::

    create extension if not exists vector;
    create table course_chunks (
        id        text primary key,
        document  text not null default '',
        embedding vector(384),
        metadata  jsonb not null default '{}'::jsonb
    );

``metadata`` mirrors the Chroma metadata dict 1:1 (same keys, ``depends_on``
kept as a JSON string), so a migration copies rows verbatim and readers are
unchanged.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Embedding dimensionality of the configured embedder (all-MiniLM-L6-v2 = 384).
# Only used for the auto-created table's vector column.
_EMBED_DIM = int(os.getenv("VECTOR_EMBEDDING_DIM", "384"))

# Per-process "schema ensured" latch so we attempt the idempotent DDL only once.
_schema_ready: set[str] = set()
_schema_lock = threading.Lock()


def resolve_dsn() -> str:
    dsn = os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")
    if not dsn:
        raise RuntimeError(
            "VECTOR_BACKEND is set to supabase/pgvector but neither SUPABASE_DB_URL "
            "nor VECTOR_DB_URL is configured. Set it to your Supabase Postgres "
            "connection string (use the pooled URI, port 6543)."
        )
    return dsn


def _import_psycopg():
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # noqa: F401  (registers dict/json adapters)
        return psycopg2
    except Exception as exc:  # pragma: no cover - import-time guidance
        raise RuntimeError(
            "The pgvector backend needs psycopg2. Install it with "
            "`pip install psycopg2-binary` in this service's environment."
        ) from exc


def _safe_table(name: str) -> str:
    """Sanitize a collection name into a safe SQL identifier (no injection)."""
    cleaned = "".join(c for c in (name or "") if c.isalnum() or c == "_")
    return cleaned or "course_chunks"


def _vec_literal(embedding: list[float]) -> str:
    """Render an embedding as a pgvector text literal: ``[v1,v2,...]``."""
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def _as_meta(value: Any) -> dict:
    """Coerce a jsonb column to a dict regardless of psycopg2's typecaster.

    psycopg2 normally decodes jsonb to a dict automatically, but if a build
    returns it as a raw string this keeps readers working.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _where_to_sql(where: dict[str, Any] | None) -> tuple[str, list[Any]]:
    """Translate a Chroma ``where`` clause into a SQL fragment + params.

    Supports exactly the shapes the codebase uses:
      - ``None`` → no filter.
      - ``{"$and": [{k: v}, ...]}`` → ``AND`` of equality predicates.
      - ``{k: v, ...}`` → ``AND`` of equality predicates (implicit AND).

    Comparison is on the JSON text projection (``metadata->>'k' = %s``). All
    filters in use key on string fields (corpus_id, course_id, book, topic,
    difficulty, concept_id), so text equality is exact. (Bool/number-valued
    filters are not used; they would need typed comparison.)
    """
    if not where:
        return "", []

    if "$and" in where:
        conditions = where["$and"]
    else:
        conditions = [{k: v} for k, v in where.items()]

    clauses: list[str] = []
    params: list[Any] = []
    for cond in conditions:
        for key, value in cond.items():
            clauses.append("metadata->>%s = %s")
            params.append(str(key))
            params.append(str(value))
    return " AND ".join(clauses), params


class PgVectorStore:
    """pgvector-backed implementation of the VectorStore interface."""

    def __init__(self, persist_dir: str | None = None,
                 collection_name: str = "course_chunks") -> None:
        # persist_dir is irrelevant for a remote store; accepted for signature
        # parity with the Chroma VectorStore so call sites need no changes.
        self._psycopg2 = _import_psycopg()
        self.table = _safe_table(collection_name)
        self._dsn = resolve_dsn()
        self._ensure_schema()
        logger.info("pgvector_store_ready", table=self.table, count=self.count)

    # ── Connection / schema ──────────────────────────────────────────

    @contextmanager
    def _cursor(self, commit: bool = False):
        conn = self._psycopg2.connect(self._dsn)
        try:
            with conn.cursor() as cur:
                yield cur
            if commit:
                conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Best-effort idempotent schema creation (once per process per table).

        If the role lacks DDL privileges, this logs a clear pointer to the setup
        SQL rather than crashing — the table can be created manually instead.
        """
        key = f"{self._dsn}::{self.table}"
        with _schema_lock:
            if key in _schema_ready:
                return
            try:
                with self._cursor(commit=True) as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    cur.execute(
                        f"CREATE TABLE IF NOT EXISTS {self.table} ("
                        "  id text PRIMARY KEY,"
                        "  document text NOT NULL DEFAULT '',"
                        f"  embedding vector({_EMBED_DIM}),"
                        "  metadata jsonb NOT NULL DEFAULT '{}'::jsonb"
                        ");"
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS {self.table}_metadata_gin "
                        f"ON {self.table} USING gin (metadata);"
                    )
                _schema_ready.add(key)
            except Exception as exc:
                logger.warning(
                    "pgvector_schema_ensure_failed",
                    table=self.table, error=str(exc),
                    hint="Run rag_pipeline/sql/pgvector_setup.sql against your Supabase DB.",
                )

    # ── Existence checks (resumability) ──────────────────────────────

    def get_existing_ids(self, chunk_ids: list[str]) -> set[str]:
        if not chunk_ids:
            return set()
        try:
            with self._cursor() as cur:
                cur.execute(
                    f"SELECT id FROM {self.table} WHERE id = ANY(%s)",
                    (list(chunk_ids),),
                )
                return {row[0] for row in cur.fetchall()}
        except Exception as exc:
            logger.warning("pgvector_existence_check_error", error=str(exc),
                           count=len(chunk_ids))
            return set()

    # ── Writes ───────────────────────────────────────────────────────

    def add_chunks(self, chunks: list) -> None:
        """Batch upsert IndexedChunk objects (mirrors Chroma metadata exactly)."""
        if not chunks:
            return
        rows = [
            (
                c.chunk_id,
                c.raw_text,
                _vec_literal(c.embedding),
                json.dumps({
                    "topic": c.topic,
                    "difficulty": c.difficulty,
                    "is_definitional": c.is_definitional,
                    "depends_on": json.dumps(c.depends_on),
                    "summary": c.summary,
                    "book": c.book,
                    "course": c.course,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "chunk_index": c.chunk_index,
                }),
            )
            for c in chunks
        ]
        self._upsert_rows(rows)
        logger.info("pgvector_chunks_stored", count=len(chunks))

    def upsert_raw(self, ids: list[str], documents: list[str],
                   embeddings: list[list[float]], metadatas: list[dict]) -> None:
        """Verbatim upsert used by the Chroma→pgvector migration.

        Preserves the FULL existing metadata (incl. corpus_id/course_id/concept_id
        stamped post-index), which ``add_chunks`` alone would not carry.
        """
        rows = [
            (i, d or "", _vec_literal(e), json.dumps(m or {}))
            for i, d, e, m in zip(ids, documents, embeddings, metadatas)
        ]
        self._upsert_rows(rows)
        logger.info("pgvector_raw_upserted", count=len(rows))

    def _upsert_rows(self, rows: list[tuple]) -> None:
        if not rows:
            return
        sql = (
            f"INSERT INTO {self.table} (id, document, embedding, metadata) "
            "VALUES (%s, %s, %s::vector, %s::jsonb) "
            "ON CONFLICT (id) DO UPDATE SET "
            "document = EXCLUDED.document, "
            "embedding = EXCLUDED.embedding, "
            "metadata = EXCLUDED.metadata"
        )
        with self._cursor(commit=True) as cur:
            cur.executemany(sql, rows)

    def update_metadata(self, ids: list[str], metadatas: list[dict[str, Any]]) -> None:
        """Merge metadata keys onto existing rows (Chroma-style partial update).

        ``metadata = metadata || patch`` overrides the provided keys and keeps
        the rest, matching Chroma's ``collection.update`` merge semantics — this
        is what lets the corpus stamper add corpus_id/course_id/concept_id in
        place without re-indexing.
        """
        if not ids:
            return
        params = [(json.dumps(meta or {}), cid) for cid, meta in zip(ids, metadatas)]
        with self._cursor(commit=True) as cur:
            cur.executemany(
                f"UPDATE {self.table} SET metadata = metadata || %s::jsonb WHERE id = %s",
                params,
            )
        logger.info("pgvector_metadata_updated", count=len(ids))

    # ── Reads / Queries ──────────────────────────────────────────────

    def query(self, embedding: list[float],
              filters: dict[str, Any] | None = None,
              top_k: int = 5) -> dict[str, Any]:
        """Cosine-distance KNN with an optional metadata filter.

        Returns the Chroma-shaped nested-list dict
        ``{ids, documents, metadatas, distances}`` (each a single-query list).
        """
        clause, params = _where_to_sql(filters)
        where_sql = f"WHERE {clause} " if clause else ""
        sql = (
            f"SELECT id, document, metadata, embedding <=> %s::vector AS distance "
            f"FROM {self.table} {where_sql}"
            "ORDER BY distance ASC LIMIT %s"
        )
        args = [_vec_literal(embedding), *params, int(top_k)]
        with self._cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        ids = [r[0] for r in rows]
        docs = [r[1] for r in rows]
        metas = [_as_meta(r[2]) for r in rows]
        dists = [float(r[3]) for r in rows]
        return {
            "ids": [ids],
            "documents": [docs],
            "metadatas": [metas],
            "distances": [dists],
        }

    def get_where(self, where: dict[str, Any] | None = None,
                  include: list[str] | None = None) -> dict[str, Any]:
        return self._fetch(where=where, ids=None, include=include)

    def get_by_ids(self, ids: list[str], where: dict[str, Any] | None = None,
                   include: list[str] | None = None) -> dict[str, Any]:
        if not ids:
            return {"ids": [], "documents": [], "metadatas": []}
        return self._fetch(where=where, ids=list(ids), include=include)

    def _fetch(self, *, where: dict[str, Any] | None, ids: list[str] | None,
               include: list[str] | None) -> dict[str, Any]:
        include = include if include is not None else ["documents", "metadatas"]
        want_docs = "documents" in include
        want_meta = "metadatas" in include

        cols = ["id"]
        cols.append("document" if want_docs else "'' AS document")
        cols.append("metadata" if want_meta else "'{}'::jsonb AS metadata")

        clause, params = _where_to_sql(where)
        conds = []
        args: list[Any] = []
        if ids is not None:
            conds.append("id = ANY(%s)")
            args.append(ids)
        if clause:
            conds.append(clause)
            args.extend(params)
        where_sql = f"WHERE {' AND '.join(conds)} " if conds else ""

        sql = f"SELECT {', '.join(cols)} FROM {self.table} {where_sql}"
        with self._cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()

        out: dict[str, Any] = {"ids": [r[0] for r in rows]}
        if want_docs:
            out["documents"] = [r[1] for r in rows]
        if want_meta:
            out["metadatas"] = [_as_meta(r[2]) for r in rows]
        return out

    def count_where(self, where: dict[str, Any] | None = None) -> int:
        clause, params = _where_to_sql(where)
        where_sql = f"WHERE {clause}" if clause else ""
        with self._cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self.table} {where_sql}", params)
            return int(cur.fetchone()[0])

    def get_all_metadata_values(self, field: str) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT metadata->>%s FROM {self.table} "
                "WHERE metadata ? %s",
                (field, field),
            )
            return sorted(str(r[0]) for r in cur.fetchall() if r[0] is not None)

    @property
    def count(self) -> int:
        try:
            with self._cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {self.table}")
                return int(cur.fetchone()[0])
        except Exception as exc:
            logger.warning("pgvector_count_failed", error=str(exc))
            return 0
