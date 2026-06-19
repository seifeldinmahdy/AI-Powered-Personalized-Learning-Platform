"""Copy the durable session-event log from local SQLite into Supabase/Postgres.

One-time migration so in-flight / not-yet-consolidated session signal survives
the switch to the shared store. Reads ``data/session_events.db`` directly
(bypassing the backend selector) and inserts each row VERBATIM into
``session_events`` — preserving the ``consumed`` flag and ``created_at`` so the
consolidation idempotency and emotion-retention windows are unchanged.

Usage (from the ai_service/ directory):

    # 1. create the schema (Supabase SQL editor): sql/ai_stores_setup.sql
    #    (or let PgSessionEventLog auto-create it on first connect)
    # 2. set the SAME pooled DSN you use for the corpus vectors:
    #    PowerShell:  $env:SUPABASE_DB_URL="postgresql://...:6543/postgres?sslmode=require"
    # 3. run:
    python scripts/migrate_session_events_to_supabase.py

Options:
    --sqlite PATH   local event DB (default: ai_service/data/session_events.db)
    --batch N       rows per batch (default: 1000)

Idempotent caveat: re-running APPENDS (the log has no natural unique key besides
its autoincrement id). Run once, or truncate the Supabase table first.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

_AI_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AI_ROOT))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    env = _AI_ROOT / ".env"
    if env.exists():
        load_dotenv(env)


def main() -> int:
    _load_env()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite", default=str(_AI_ROOT / "data" / "session_events.db"))
    ap.add_argument("--batch", type=int, default=1000)
    args = ap.parse_args()

    if not (os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")):
        print("ERROR: set SUPABASE_DB_URL (or VECTOR_DB_URL) to your Supabase connection string.")
        return 2

    sqlite_path = args.sqlite
    if not Path(sqlite_path).exists():
        print(f"ERROR: local SQLite event DB not found: {sqlite_path}")
        return 2

    from services.pg_session_event_log import PgSessionEventLog

    src = sqlite3.connect(sqlite_path)
    dest = PgSessionEventLog()

    # Does the source table exist?
    has = src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='session_events'"
    ).fetchone()
    if not has:
        print("session_events: table not present in source — nothing to migrate.")
        return 0

    cur = src.execute(
        "SELECT session_id, student_id, course_id, event_type, payload, consumed, created_at "
        "FROM session_events ORDER BY id"
    )
    migrated = 0
    while True:
        chunk = cur.fetchmany(args.batch)
        if not chunk:
            break
        rows = [
            (
                r[0], r[1] or "", r[2] or "", r[3],
                r[4] or "{}",            # payload JSON string → ::jsonb
                bool(r[5]),              # consumed 0/1 → bool
                r[6],                    # created_at ISO → ::timestamptz
            )
            for r in chunk
        ]
        dest.insert_raw_batch(rows)
        migrated += len(rows)
        print(f"  migrated {migrated}")

    src.close()
    print(f"Done. Inserted {migrated} session-event rows into Supabase.")
    print("Now set SESSION_EVENTS_BACKEND=supabase (+ SUPABASE_DB_URL) in ai_service/.env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
