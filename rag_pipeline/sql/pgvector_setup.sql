-- Supabase / Postgres pgvector setup for the SHARED course-chunk corpus.
-- Run this ONCE against your Supabase database (Dashboard → SQL Editor, or psql).
-- After it runs, set VECTOR_BACKEND=supabase + SUPABASE_DB_URL in each service's
-- .env and the whole team reads/writes one shared corpus.
--
-- The embedding dimension MUST match the embedder (all-MiniLM-L6-v2 = 384).
-- If you change EMBEDDING_MODEL, change vector(384) below and VECTOR_EMBEDDING_DIM.

create extension if not exists vector;

create table if not exists course_chunks (
    id        text primary key,
    document  text not null default '',
    embedding vector(384),
    metadata  jsonb not null default '{}'::jsonb
);

-- Metadata filters: corpus_id / course_id / book / topic / concept_id / difficulty.
-- This is the index the pathway/assessment/slide reads rely on (scope filtering).
create index if not exists course_chunks_metadata_gin
    on course_chunks using gin (metadata);

-- Cosine-distance ANN index for semantic search (RAG answers + tutor grounding).
-- HNSW needs no training and gives strong recall. Build it AFTER migrating data
-- for a faster initial build (it is still correct if built on an empty table).
-- Alternative for very large corpora: ivfflat (requires choosing `lists` + ANALYZE).
create index if not exists course_chunks_embedding_hnsw
    on course_chunks using hnsw (embedding vector_cosine_ops);
