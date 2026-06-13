"""Backfill: migrate existing students' topic_performance into concept_mastery.

Batch 5 collapses the two parallel knowledge vocabularies onto ONE: Django
``concept_mastery`` (keyed by Concept.id). Existing students carry their
placement signal as ``topic_performance`` (free-text ChromaDB topic → score) in
the AI-service student-context JSON store. This command matches each topic to a
course Concept and seeds ``concept_mastery`` so nobody loses their placement
signal in the cutover.

It is idempotent and conservative: it only SEEDS a concept entry that is absent
or has no evidence yet — it never clobbers stronger, real evidence accumulated
from problem-sets/capstone. Unmatched topics are reported, not guessed.

Usage:
    python manage.py migrate_topic_performance_to_concepts --dry-run
    python manage.py migrate_topic_performance_to_concepts --min-confidence 0.6
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.courses.models import Concept
from apps.progress.models import StudentLearningProfile

from apps.courses.concept_match import build_matcher  # shared concept matcher


def _contexts_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[5]
    return repo_root / "ai_service" / "data" / "student_contexts"


class Command(BaseCommand):
    help = "Seed concept_mastery from existing students' topic_performance (one-time cutover)."

    def add_arguments(self, parser):
        parser.add_argument("--min-confidence", type=float, default=0.6)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        min_conf = opts["min_confidence"]
        dry = opts["dry_run"]

        ctx_dir = _contexts_dir()
        if not ctx_dir.exists():
            self.stdout.write(self.style.WARNING(f"No student-context dir at {ctx_dir}; nothing to do."))
            return

        files = sorted(ctx_dir.glob("*.json"))
        if not files:
            self.stdout.write("No student-context files found.")
            return

        total_seeded = 0
        total_unmatched = 0
        # cache matchers per course so we don't rebuild embeddings repeatedly
        matcher_cache: dict[str, object] = {}
        label_cache: dict[str, dict] = {}

        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  skip {f.name}: {e}"))
                continue

            profile = data.get("profile", {})
            student_id = profile.get("student_id")
            course_id = profile.get("course_id")
            tp = profile.get("topic_performance") or {}
            if not student_id or not course_id or not tp:
                continue

            if course_id not in matcher_cache:
                concepts = list(Concept.objects.filter(course_id=course_id))
                matcher_cache[course_id] = build_matcher(concepts)
                label_cache[course_id] = {str(c.id): c.label for c in concepts}
            matcher = matcher_cache[course_id]

            try:
                slp, _ = StudentLearningProfile.objects.get_or_create(student_id=int(student_id))
            except (ValueError, TypeError):
                self.stdout.write(self.style.WARNING(f"  skip {f.name}: bad student_id {student_id!r}"))
                continue

            cm = dict(slp.concept_mastery or {})
            seeded, unmatched = [], []
            for topic, score in tp.items():
                concept, conf = matcher.match(topic)
                if concept is None or conf < min_conf:
                    unmatched.append(topic)
                    continue
                key = str(concept.id)
                existing = cm.get(key)
                # Conservative: only seed if absent or evidence-less.
                if existing and int(existing.get("evidence", 0)) > 0:
                    continue
                cm[key] = {
                    "score": round(float(score), 4),
                    "evidence": 1,
                    "trend": "flat",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "linked_mistakes": [],
                }
                seeded.append(label_cache[course_id].get(key, key))

            total_seeded += len(seeded)
            total_unmatched += len(unmatched)
            if not dry and seeded:
                slp.concept_mastery = cm
                slp.save(update_fields=["concept_mastery"])

            self.stdout.write(
                f"  student={student_id} course={course_id}: "
                f"seeded={len(seeded)} unmatched={len(unmatched)}"
                + (f"  (unmatched: {', '.join(unmatched)})" if unmatched else "")
            )

        self.stdout.write(self.style.SUCCESS(
            f"{'[dry-run] ' if dry else ''}Done. {total_seeded} concept(s) "
            f"{'would be ' if dry else ''}seeded; {total_unmatched} topic(s) unmatched."
        ))
