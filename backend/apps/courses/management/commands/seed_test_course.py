"""
Seed a ready-to-test capstone course end to end.

Creates a small published course (1 module, 3 lessons), concepts + CLOs, an
ACTIVE capstone with a core/stretch rubric, and one or more test students who
are enrolled and (optionally) have the material fast-finished to 100%. Supports
solo and team modes, optional pre-formed team, seeded complementary mastery so
the team role-advisor produces meaningful output, and an optional shortcut that
marks the capstone PASSED so you can jump straight to survey → certificate.

Examples
--------
Solo, material finished, jump to the ending:
    python manage.py seed_test_course --mode solo --finish --pass --reset

Team of 3, pre-formed team with complementary mastery (for role advice):
    python manage.py seed_test_course --mode team --students 3 --form-team --finish --reset

Everything is idempotent per --title when you pass --reset (it deletes the prior
course of that title first). Test users are reused (password reset each run).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()

# concept slug -> label
CONCEPTS = [
    ("io-files", "File I/O"),
    ("logic-validation", "Input validation / logic"),
    ("data-structures", "Data structures"),
    ("testing", "Testing"),
]

# Complementary mastery profiles, rotated across team members so the role
# advisor has real, contrasting strengths to reason about.
MASTERY_PROFILES = [
    {  # strong I/O + structures, weak validation/testing
        "io-files": (0.85, 6), "data-structures": (0.72, 5),
        "logic-validation": (0.22, 5), "testing": (0.30, 4),
    },
    {  # strong validation + testing, weak I/O/structures
        "logic-validation": (0.86, 6), "testing": (0.75, 5),
        "io-files": (0.20, 5), "data-structures": (0.33, 4),
    },
    {  # all-rounder, moderate evidence
        "data-structures": (0.78, 6), "io-files": (0.55, 4),
        "logic-validation": (0.50, 4), "testing": (0.45, 4),
    },
    {  # strong testing, otherwise developing
        "testing": (0.82, 6), "logic-validation": (0.60, 5),
        "io-files": (0.35, 4), "data-structures": (0.40, 4),
    },
]


class Command(BaseCommand):
    help = "Seed a test capstone course (solo/team) with enrolled, fast-finished students."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=["solo", "team"], default="solo")
        parser.add_argument("--students", type=int, default=0,
                            help="Number of test students (default: 1 solo, 3 team).")
        parser.add_argument("--title", default="Capstone Test Course")
        parser.add_argument("--password", default="test12345")
        parser.add_argument("--finish", action="store_true",
                            help="Mark the 3 lessons complete → material progress 100%%.")
        parser.add_argument("--form-team", action="store_true",
                            help="Team mode: pre-form a Team with all students (skip the queue).")
        parser.add_argument("--pass", dest="pass_capstone", action="store_true",
                            help="Shortcut: create a PASSED submission per student (test the ending).")
        parser.add_argument("--reset", action="store_true",
                            help="Delete any existing course with the same title first.")

    @transaction.atomic
    def handle(self, *args, **opts):
        from apps.courses.models import Course, Module, Lesson, Enrollment, Concept, CourseLearningOutcome
        from apps.capstone.models import Capstone, CapstoneRubricItem, Team
        from apps.users.models import StudentProfile
        from apps.progress.models import StudentLearningProfile, LessonCompletion

        mode = opts["mode"]
        title = opts["title"]
        password = opts["password"]
        n_students = opts["students"] or (3 if mode == "team" else 1)

        # Make sure the static default survey exists (for survey → certificate).
        call_command("seed_survey_template")

        if opts["reset"]:
            deleted, _ = Course.objects.filter(title=title).delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f"Reset: removed prior '{title}' ({deleted} rows)."))

        # ---- Course + module + 3 lessons (signal sets total_lessons_count) ----
        course = Course.objects.create(
            title=title,
            description="Auto-generated course for capstone testing.",
            difficulty="Beginner", status="Published", is_published=True,
        )
        module = Module.objects.create(course=course, title="Getting Started", module_order=1)
        lessons = [
            Lesson.objects.create(module=module, title=f"Session {i}", lesson_order=i)
            for i in range(1, 4)
        ]

        # ---- Concepts ----
        concepts = {}
        for order, (slug, label) in enumerate(CONCEPTS):
            concepts[slug] = Concept.objects.create(
                course=course, label=label, slug=slug, order=order,
            )

        # ---- CLOs (concept-linked; power certificate "CLOs attained") ----
        clo_specs = [
            ("CLO1", "Apply file input/output to persist data.", "apply", ["io-files"]),
            ("CLO2", "Apply control flow and input validation.", "apply", ["logic-validation"]),
            ("CLO3", "Select and use appropriate data structures.", "apply", ["data-structures"]),
        ]
        for order, (code, text, bloom, cslugs) in enumerate(clo_specs):
            clo = CourseLearningOutcome.objects.create(
                course=course, code=code, text=text, bloom_level=bloom, order=order,
            )
            clo.concepts.set([concepts[s] for s in cslugs])

        # ---- Capstone (ACTIVE) + rubric ----
        capstone = Capstone.objects.create(
            course=course,
            title=f"{title} — Capstone",
            spec_mode="admin_defined",
            team_mode=mode,
            team_cap=4,
            status="active",
            brief_text="Build a small command-line app that stores records to a file, "
                       "validates user input, and uses sensible data structures.",
            run_command="python main.py",
            pass_policy="all_core",
        )
        # (category, text, concept_slug, weight, min_team_size)
        rubric = [
            ("core", "Reads and writes data to a file correctly", "io-files", 2, 1),
            ("core", "Validates user input with clear conditional logic", "logic-validation", 2, 1),
            ("core", "Uses appropriate data structures", "data-structures", 1, 1),
            ("core", "Has a working main entry point (main.py)", "io-files", 1, 1),
            ("stretch", "Includes unit tests", "testing", 1, 1),
            ("stretch", "Handles edge cases gracefully", "logic-validation", 1, 1),
        ]
        if mode == "team":
            rubric.append(
                ("core", "Commit history shows contributions from all members", None, 1, 2)
            )
        for order, (cat, text, cslug, weight, mts) in enumerate(rubric):
            CapstoneRubricItem.objects.create(
                capstone=capstone, text=text, category=cat,
                concept=concepts.get(cslug) if cslug else None,
                weight=weight, min_team_size=mts, order=order,
            )
        effective_items = list(capstone.rubric_items.all())

        # ---- Students ----
        created_students = []
        for i in range(1, n_students + 1):
            username = f"cap_student{i}"
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@test.local", "role": "student"},
            )
            user.role = "student"
            user.set_password(password)
            user.save()

            StudentProfile.objects.get_or_create(user=user)

            # Seed complementary concept_mastery through the SINGLE writer so the
            # event log is the source of truth even for seeded fixtures.
            from apps.progress.mastery_service import record_events
            StudentLearningProfile.objects.get_or_create(student=user)
            mp = MASTERY_PROFILES[(i - 1) % len(MASTERY_PROFILES)]
            record_events(user.id, [
                # alpha=1.0 lands the score exactly; evidence_delta carries the count.
                {"concept_id": str(concepts[slug].id), "outcome": score,
                 "source": "assessment", "alpha": 1.0, "evidence_delta": evidence}
                for slug, (score, evidence) in mp.items()
            ])

            enrollment, _ = Enrollment.objects.get_or_create(
                student=user, course=course,
                defaults={
                    "placement_score": 70.0,
                    "is_pathway_ready": True,
                    "current_lesson": lessons[0],
                    "current_pathway": {
                        "sessions": [{"lesson_id": l.id, "title": l.title} for l in lessons]
                    },
                },
            )

            # ---- Fast-finish the material (drives progress → 100%) ----
            if opts["finish"]:
                for lesson in lessons:
                    LessonCompletion.objects.update_or_create(
                        enrollment=enrollment, lesson=lesson,
                        defaults={"status": "Completed", "completed_at": timezone.now(),
                                  "score": 100, "time_spent_minutes": 20},
                    )
                # Defensive: ensure 100% even if the gamification signal short-circuits.
                enrollment.refresh_from_db()
                if float(enrollment.progress_percentage or 0) < 100:
                    enrollment.progress_percentage = 100
                    enrollment.save(update_fields=["progress_percentage"])

            created_students.append((user, enrollment))

        # ---- Optional: pre-form a team (team mode) ----
        team = None
        if mode == "team" and opts["form_team"] and len(created_students) >= 2:
            team = Team.objects.create(capstone=capstone, status="active",
                                       name="Test Team")
            team.members.set([u for u, _ in created_students])
            # Generate role advice now (needs the AI service running; non-fatal).
            try:
                from apps.capstone.team_roles import generate_for_team
                generate_for_team(team.id)
            except Exception as exc:  # pragma: no cover
                self.stdout.write(self.style.WARNING(f"role advice generation skipped: {exc}"))

        # ---- Optional: mark capstone PASSED (shortcut to test the ending) ----
        if opts["pass_capstone"]:
            self._pass_submissions(capstone, created_students, team, effective_items, mode)

        # ---- Report ----
        self._report(course, capstone, team, created_students, password, opts)

    def _pass_submissions(self, capstone, created_students, team, items, mode):
        from apps.capstone.models import CapstoneSubmission
        from apps.courses.completion import mark_complete_if_eligible

        for user, enrollment in created_students:
            # Mark every applicable rubric item as passed → verdict pass.
            size = team.members.count() if (team and mode == "team") else 1
            applicable = [it for it in items if it.min_team_size <= size]
            results = {
                str(it.id): {"passed": True, "weight": it.weight, "evidence": "seeded pass"}
                for it in applicable
            }
            CapstoneSubmission.objects.update_or_create(
                capstone=capstone, enrollment=enrollment,
                defaults={
                    "team": team if mode == "team" else None,
                    "results": results, "score": 100.0, "verdict": "pass",
                    "feedback": "Seeded passing submission for testing.",
                    "status": "completed", "evaluated_at": timezone.now(),
                    "mastery_applied": True, "xp_awarded": 0,
                },
            )
            mark_complete_if_eligible(enrollment)

    def _report(self, course, capstone, team, created_students, password, opts):
        line = self.style.SUCCESS
        self.stdout.write(line("\n" + "=" * 60))
        self.stdout.write(line("  Test capstone course ready"))
        self.stdout.write(line("=" * 60))
        self.stdout.write(f"  Course id      : {course.id}  ({course.title})")
        self.stdout.write(f"  Capstone id    : {capstone.id}  (mode={capstone.team_mode}, status={capstone.status})")
        if team:
            self.stdout.write(f"  Team id        : {team.id}  members={team.members.count()}")
        self.stdout.write(f"  Material finish: {'yes' if opts['finish'] else 'no'}    "
                          f"Passed shortcut: {'yes' if opts['pass_capstone'] else 'no'}")
        self.stdout.write("  Students (password = " + password + "):")
        for user, enr in created_students:
            self.stdout.write(f"    - {user.username}   enrollment={enr.id}  progress={enr.progress_percentage}%")
        self.stdout.write("\n  Try these (log in as a student):")
        self.stdout.write(f"    Capstone page : /course/{course.id}/capstone")
        self.stdout.write(f"    IDE workspace : /course/{course.id}/capstone/workspace")
        if capstone.team_mode == "team" and not team:
            self.stdout.write("    Team tab -> Join Queue (form teams via admin 'Process Queue Now' "
                              "or re-run with --form-team).")
        self.stdout.write("\n  Notes:")
        self.stdout.write("    - Repo provisioning + per-commit CI need the GitHub App; "
                          "without it use 'Submit Code' (archive) which calls the AI service.")
        self.stdout.write("    - Role advice + archive grading require the AI service running "
                          "(grading also needs OLLAMA creds).")
        self.stdout.write("    - With --pass, open the capstone -> Results: PASS -> survey -> certificate.\n")
