"""
Management command: check_intent_retraining

Checks whether enough user feedback has accumulated to retrain the intent
classifier. If the ``IntentRetrainingCounter`` threshold is reached, it:

1. Exports pending ``IntentFeedbackBuffer`` rows to
   ``Intent_Classifier_Model/data/feedback_utterances.csv``.
2. Spawns the feedback-aware retraining pipeline in the model directory.
3. On success, marks the exported rows as used and resets the counter.

Usage:
    python manage.py check_intent_retraining [--force]

Cron example (every 15 minutes):
    */15 * * * * cd /path/to/backend && venv/bin/python manage.py check_intent_retraining
"""

import csv
import logging
import os
import subprocess
import sys
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.progress.models import IntentFeedbackBuffer, IntentRetrainingCounter

logger = logging.getLogger(__name__)

# Path to the intent classifier model directory, relative to the backend root.
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
MODEL_DIR = BACKEND_DIR.parent / "Intent_Classifier_Model"
FEEDBACK_CSV = MODEL_DIR / "data" / "feedback_utterances.csv"

INTENT_LABEL_MAP = {
    "On-Topic Question": 0,
    "Off-Topic Question": 1,
    "Emotional-State": 2,
    "Pace-Related": 3,
    "Repeat/clarification": 4,
    "Debugging/Code-Sharing": 5,
}


class Command(BaseCommand):
    help = "Check if the intent classifier should be retrained based on user feedback."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run retraining even if the threshold has not been reached.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Export the feedback CSV but do not trigger retraining.",
        )

    def handle(self, *args, **options):
        counter = IntentRetrainingCounter.get()
        force = options["force"]
        dry_run = options["dry_run"]

        self.stdout.write(
            f"Reviews since last train: {counter.reviews_since_last_train}/{counter.threshold}"
        )

        if not force and not counter.threshold_reached():
            self.stdout.write(self.style.NOTICE("Threshold not reached. Exiting."))
            return

        pending = IntentFeedbackBuffer.objects.filter(status="pending").select_related("chat_log")
        if not pending.exists():
            self.stdout.write(self.style.NOTICE("No pending feedback rows. Exiting."))
            return

        # Ensure the target directory exists
        FEEDBACK_CSV.parent.mkdir(parents=True, exist_ok=True)

        exported_ids = []
        with open(FEEDBACK_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "chat_log_id",
                    "student_input",
                    "session_context",
                    "predicted_intent",
                    "corrected_intent",
                    "label_id",
                    "confidence",
                    "feedback",
                ],
            )
            writer.writeheader()
            for entry in pending:
                label_name = entry.effective_label()
                label_id = INTENT_LABEL_MAP.get(label_name, 0)
                writer.writerow(
                    {
                        "id": entry.id,
                        "chat_log_id": entry.chat_log_id,
                        "student_input": entry.student_input,
                        "session_context": entry.session_context,
                        "predicted_intent": entry.predicted_intent,
                        "corrected_intent": entry.corrected_intent or "",
                        "label_id": label_id,
                        "confidence": entry.confidence or "",
                        "feedback": entry.feedback,
                    }
                )
                exported_ids.append(entry.id)

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(exported_ids)} feedback utterances to {FEEDBACK_CSV}"
            )
        )

        if dry_run:
            self.stdout.write(self.style.NOTICE("Dry run: not triggering retraining."))
            return

        # Run the feedback-aware trainer
        trainer_script = MODEL_DIR / "feedback_trainer.py"
        if not trainer_script.exists():
            self.stdout.write(
                self.style.ERROR(f"Trainer script not found: {trainer_script}")
            )
            sys.exit(1)

        self.stdout.write("Starting feedback-aware retraining pipeline...")
        try:
            result = subprocess.run(
                [sys.executable, str(trainer_script)],
                cwd=str(MODEL_DIR),
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            logger.exception("Failed to run feedback trainer")
            self.stdout.write(self.style.ERROR(f"Subprocess error: {exc}"))
            sys.exit(1)

        # Log trainer output
        if result.stdout:
            self.stdout.write(result.stdout)
        if result.stderr:
            self.stdout.write(self.style.WARNING(result.stderr))

        if result.returncode != 0:
            self.stdout.write(self.style.ERROR("Retraining failed. Counter not reset."))
            sys.exit(result.returncode)

        # Mark exported rows as used
        now = timezone.now()
        IntentFeedbackBuffer.objects.filter(id__in=exported_ids).update(
            status="used", used_at=now
        )
        AIChatLog = IntentFeedbackBuffer._meta.get_field("chat_log").related_model
        AIChatLog.objects.filter(feedback_buffer_entry__id__in=exported_ids).update(
            used_for_retraining=True
        )

        counter = IntentRetrainingCounter.reset()
        self.stdout.write(
            self.style.SUCCESS(
                f"Retraining complete. Counter reset to {counter.reviews_since_last_train}."
            )
        )

        # Notify the AI service to reload the promoted checkpoint
        ai_service_url = getattr(settings, "AI_SERVICE_URL", "http://localhost:8001").rstrip("/")
        try:
            reload_resp = requests.post(
                f"{ai_service_url}/intent/reload",
                json={"model_path": "prod_tinybert.pt"},
                timeout=120,
            )
            if reload_resp.status_code == 200:
                self.stdout.write(
                    self.style.SUCCESS(f"AI service reloaded model: {reload_resp.json()}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"AI service reload returned {reload_resp.status_code}: {reload_resp.text}"
                    )
                )
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"Could not notify AI service to reload model: {exc}")
            )
