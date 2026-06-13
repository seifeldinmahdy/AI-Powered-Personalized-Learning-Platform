"""
Management command to bootstrap Concept records from existing lessons.

Usage:
    python manage.py bootstrap_concepts           # all courses
    python manage.py bootstrap_concepts --course 1  # one course

For each lesson, derives 1–3 concept slugs from the lesson title words and
creates Concept records, linking the lesson via M2M. Idempotent: skips
concept slugs that already exist for the course.
"""

import re
from django.core.management.base import BaseCommand
from apps.courses.models import Course, Lesson, Concept


def _slugify(text: str) -> str:
    """Simple slug: lowercase, keep alphanumeric + hyphens."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:60]


def _derive_concepts(lesson_title: str) -> list[dict]:
    """Return 1–3 concept dicts from a lesson title.
    Strategy: split on common delimiters, take meaningful words, build slugs.
    """
    # Strip leading numbers / ordinals (e.g. "01 – Introduction to ...")
    clean = re.sub(r"^[\d\s\-–:]+", "", lesson_title).strip()

    # Split on ":", "–", "-", "and", "&"
    parts = re.split(r"[:\-–&]|\band\b", clean, flags=re.IGNORECASE)
    concepts = []
    for part in parts[:3]:  # at most 3 per lesson
        part = part.strip()
        if len(part) < 3:
            continue
        slug = _slugify(part)
        if not slug:
            continue
        concepts.append({"label": part.title(), "slug": slug})

    # Fallback: use the whole title if nothing parsed
    if not concepts:
        slug = _slugify(clean)
        if slug:
            concepts.append({"label": clean.title(), "slug": slug})

    return concepts


class Command(BaseCommand):
    help = "Bootstrap Concept records from existing lessons (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--course",
            type=int,
            default=None,
            help="Course ID to bootstrap. Omit to process all courses.",
        )

    def handle(self, *args, **options):
        course_id = options.get("course")
        courses = Course.objects.all() if not course_id else Course.objects.filter(pk=course_id)

        if not courses.exists():
            self.stdout.write(self.style.WARNING("No courses found."))
            return

        total_created = 0
        total_skipped = 0

        for course in courses:
            self.stdout.write(f"\nCourse: {course.title} (id={course.id})")
            lessons = Lesson.objects.filter(module__course=course).order_by(
                "module__module_order", "lesson_order"
            )
            order_counter = 0
            for lesson in lessons:
                derived = _derive_concepts(lesson.title)
                for concept_data in derived:
                    existing = Concept.objects.filter(
                        course=course, slug=concept_data["slug"]
                    ).first()
                    if existing:
                        existing.lessons.add(lesson)
                        total_skipped += 1
                        self.stdout.write(
                            f"  SKIP existing concept: {concept_data['slug']}"
                        )
                    else:
                        concept = Concept.objects.create(
                            course=course,
                            label=concept_data["label"],
                            slug=concept_data["slug"],
                            order=order_counter,
                        )
                        concept.lessons.add(lesson)
                        order_counter += 1
                        total_created += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  CREATED concept: {concept.label} (slug={concept.slug})"
                            )
                        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created={total_created}, Skipped={total_skipped}."
            )
        )
