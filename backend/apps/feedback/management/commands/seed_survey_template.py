"""
Seed the static default post-course survey (idempotent).

The survey is intentionally STATIC — no LLM at question time. The AI's only job
is summarizing responses for the admin (handled elsewhere). ~5 short, mostly
tap-to-answer questions; one optional free-text box feeds the admin summary.

Run:  python manage.py seed_survey_template
"""

from django.core.management.base import BaseCommand

from apps.feedback.models import SurveyTemplate, SurveyQuestion

DEFAULT_TITLE = "Course Feedback"

# (kind, prompt, options, order). Free-text question is optional on the client.
QUESTIONS = [
    ("likert", "Overall, how would you rate this course?", [], 1),
    (
        "single",
        "How well did the course meet its learning goals?",
        ["Not really", "Somewhat", "Very well"],
        2,
    ),
    (
        "single",
        "What was the hardest part of the course?",
        ["Concepts", "Labs", "Problem sets", "Capstone", "Pace"],
        3,
    ),
    (
        "single",
        "What should we improve first?",
        ["Clearer explanations", "More practice", "Better feedback", "Pacing", "Nothing — it was great"],
        4,
    ),
    ("text", "Anything else you'd like to share? (optional)", [], 5),
]


class Command(BaseCommand):
    help = "Create the default static survey template if it does not exist."

    def handle(self, *args, **options):
        template = SurveyTemplate.objects.filter(is_default=True).first()
        if template is None:
            template = SurveyTemplate.objects.create(title=DEFAULT_TITLE, is_default=True)
            self.stdout.write(self.style.SUCCESS(f"Created default template '{template.title}' (id={template.id})"))
        else:
            self.stdout.write(f"Default template already exists (id={template.id}).")

        created = 0
        for kind, prompt, options, order in QUESTIONS:
            _, was_created = SurveyQuestion.objects.get_or_create(
                template=template,
                order=order,
                defaults={"kind": kind, "prompt": prompt, "options": options},
            )
            if was_created:
                created += 1

        if created:
            self.stdout.write(self.style.SUCCESS(f"Added {created} question(s)."))
        else:
            self.stdout.write("All questions already present - nothing to do.")
