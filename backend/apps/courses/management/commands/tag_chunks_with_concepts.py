"""Tag corpus chunks with their course Concept (concept_id metadata).

This realises the authoring chain CLO -> concept -> corpus chunks: it stamps
each chunk in a course's corpus with the best-matching ``Concept.id`` so the
backward-designed assessment generator and concept-keyed slide grounding can
retrieve "the chunks for this concept".

It is a deliberate, idempotent OPERATIONAL step (sibling of
``backfill_corpus_vector_tags``) — Django migrations must not reach into
ChromaDB, and index-time concept tagging is the deferred ingestion path.

CONDITION (Batch 5): this command MUST emit a coverage/confidence report you
review before it is considered done. It flags every concept that ends up with
ZERO chunks or only LOW-CONFIDENCE matches. Low-confidence chunks are left
UNTAGGED by default (raise/lower with --min-confidence); use --dry-run to
preview without writing.

Matching: normalized exact label match → difflib ratio → (optional)
sentence-transformer cosine if the lib is installed. Confidence is that score.

Usage:
    python manage.py tag_chunks_with_concepts <course_pk> --dry-run
    python manage.py tag_chunks_with_concepts <course_pk> --min-confidence 0.6
"""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.courses.models import Course, CourseCorpus, Concept
from apps.courses.concept_match import build_matcher


def _load_vector_store():
    repo_root = Path(__file__).resolve().parents[5]
    rag_dir = str(repo_root / "rag_pipeline")
    if rag_dir not in sys.path:
        sys.path.insert(0, rag_dir)
    from src.indexing.store import VectorStore  # type: ignore

    chroma_path = str(repo_root / "rag_pipeline" / "data" / "chroma")
    return VectorStore(persist_dir=chroma_path, collection_name="course_chunks")


class Command(BaseCommand):
    help = "Tag a course's corpus chunks with their Concept id (with a coverage report)."

    def add_arguments(self, parser):
        parser.add_argument("course_pk", type=int)
        parser.add_argument("--min-confidence", type=float, default=0.55,
                            help="Below this, a chunk is left UNTAGGED and reported.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        course_pk = opts["course_pk"]
        min_conf = opts["min_confidence"]
        dry = opts["dry_run"]

        try:
            course = Course.objects.get(pk=course_pk)
        except Course.DoesNotExist:
            raise CommandError(f"Course {course_pk} not found.")

        corpus = CourseCorpus.objects.filter(course=course).first()
        if not corpus:
            raise CommandError(f"Course {course_pk} has no corpus. Run backfill_corpus_vector_tags first.")

        concepts = list(Concept.objects.filter(course=course))
        if not concepts:
            raise CommandError(f"Course {course_pk} has no concepts to tag against.")

        store = _load_vector_store()
        # Scope to this corpus's chunks via the per-corpus membership flag
        # (corpus__<id> = "1"), so a shared book is tagged only where it's selected.
        membership_key = f"corpus__{corpus.corpus_id}"
        res = store.get_where({membership_key: "1"}, include=["metadatas"])
        ids = res.get("ids", []) or []
        metas = res.get("metadatas", []) or []
        if not ids:
            raise CommandError(
                f"Corpus {corpus.corpus_id} has no chunks. Index + attach the "
                f"book(s) for this course first."
            )

        matcher = build_matcher(concepts)

        # per-concept stats
        tagged: dict[str, int] = {str(c.id): 0 for c in concepts}
        confidence_sum: dict[str, float] = {str(c.id): 0.0 for c in concepts}
        low_conf = 0
        unmatched = 0
        upd_ids: list[str] = []
        upd_metas: list[dict] = []

        for cid, meta in zip(ids, metas):
            topic = (meta or {}).get("topic", "")
            concept, conf = matcher.match(topic)
            if concept is None or conf < min_conf:
                low_conf += 1 if concept is not None else 0
                unmatched += 1 if concept is None else 0
                continue
            key = str(concept.id)
            tagged[key] += 1
            confidence_sum[key] += conf
            # Per-corpus concept tag (concept__<corpus_id>), so the SAME shared
            # book can carry different concept tags in different courses. Merged
            # in place via update_metadata, preserving other corpora's tags.
            upd_ids.append(cid)
            upd_metas.append({f"concept__{corpus.corpus_id}": key})

        if not dry and upd_ids:
            store.update_metadata(upd_ids, upd_metas)

        # ── Coverage / confidence report ──────────────────────────
        self.stdout.write("")
        self.stdout.write(f"{'[dry-run] ' if dry else ''}Concept tagging — course {course_pk} "
                          f"(corpus {corpus.corpus_id[:8]}…), {len(ids)} chunks, "
                          f"min_confidence={min_conf}")
        self.stdout.write("-" * 72)
        zero, weak = [], []
        for c in concepts:
            key = str(c.id)
            n = tagged[key]
            avg = (confidence_sum[key] / n) if n else 0.0
            flag = ""
            if n == 0:
                flag = "  [!] ZERO CHUNKS"
                zero.append(c.label)
            elif avg < 0.7:
                flag = "  [!] low avg confidence"
                weak.append(c.label)
            self.stdout.write(f"  {c.label[:40]:<40} chunks={n:<4} avg_conf={avg:.2f}{flag}")
        self.stdout.write("-" * 72)
        self.stdout.write(f"  tagged={len(upd_ids)}  low_confidence_skipped={low_conf}  unmatched={unmatched}")
        if zero:
            self.stdout.write(self.style.WARNING(f"  CONCEPTS WITH ZERO CHUNKS ({len(zero)}): {', '.join(zero)}"))
        if weak:
            self.stdout.write(self.style.WARNING(f"  LOW-CONFIDENCE CONCEPTS ({len(weak)}): {', '.join(weak)}"))
        if zero or weak:
            self.stdout.write(self.style.WARNING(
                "  REVIEW REQUIRED: add/clarify sources or concept labels for the flagged concepts."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("  All concepts have confident chunk coverage."))
        if dry:
            self.stdout.write(self.style.NOTICE("  [dry-run] no metadata written."))
