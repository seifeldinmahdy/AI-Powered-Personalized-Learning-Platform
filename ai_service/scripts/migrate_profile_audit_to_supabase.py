"""Copy every profiling-claim audit log from local JSON into Supabase/Postgres.

One-time migration so the locally-written audit trail becomes the shared,
server-side store. Reads ``data/profile_audit/{student_id}/audit.json`` directly
(bypassing the backend selector) and inserts each entry as a row in
``profile_audit`` (verbatim — no cap/roll-up during migration, so history is
preserved; the cap applies to future writes).

Usage (from the ai_service/ directory):

    # 1. create the schema (Supabase SQL editor): sql/ai_stores_setup.sql
    #    (or let PgProfileAuditStore auto-create it on first connect)
    # 2. set the SAME pooled DSN you use for the corpus vectors:
    #    PowerShell:  $env:SUPABASE_DB_URL="postgresql://...:6543/postgres?sslmode=require"
    # 3. run:
    python scripts/migrate_profile_audit_to_supabase.py

Options:
    --dir PATH   audit dir (default: ai_service/data/profile_audit)
"""

from __future__ import annotations

import argparse
import json
import os
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
    ap.add_argument("--dir", default=str(_AI_ROOT / "data" / "profile_audit"))
    args = ap.parse_args()

    if not (os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")):
        print("ERROR: set SUPABASE_DB_URL (or VECTOR_DB_URL) to your Supabase connection string.")
        return 2

    audit_root = Path(args.dir)
    if not audit_root.exists():
        print(f"ERROR: audit dir not found: {audit_root}")
        return 2

    from services.pg_profile_audit_store import PgProfileAuditStore

    dest = PgProfileAuditStore()

    students = 0
    entries_migrated = 0
    for student_dir in sorted(p for p in audit_root.iterdir() if p.is_dir()):
        audit_path = student_dir / "audit.json"
        if not audit_path.exists():
            continue
        student_id = student_dir.name
        try:
            entries = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  SKIP {student_id}: unreadable ({exc})")
            continue
        if not isinstance(entries, list):
            continue
        for e in entries:
            dest.insert_raw(
                student_id,
                str(e.get("session_id", "")),
                str(e.get("session_type", "")),
                str(e.get("summary_written", "")),
                e.get("claims", []),
                str(e.get("written_at", "")),
            )
            entries_migrated += 1
        students += 1
        print(f"  migrated {student_id}: {len(entries)} entries")

    print(f"Done. Migrated {entries_migrated} entries across {students} students into Supabase.")
    print("Now set PROFILE_AUDIT_BACKEND=supabase (+ SUPABASE_DB_URL) in ai_service/.env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
