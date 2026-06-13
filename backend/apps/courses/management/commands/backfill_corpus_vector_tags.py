"""Backfill: stamp existing ChromaDB chunks with their corpus_id / course_id.

This is the VECTOR half of the corpus backfill (the relational half — one
CourseCorpus per Course — is done by migration 0008). It is a deliberate,
idempotent OPERATIONAL step rather than part of the migration, because Django
migrations must not reach into ChromaDB (a separate datastore that may be absent
in some environments).

What it does, per (book_stem -> course) mapping:
  1. Ensures the course's CourseCorpus exists and a CorpusSource(book_stem) row.
  2. Finds every chunk whose ``book`` metadata == book_stem and merges
     ``corpus_id`` + ``course_id`` into its metadata via an in-place update
     (no re-embedding).

Mapping resolution:
  - Explicit: --map <book_stem>=<course_pk> (repeatable). REQUIRED when the
    collection holds more than one book or the project has more than one course
    (we refuse to guess book<->course links across courses).
  - Auto: if exactly one book and exactly one course exist, they are linked.

Usage:
    python manage.py backfill_corpus_vector_tags
    python manage.py backfill_corpus_vector_tags --map pythonlearn=3 --map dsbook=4
    python manage.py backfill_corpus_vector_tags --dry-run

Batch 4 breadcrumb: once corpus-aware INGESTION lands, new chunks will be tagged
at index time and this command becomes a one-off for legacy/pre-corpus data.
"""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.courses.models import Course, CourseCorpus, CorpusSource


def _load_vector_store():
    """Import the rag_pipeline VectorStore against the shared Chroma path."""
    repo_root = Path(__file__).resolve().parents[5]
    rag_dir = repo_root / "rag_pipeline"
    pathway_src = repo_root / "course_pathway" / "src"
    for p in (str(rag_dir), str(pathway_src)):
        if p not in sys.path:
            sys.path.insert(0, p)

    from pathway.config import get_settings  # type: ignore
    from src.indexing.store import VectorStore  # type: ignore

    settings = get_settings()
    store = VectorStore(
        persist_dir=settings.chroma_db_path,
        collection_name=settings.chroma_collection_name,
    )
    return store


class Command(BaseCommand):
    help = "Stamp existing ChromaDB chunks with corpus_id/course_id for their course."

    def add_arguments(self, parser):
        parser.add_argument(
            "--map", action="append", default=[], metavar="BOOK_STEM=COURSE_PK",
            help="Explicit book_stem -> course PK mapping (repeatable).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing to ChromaDB.",
        )

    def handle(self, *args, **opts):
        store = _load_vector_store()

        mapping = self._resolve_mapping(store, opts["map"])
        if not mapping:
            raise CommandError("No book_stem -> course mapping resolved. Use --map.")

        dry_run = opts["dry_run"]
        total = 0
        for book_stem, course_pk in mapping.items():
            try:
                course = Course.objects.get(pk=course_pk)
            except Course.DoesNotExist:
                raise CommandError(f"Course pk={course_pk} does not exist.")

            corpus, _ = CourseCorpus.objects.get_or_create(
                course=course, defaults={"name": course.title},
            )
            if not dry_run:
                CorpusSource.objects.get_or_create(
                    corpus=corpus, book_stem=book_stem,
                    defaults={"title": book_stem, "source_type": "pdf"},
                )

            count = self._retag(store, book_stem, corpus.corpus_id, str(course.pk), dry_run)
            total += count
            self.stdout.write(
                f"{'[dry-run] ' if dry_run else ''}book '{book_stem}' -> course "
                f"{course.pk} (corpus {corpus.corpus_id[:8]}…): {count} chunks"
            )

        self.stdout.write(self.style.SUCCESS(
            f"{'[dry-run] ' if dry_run else ''}Done. {total} chunks "
            f"{'would be ' if dry_run else ''}tagged."
        ))

    # ── helpers ──────────────────────────────────────────────────

    def _resolve_mapping(self, store, raw_map: list[str]) -> dict[str, str]:
        if raw_map:
            mapping: dict[str, str] = {}
            for item in raw_map:
                if "=" not in item:
                    raise CommandError(f"Bad --map '{item}'. Expected BOOK_STEM=COURSE_PK.")
                book_stem, course_pk = item.split("=", 1)
                mapping[book_stem.strip()] = course_pk.strip()
            return mapping

        # Auto-map only when unambiguous.
        books = store.get_all_metadata_values("book")
        courses = list(Course.objects.values_list("pk", flat=True))
        if len(books) == 1 and len(courses) == 1:
            self.stdout.write(
                f"Auto-mapping the only book '{books[0]}' to the only course {courses[0]}."
            )
            return {books[0]: str(courses[0])}

        raise CommandError(
            f"Ambiguous mapping: found {len(books)} book(s) {books} and "
            f"{len(courses)} course(s). Provide explicit --map BOOK_STEM=COURSE_PK."
        )

    def _retag(self, store, book_stem: str, corpus_id: str, course_id: str,
               dry_run: bool) -> int:
        res = store.get_where({"book": book_stem}, include=["metadatas"])
        ids = res.get("ids", []) or []
        metas = res.get("metadatas", []) or []
        if not ids:
            return 0
        if dry_run:
            return len(ids)

        merged = []
        for meta in metas:
            m = dict(meta or {})
            m["corpus_id"] = corpus_id
            m["course_id"] = course_id
            merged.append(m)
        store.update_metadata(ids, merged)
        return len(ids)
