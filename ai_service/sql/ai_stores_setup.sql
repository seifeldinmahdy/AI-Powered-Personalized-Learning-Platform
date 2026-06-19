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

-- ── Profiling-claim audit log (one row per entry; capped + digest roll-up) ──
CREATE TABLE IF NOT EXISTS profile_audit (
    id              BIGSERIAL   PRIMARY KEY,
    student_id      TEXT        NOT NULL,
    session_id      TEXT        NOT NULL DEFAULT '',
    session_type    TEXT        NOT NULL DEFAULT '',
    summary_written TEXT        NOT NULL DEFAULT '',
    claims          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    written_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS profile_audit_student_id ON profile_audit (student_id, id);

-- Rows beyond PROFILE_AUDIT_MAX_ROWS per student roll up here (compressed),
-- so the audit trail stays bounded without losing that older consolidations ran.
CREATE TABLE IF NOT EXISTS profile_audit_digest (
    student_id          TEXT        PRIMARY KEY,
    rolled_entries      INTEGER     NOT NULL DEFAULT 0,
    rolled_claims       INTEGER     NOT NULL DEFAULT 0,
    earliest_at         TIMESTAMPTZ,
    latest_at           TIMESTAMPTZ,
    session_type_counts JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Durable session-event log (live-session signal; consume + emotion purge) ──
CREATE TABLE IF NOT EXISTS session_events (
    id          BIGSERIAL   PRIMARY KEY,
    session_id  TEXT        NOT NULL,
    student_id  TEXT        NOT NULL DEFAULT '',
    course_id   TEXT        NOT NULL DEFAULT '',
    event_type  TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    consumed    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_session_events_sid
    ON session_events (session_id, consumed, id);
