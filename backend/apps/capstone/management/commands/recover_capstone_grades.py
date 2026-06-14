"""Recover capstone submissions stuck in 'evaluating'.

Run from cron (e.g. every few minutes):

    python manage.py recover_capstone_grades

Repo-backed grades whose worker died are re-queued (bounded by max attempts);
the rest are failed with a re-submit message. Idempotent and concurrency-safe.
"""

from django.core.management.base import BaseCommand

from apps.capstone.grading import (
    recover_stuck_grades,
    GRADING_TIMEOUT_MINUTES,
    MAX_GRADING_ATTEMPTS,
)


class Command(BaseCommand):
    help = "Detect and recover capstone submissions stuck in 'evaluating'."

    def add_arguments(self, parser):
        parser.add_argument("--timeout-minutes", type=int, default=GRADING_TIMEOUT_MINUTES)
        parser.add_argument("--max-attempts", type=int, default=MAX_GRADING_ATTEMPTS)

    def handle(self, *args, **options):
        result = recover_stuck_grades(
            timeout_minutes=options["timeout_minutes"],
            max_attempts=options["max_attempts"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"recovered: requeued={result['requeued']} failed={result['failed']}"
        ))
