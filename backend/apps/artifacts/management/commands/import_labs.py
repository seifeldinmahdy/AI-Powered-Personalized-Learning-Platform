"""Import on-disk coding-lab history into the durable artifact store.

Run AFTER import_problem_sets (and after reviewing its report):

    python manage.py import_labs [--data-dir DIR] [--report FILE] [--dry-run]

Idempotent. Writes a reviewable markdown report of migrated + skipped rows.
"""

from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.artifacts.importers import import_labs, ImportReport, default_data_dir


class Command(BaseCommand):
    help = "Import AI-service coding-lab JSON files into the durable store."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=None, help="AI service data dir.")
        parser.add_argument("--report", default=None, help="Report markdown path.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Resolve + report without writing rows.")

    def handle(self, *args, **opts):
        data_dir = opts["data_dir"] or default_data_dir()
        report = ImportReport("labs")
        import_labs(data_dir, report, dry_run=opts["dry_run"])

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = opts["report"] or f"import_report_labs_{ts}.md"
        Path(report_path).write_text(report.render_markdown(), encoding="utf-8")

        prefix = "[DRY RUN] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(prefix + report.summary_line()))
        if report.skipped:
            self.stdout.write(self.style.WARNING(
                f"{len(report.skipped)} file(s) SKIPPED — review {report_path}"))
        self.stdout.write(f"report: {report_path}")
