"""Supabase / Postgres backend for the profiling-claim AUDIT log.

Drop-in replacement for the per-student ``data/profile_audit/{id}/audit.json``
files written by ``profiler_service._write_audit_entry`` / read by
``get_audit_log``. The active backend is chosen there from the environment
(``PROFILE_AUDIT_BACKEND=supabase``).

Why normalize to rows
---------------------
The file form is one growing JSON array per student. In Postgres we store ONE
ROW per audit entry (``profile_audit``), which is far cheaper to append, query,
and trim than rewriting a blob each time.

Bloat control (two tiers)
-------------------------
1. Rolling cap: keep at most ``PROFILE_AUDIT_MAX_ROWS`` detailed rows per student
   (default 500 — same as the file cap).
2. Compress-on-eviction: rows beyond the cap are NOT just deleted — they are
   folded into a single per-student ``profile_audit_digest`` row (counts +
   date range), so the audit trail stays bounded without losing the fact that
   older consolidations happened. Each audit entry is itself written at the
   moment its claims were consolidated into the durable profile, so "evicted
   detailed row → digest" is exactly the compress-on-consolidation roll-up.

Isolation note: keyed by ``student_id`` exactly as passed; the API layer ensures
that id is the verified, authenticated student (Track 1).
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

import structlog

from services.pg_common import import_psycopg, pg_cursor, resolve_dsn

logger = structlog.get_logger(__name__)

_schema_ready: set[str] = set()
_schema_lock = threading.Lock()

# Max detailed rows kept per student before older ones roll up into the digest.
_MAX_ROWS = int(os.getenv("PROFILE_AUDIT_MAX_ROWS", "500"))

_DDL_AUDIT = """
CREATE TABLE IF NOT EXISTS profile_audit (
    id              BIGSERIAL   PRIMARY KEY,
    student_id      TEXT        NOT NULL,
    session_id      TEXT        NOT NULL DEFAULT '',
    session_type    TEXT        NOT NULL DEFAULT '',
    summary_written TEXT        NOT NULL DEFAULT '',
    claims          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    written_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DDL_AUDIT_INDEX = """
CREATE INDEX IF NOT EXISTS profile_audit_student_id ON profile_audit (student_id, id);
"""

_DDL_DIGEST = """
CREATE TABLE IF NOT EXISTS profile_audit_digest (
    student_id          TEXT        PRIMARY KEY,
    rolled_entries      INTEGER     NOT NULL DEFAULT 0,
    rolled_claims       INTEGER     NOT NULL DEFAULT 0,
    earliest_at         TIMESTAMPTZ,
    latest_at           TIMESTAMPTZ,
    session_type_counts JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PgProfileAuditStore:
    """Postgres-backed profiling-claim audit log with cap + digest roll-up."""

    def __init__(self) -> None:
        import_psycopg()
        self._dsn = resolve_dsn()
        self._cap = max(1, _MAX_ROWS)
        self._ensure_schema()
        logger.info("pg_profile_audit_store_ready", backend="supabase", cap=self._cap)

    def _ensure_schema(self) -> None:
        key = self._dsn
        with _schema_lock:
            if key in _schema_ready:
                return
            try:
                with pg_cursor(self._dsn, commit=True) as cur:
                    cur.execute(_DDL_AUDIT)
                    cur.execute(_DDL_AUDIT_INDEX)
                    cur.execute(_DDL_DIGEST)
                _schema_ready.add(key)
            except Exception as exc:
                logger.warning(
                    "pg_profile_audit_schema_ensure_failed",
                    error=str(exc),
                    hint="Run ai_service/sql/ai_stores_setup.sql against your Supabase DB.",
                )

    # ── Write (append + cap/roll-up) ─────────────────────────────

    def write_entry(self, student_id: str, session_id: str, session_type: str,
                    claims: list[dict], summary: str = "") -> None:
        """Append one audit entry; roll the oldest over-cap rows into the digest."""
        import json
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "INSERT INTO profile_audit "
                "(student_id, session_id, session_type, summary_written, claims, written_at) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                (str(student_id), str(session_id or ""), str(session_type or ""),
                 (summary or "")[:300], json.dumps(claims or []),
                 datetime.now(timezone.utc)),
            )
            self._roll_up_overflow(cur, str(student_id))

    def _roll_up_overflow(self, cur, student_id: str) -> None:
        """Fold rows beyond the cap into the per-student digest, then delete them."""
        cur.execute("SELECT count(*) FROM profile_audit WHERE student_id=%s", (student_id,))
        total = int(cur.fetchone()[0])
        overflow = total - self._cap
        if overflow <= 0:
            return

        cur.execute(
            "SELECT id, session_type, claims, written_at FROM profile_audit "
            "WHERE student_id=%s ORDER BY id ASC LIMIT %s",
            (student_id, overflow),
        )
        rows = cur.fetchall()
        if not rows:
            return

        rolled_entries = len(rows)
        rolled_claims = sum(len(r[2] or []) for r in rows)
        earliest = min(r[3] for r in rows)
        latest = max(r[3] for r in rows)
        type_counts: dict[str, int] = {}
        for r in rows:
            t = r[1] or ""
            type_counts[t] = type_counts.get(t, 0) + 1

        # Merge into the existing digest (read-modify-write keeps the JSONB merge
        # simple and portable).
        cur.execute(
            "SELECT rolled_entries, rolled_claims, earliest_at, latest_at, session_type_counts "
            "FROM profile_audit_digest WHERE student_id=%s",
            (student_id,),
        )
        existing = cur.fetchone()
        if existing:
            rolled_entries += int(existing[0] or 0)
            rolled_claims += int(existing[1] or 0)
            if existing[2] is not None:
                earliest = min(earliest, existing[2])
            if existing[3] is not None:
                latest = max(latest, existing[3])
            merged = dict(existing[4] or {})
            for t, c in type_counts.items():
                merged[t] = int(merged.get(t, 0)) + c
            type_counts = merged

        import json
        cur.execute(
            "INSERT INTO profile_audit_digest "
            "(student_id, rolled_entries, rolled_claims, earliest_at, latest_at, "
            " session_type_counts, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s) "
            "ON CONFLICT (student_id) DO UPDATE SET "
            "    rolled_entries      = EXCLUDED.rolled_entries, "
            "    rolled_claims       = EXCLUDED.rolled_claims, "
            "    earliest_at         = EXCLUDED.earliest_at, "
            "    latest_at           = EXCLUDED.latest_at, "
            "    session_type_counts = EXCLUDED.session_type_counts, "
            "    updated_at          = EXCLUDED.updated_at",
            (student_id, rolled_entries, rolled_claims, earliest, latest,
             json.dumps(type_counts), datetime.now(timezone.utc)),
        )

        ids = [r[0] for r in rows]
        cur.execute("DELETE FROM profile_audit WHERE id = ANY(%s)", (ids,))
        logger.info("pg_profile_audit_rolled_up", student_id=student_id, rolled=len(ids))

    # ── Read ─────────────────────────────────────────────────────

    def get_log(self, student_id: str, limit: int = 20) -> list[dict]:
        """Return the most recent ``limit`` detailed entries, oldest-first within
        the window (matches the file store's ``entries[-limit:]`` shape)."""
        try:
            with pg_cursor(self._dsn) as cur:
                cur.execute(
                    "SELECT written_at, session_id, session_type, summary_written, claims "
                    "FROM ("
                    "  SELECT id, written_at, session_id, session_type, summary_written, claims "
                    "  FROM profile_audit WHERE student_id=%s ORDER BY id DESC LIMIT %s"
                    ") t ORDER BY id ASC",
                    (str(student_id), int(limit)),
                )
                rows = cur.fetchall()
        except Exception as exc:
            logger.warning("pg_profile_audit_get_failed", student_id=student_id, error=str(exc))
            return []
        out = []
        for written_at, session_id, session_type, summary, claims in rows:
            out.append({
                "written_at": written_at.isoformat() if hasattr(written_at, "isoformat") else str(written_at),
                "session_id": session_id,
                "session_type": session_type,
                "summary_written": summary,
                "claims": claims or [],
            })
        return out

    # ── Verbatim upsert used by the file→Supabase migration ──────

    def insert_raw(self, student_id: str, session_id: str, session_type: str,
                   summary: str, claims: list[dict], written_at_iso: str) -> None:
        """Insert one historical entry verbatim (no cap/roll-up during migration)."""
        import json
        with pg_cursor(self._dsn, commit=True) as cur:
            cur.execute(
                "INSERT INTO profile_audit "
                "(student_id, session_id, session_type, summary_written, claims, written_at) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                (str(student_id), str(session_id or ""), str(session_type or ""),
                 (summary or "")[:300], json.dumps(claims or []),
                 written_at_iso or datetime.now(timezone.utc).isoformat()),
            )
