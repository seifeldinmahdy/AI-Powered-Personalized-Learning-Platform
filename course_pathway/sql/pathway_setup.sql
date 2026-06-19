-- Supabase / Postgres schema for the course-pathway PLAN store.
--
-- Run this once in the Supabase SQL editor (or via psql) against the SAME
-- project that hosts the corpus vectors. Mirrors the SQLite tables in
-- course_pathway/src/pathway/storage/plan_store.py 1:1, with is_current as a
-- real boolean and the JSON payloads kept as text (stored verbatim from
-- SessionPlan.model_dump_json()).
--
-- Idempotent: safe to re-run. The PgPlanStore also auto-creates these on first
-- use if the role has DDL rights; this file is the manual fallback.

CREATE TABLE IF NOT EXISTS session_plans_v2 (
    student_id        TEXT    NOT NULL,
    course_id         TEXT    NOT NULL,
    plan_version      INTEGER NOT NULL,
    plan_json         TEXT    NOT NULL,
    context_hash      TEXT    NOT NULL,
    raw_proposal_hash TEXT    NOT NULL DEFAULT '',
    is_current        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TEXT    NOT NULL,
    PRIMARY KEY (student_id, course_id, plan_version)
);

-- Fast lookup of "the current plan for a student+course" and "all current
-- plans for a student" (list_plans), which are the hot read paths.
CREATE INDEX IF NOT EXISTS session_plans_v2_current
    ON session_plans_v2 (student_id, course_id)
    WHERE is_current;

CREATE TABLE IF NOT EXISTS curriculum_proposals (
    course_id      TEXT NOT NULL,
    corpus_id      TEXT NOT NULL,
    input_hash     TEXT NOT NULL,
    proposal_hash  TEXT NOT NULL,
    proposal_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (course_id, corpus_id)
);
