"""Shared Postgres/Supabase plumbing for the ai_service-native stores.

The student-context, profile-audit, and session-event stores can each be moved
from their local file/SQLite form to the shared Supabase Postgres (the SAME
project + DSN that hosts the corpus vectors and the pathway plans). This module
centralizes the three things they all need — DSN resolution, the psycopg2 import
guard, and a short-lived per-operation cursor — so each store stays small and
they never drift apart.

Connection model mirrors the pgvector/plan stores: read the pooled DSN from
``SUPABASE_DB_URL`` (or ``VECTOR_DB_URL``), open one short-lived connection per
operation, and let the Supabase pooler (port 6543) absorb the churn.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import structlog

logger = structlog.get_logger(__name__)


def resolve_dsn() -> str:
    """Return the Supabase Postgres DSN, or raise with actionable guidance."""
    dsn = os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")
    if not dsn:
        raise RuntimeError(
            "A Supabase-backed store is enabled but neither SUPABASE_DB_URL nor "
            "VECTOR_DB_URL is configured. Set it to your Supabase Postgres "
            "connection string (use the pooled URI, port 6543)."
        )
    return dsn


def import_psycopg():
    """Import psycopg2 lazily with a clear install hint on failure."""
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # noqa: F401  (registers adapters)
        return psycopg2
    except Exception as exc:  # pragma: no cover - import-time guidance
        raise RuntimeError(
            "This Supabase-backed store needs psycopg2. Install it with "
            "`pip install psycopg2-binary` in the ai_service environment."
        ) from exc


@contextmanager
def pg_cursor(dsn: str, commit: bool = False):
    """Yield a cursor on a fresh short-lived connection; close it afterwards."""
    psycopg2 = import_psycopg()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()
