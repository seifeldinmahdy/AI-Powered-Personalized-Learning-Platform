"""Copy every student-context JSON file into Supabase/Postgres.

One-time migration so the locally-generated student contexts become the shared,
server-side store. Reads the files directly (bypassing the backend selector) and
upserts each verbatim into the ``student_contexts`` table.

Usage (from the ai_service/ directory):

    # 1. create the schema (Supabase SQL editor): sql/ai_stores_setup.sql
    #    (or let PgStudentContextStore auto-create it on first connect)
    # 2. set the SAME pooled DSN you use for the corpus vectors:
    #    PowerShell:  $env:SUPABASE_DB_URL="postgresql://...:6543/postgres?sslmode=require"
    # 3. run:
    python scripts/migrate_student_contexts_to_supabase.py

Options:
    --dir PATH   contexts dir (default: ai_service/data/student_contexts)

Idempotent: re-running upserts by (student_id, course_id). The key for each row
is taken from the context's own profile ids when present, falling back to the
filename ``{student_id}_{course_id}.json`` — exactly how the file store keys it.
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


def _key_for(path: Path, data: dict) -> tuple[str, str] | None:
    """Resolve (student_id, course_id) — prefer the in-file profile ids, which
    are authoritative and unambiguous; fall back to splitting the filename on the
    LAST underscore (matches the file store's ``{student}_{course}`` key)."""
    profile = (data or {}).get("profile") or {}
    sid = str(profile.get("student_id") or "").strip()
    cid = str(profile.get("course_id") or "").strip()
    if sid and cid:
        return sid, cid
    stem = path.stem
    if "_" in stem:
        sid, cid = stem.rsplit("_", 1)
        return sid, cid
    return None


def main() -> int:
    _load_env()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=str(_AI_ROOT / "data" / "student_contexts"))
    args = ap.parse_args()

    if not (os.getenv("SUPABASE_DB_URL") or os.getenv("VECTOR_DB_URL")):
        print("ERROR: set SUPABASE_DB_URL (or VECTOR_DB_URL) to your Supabase connection string.")
        return 2

    ctx_dir = Path(args.dir)
    if not ctx_dir.exists():
        print(f"ERROR: contexts dir not found: {ctx_dir}")
        return 2

    from services.pg_student_context_store import PgStudentContextStore

    dest = PgStudentContextStore()

    migrated = 0
    skipped = 0
    for path in sorted(ctx_dir.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as exc:
            print(f"  SKIP {path.name}: unreadable ({exc})")
            skipped += 1
            continue
        key = _key_for(path, data)
        if not key:
            print(f"  SKIP {path.name}: cannot resolve student/course id")
            skipped += 1
            continue
        student_id, course_id = key
        dest.upsert_raw(student_id, course_id, raw)
        migrated += 1
        print(f"  migrated {student_id}/{course_id}")

    print(f"Done. Upserted {migrated} contexts ({skipped} skipped) into Supabase.")
    print("Now set STUDENT_CONTEXT_BACKEND=supabase (+ SUPABASE_DB_URL) in ai_service/.env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
