"""Clean up a course's Concept list: drop obvious junk and merge exact duplicates.

- Junk: concepts whose label is ``Adaptive Session <n>`` (leftover pathway-session
  names that were inserted as concepts by an old import). These are deleted.
- Exact duplicates: concepts whose labels are identical after normalizing
  unicode dashes/whitespace/case (e.g. "Object-Oriented Programming" with a
  normal hyphen vs. a non-breaking one). The lowest-id row survives; the others
  have their CLO links repointed to the survivor and are deleted.

Conservative on purpose: it only merges labels that are *identical* once
normalized. It will NOT merge merely-similar labels ("Data Structures" vs
"Python Data Structures") — those are treated as distinct concepts.

Usage:
    python manage.py cleanup_concepts --course 16
    python manage.py cleanup_concepts --course 16 --dry-run
"""

from __future__ import annotations

import re
import unicodedata

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.courses.models import Concept, Course

_JUNK_RE = re.compile(r"^adaptive session\s+\d+$", re.IGNORECASE)
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")


def _normalize(label: str) -> str:
    s = unicodedata.normalize("NFKC", label or "").translate(_DASHES)
    return re.sub(r"\s+", " ", s).strip().lower()


class Command(BaseCommand):
    help = "Delete 'Adaptive Session N' junk concepts and merge exact-duplicate concepts."

    def add_arguments(self, parser):
        parser.add_argument("--course", type=int, required=True, help="Course id to clean.")
        parser.add_argument("--dry-run", action="store_true", help="Report only; change nothing.")

    def handle(self, *args, **opts):
        course_pk = opts["course"]
        dry = opts["dry_run"]
        if not Course.objects.filter(pk=course_pk).exists():
            raise CommandError(f"Course {course_pk} not found.")

        concepts = list(Concept.objects.filter(course_id=course_pk).order_by("id"))

        # 1) Junk: Adaptive Session N
        junk = [c for c in concepts if _JUNK_RE.match(c.label.strip())]

        # 2) Exact-normalized duplicates among the survivors.
        survivors = [c for c in concepts if c not in junk]
        groups: dict[str, list[Concept]] = {}
        for c in survivors:
            groups.setdefault(_normalize(c.label), []).append(c)
        dupe_groups = {k: v for k, v in groups.items() if len(v) > 1}

        self.stdout.write(self.style.MIGRATE_HEADING(f"Course {course_pk}: cleanup plan"))
        self.stdout.write(f"  Junk to delete ({len(junk)}): {[c.label for c in junk]}")
        for _, members in dupe_groups.items():
            keep, drop = members[0], members[1:]
            self.stdout.write(
                f"  Merge dupes -> keep #{keep.id} '{keep.label}', "
                f"drop {[(c.id, c.label) for c in drop]}"
            )

        if dry:
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
            return

        deleted_junk = 0
        merged = 0
        with transaction.atomic():
            for c in junk:
                c.delete()  # cascades CLO M2M unlink
                deleted_junk += 1

            for members in dupe_groups.values():
                keep, drop = members[0], members[1:]
                for d in drop:
                    # Repoint every CLO that used the duplicate onto the survivor.
                    for clo in d.clos.all():
                        clo.concepts.remove(d)
                        clo.concepts.add(keep)
                    d.delete()
                    merged += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Deleted {deleted_junk} junk concept(s), merged {merged} duplicate(s)."
        ))
        self.stdout.write(
            "Tip: re-run auto-tagging so chunk tags point at the surviving concepts "
            "(editing any concept triggers it, or run tag_chunks_with_concepts)."
        )
