"""Copy every generated session plan from the local SQLite store into Supabase.

One-time migration so an already-generated set of pathway plans becomes the
shared, server-side plan store. Reads directly from the SQLite file (bypassing
the backend selector) and writes the rows VERBATIM into Postgres — preserving
every plan version, the ``is_current`` flags, and the cached curriculum
proposals, which a re-generation would not reproduce identically.

Usage (from the course_pathway/ directory):

    # 1. create the schema first (Supabase SQL editor): sql/pathway_setup.sql
    #    (or let PgPlanStore auto-create it on first connect)
    # 2. set the SAME pooled DSN you use for the corpus vectors:
    #    PowerShell:  $env:SUPABASE_DB_URL="postgresql://...:6543/postgres?sslmode=require"
    # 3. run:
    python scripts/migrate_sqlite_to_supabase.py

Options:
    --sqlite PATH   local plan DB (default: $PATHWAY_SQLITE_DB_PATH or
                    course_pathway/data/session_plans.db)

Idempotent: re-running upserts by primary key (no duplicates). The DSN is read
from SUPABASE_DB_URL / VECTOR_DB_URL — the same variable the pgvector corpus
store uses, so one Supabase project hosts both.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Make `src` importable when run from course_pathway/.
_PATHWAY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PATHWAY_ROOT / "src"))


def _load_env() -> None:
    """Load the nearest .env so config lives in the file, not the shell.

    override=False: an explicit shell `SUPABASE_DB_URL` still wins if set.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    # Walk up to find a .env (course_pathway shares the repo-root / rag_pipeline one).
    here = _PATHWAY_ROOT
    for _ in range(6):
        candidate = here / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            return
        here = here.parent


def _default_sqlite_path() -> str:
    env = os.getenv("PATHWAY_SQLITE_DB_PATH")
    if env:
        return env
    return str(_PATHWAY_ROOT / "data" / "session_plans.db")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def main() -> int:
    _load_env()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite", default=_default_sqlite_path())
    args = ap.parse_args()

    if not (os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")):
        print("ERROR: set SUPABASE_DB_URL (or VECTOR_DB_URL) to your Supabase connection string.")
        return 2

    sqlite_path = args.sqlite
    if not Path(sqlite_path).exists():
        print(f"ERROR: local SQLite plan DB not found: {sqlite_path}")
        return 2

    from pathway.storage.pg_plan_store import PgPlanStore

    src = sqlite3.connect(sqlite_path)
    dest = PgPlanStore()

    # ── session_plans_v2 ─────────────────────────────────────────
    plans_migrated = 0
    if _table_exists(src, "session_plans_v2"):
        rows = src.execute(
            "SELECT student_id, course_id, plan_version, plan_json, context_hash, "
            "       raw_proposal_hash, is_current, created_at "
            "FROM session_plans_v2"
        ).fetchall()
        # SQLite stores is_current as 0/1; Postgres wants a real boolean.
        norm = [
            (r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6]), r[7])
            for r in rows
        ]
        dest.upsert_plan_rows(norm)
        plans_migrated = len(norm)
        print(f"session_plans_v2: migrated {plans_migrated} rows")
    else:
        print("session_plans_v2: table not present in source — skipped")

    # ── curriculum_proposals ─────────────────────────────────────
    proposals_migrated = 0
    if _table_exists(src, "curriculum_proposals"):
        rows = src.execute(
            "SELECT course_id, corpus_id, input_hash, proposal_hash, proposal_json, created_at "
            "FROM curriculum_proposals"
        ).fetchall()
        dest.upsert_proposal_rows(list(rows))
        proposals_migrated = len(rows)
        print(f"curriculum_proposals: migrated {proposals_migrated} rows")
    else:
        print("curriculum_proposals: table not present in source — skipped")

    src.close()

    print(
        f"Done. Upserted {plans_migrated} plan rows and {proposals_migrated} "
        f"proposal rows into Supabase."
    )
    print("Now set PATHWAY_BACKEND=supabase (+ SUPABASE_DB_URL) in each service's .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
