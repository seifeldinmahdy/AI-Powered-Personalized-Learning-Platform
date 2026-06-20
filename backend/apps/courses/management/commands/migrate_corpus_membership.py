"""One-time migration: legacy scalar corpus/concept stamps → per-corpus flags.

The corpus model moved from a single ``corpus_id`` (and ``concept_id``) stamped
on each chunk to PER-CORPUS membership/concept flags, so one book can belong to
many courses at once:

    corpus_id = "C"           ->  corpus__C  = "1"          (membership flag)
    concept_id = "K" (in C)   ->  concept__C = "K"          (per-corpus concept)

This converts existing chunks in place (metadata merge, no re-embedding). It is
idempotent — running it again is a no-op for already-migrated chunks — and
non-destructive: the legacy ``corpus_id`` / ``concept_id`` keys are left intact
as a fallback (retrieval reads the new keys first, the legacy ones second).

Usage:
    python manage.py migrate_corpus_membership            # apply
    python manage.py migrate_corpus_membership --dry-run  # report only
"""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand


def _load_vector_store():
    repo_root = Path(__file__).resolve().parents[5]
    rag_dir = str(repo_root / "rag_pipeline")
    if rag_dir not in sys.path:
        sys.path.insert(0, rag_dir)
    from src.indexing.store import VectorStore  # type: ignore

    chroma_path = str(repo_root / "rag_pipeline" / "data" / "chroma")
    return VectorStore(persist_dir=chroma_path, collection_name="course_chunks")


class Command(BaseCommand):
    help = "Convert legacy corpus_id/concept_id stamps to per-corpus membership flags."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing.")
        parser.add_argument("--batch", type=int, default=500,
                            help="update_metadata batch size (default 500).")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        batch = max(1, int(opts["batch"]))

        store = _load_vector_store()
        res = store.get_where(None, include=["metadatas"])
        ids = res.get("ids", []) or []
        metas = res.get("metadatas", []) or []

        upd_ids: list[str] = []
        upd_metas: list[dict] = []
        already = 0
        no_legacy = 0

        for cid, meta in zip(ids, metas):
            m = meta or {}
            corpus_id = str(m.get("corpus_id", "") or "")
            if not corpus_id:
                no_legacy += 1
                continue

            patch: dict[str, str] = {}
            mkey = f"corpus__{corpus_id}"
            if str(m.get(mkey, "")) != "1":
                patch[mkey] = "1"

            concept = str(m.get("concept_id", "") or "")
            if concept:
                ckey = f"concept__{corpus_id}"
                if str(m.get(ckey, "")) != concept:
                    patch[ckey] = concept

            if not patch:
                already += 1
                continue
            upd_ids.append(cid)
            upd_metas.append(patch)

        self.stdout.write(
            f"{'[dry-run] ' if dry else ''}chunks={len(ids)} to_migrate={len(upd_ids)} "
            f"already_migrated={already} no_legacy_corpus={no_legacy}"
        )

        if dry or not upd_ids:
            return

        for i in range(0, len(upd_ids), batch):
            store.update_metadata(upd_ids[i:i + batch], upd_metas[i:i + batch])
            self.stdout.write(f"  migrated {min(i + batch, len(upd_ids))}/{len(upd_ids)}")

        self.stdout.write(self.style.SUCCESS(f"Done. Migrated {len(upd_ids)} chunks."))
