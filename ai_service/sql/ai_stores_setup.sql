-- Supabase / Postgres schema for the ai_service-native stores.
--
-- Run once in the Supabase SQL editor (or via psql) against the SAME project
-- that hosts the corpus vectors and the pathway plans. Each store also
-- auto-creates its own table on first connect when the role has DDL rights;
-- this file is the manual fallback and the single place to see all schemas.
--
-- Idempotent: safe to re-run.

-- ── Student contexts (write-once, read-only; one row per student+course) ──
CREATE TABLE IF NOT EXISTS student_contexts (
    student_id   TEXT        NOT NULL,
    course_id    TEXT        NOT NULL,
    context_json TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, course_id)
);
