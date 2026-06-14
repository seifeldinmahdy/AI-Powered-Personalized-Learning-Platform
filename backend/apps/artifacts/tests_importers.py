"""Stage 6 — one-time importers (problem sets first, then labs).

Verifies migration from on-disk JSON to the durable store, the reviewable
report (migrated + skipped-with-reasons), idempotency, dry-run, and that
unresolvable rows are skipped (not silently dropped).
"""

import json

from django.test import TestCase

from apps.users.models import User
from apps.courses.models import Course, Module, Lesson, Enrollment
from apps.artifacts.models import ProblemSet, ProblemSetAttempt, StudentArtifact
from apps.artifacts.importers import (
    import_problem_sets, import_labs, ImportReport, IMPORTED_PLAN_VERSION,
)


def _course_lesson():
    course = Course.objects.create(title="C", total_lessons_count=1)
    module = Module.objects.create(course=course, title="M", module_order=1)
    lesson = Lesson.objects.create(module=module, title="L", lesson_order=1)
    return course, lesson


class ProblemSetImporterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="s1", email="s1@x.com", password="pw")
        self.course, self.lesson = _course_lesson()
        self.enr = Enrollment.objects.create(student=self.user, course=self.course)
        self.root = None

    def _write_ps(self, data_dir, uid, *, course_id, submissions=None, generated_at="t1"):
        d = {
            "problem_set_id": uid, "student_id": str(self.user.id),
            "course_id": str(course_id) if course_id is not None else "",
            "lesson_id": str(self.lesson.id), "generated_at": generated_at,
            "questions": [{"id": "q1"}], "submissions": submissions or {},
        }
        path = data_dir / "problem_sets" / str(self.user.id) / str(self.lesson.id)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{uid}.json").write_text(json.dumps(d), encoding="utf-8")

    def test_imports_set_with_historical_attempt(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        self._write_ps(data_dir, "ps-1", course_id=self.course.id, submissions={
            "q1": {"code": "print(1)", "hints_used": 1,
                   "result": {"final_score": 80, "evaluated_rubric": [{"id": "r1"}]}},
        })
        report = ImportReport("problem_sets")
        import_problem_sets(data_dir, report)

        ps = ProblemSet.objects.get(ps_uid="ps-1")
        self.assertEqual(ps.plan_version, IMPORTED_PLAN_VERSION)
        self.assertEqual(ps.generation_index, 0)
        att = ProblemSetAttempt.objects.get(problem_set=ps)
        self.assertEqual(att.source, "imported")
        self.assertEqual(att.score, 80)
        self.assertEqual(att.hints_used, 1)
        self.assertEqual(len(report.migrated), 1)

    def test_multiple_generations_get_indexed_and_superseded(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        self._write_ps(data_dir, "ps-a", course_id=self.course.id, generated_at="2026-01-01")
        self._write_ps(data_dir, "ps-b", course_id=self.course.id, generated_at="2026-02-01")
        import_problem_sets(data_dir, ImportReport("problem_sets"))

        a = ProblemSet.objects.get(ps_uid="ps-a")
        b = ProblemSet.objects.get(ps_uid="ps-b")
        self.assertEqual((a.generation_index, a.superseded), (0, True))   # older
        self.assertEqual((b.generation_index, b.superseded), (1, False))  # latest current

    def test_skips_legacy_without_course_id(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        self._write_ps(data_dir, "ps-x", course_id=None)
        report = ImportReport("problem_sets")
        import_problem_sets(data_dir, report)
        self.assertEqual(ProblemSet.objects.count(), 0)
        assert any("missing course_id" in r for _, _, r in report.skipped)
        # The report is the reviewable artifact, not a log line.
        assert "missing course_id" in report.render_markdown()

    def test_idempotent_rerun(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        self._write_ps(data_dir, "ps-1", course_id=self.course.id)
        import_problem_sets(data_dir, ImportReport("problem_sets"))
        report2 = ImportReport("problem_sets")
        import_problem_sets(data_dir, report2)  # second run
        self.assertEqual(ProblemSet.objects.filter(ps_uid="ps-1").count(), 1)
        assert any("already imported" in r for _, _, r in report2.skipped)

    def test_dry_run_writes_nothing(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        self._write_ps(data_dir, "ps-1", course_id=self.course.id)
        report = ImportReport("problem_sets")
        import_problem_sets(data_dir, report, dry_run=True)
        self.assertEqual(ProblemSet.objects.count(), 0)
        self.assertEqual(len(report.migrated), 1)  # would-migrate still reported


class LabImporterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="s2", email="s2@x.com", password="pw")
        self.course, self.lesson = _course_lesson()
        self.enr = Enrollment.objects.create(student=self.user, course=self.course)

    def _write_lab(self, data_dir, lab_id, completed=False):
        d = {"lab_id": lab_id, "cached": False, "generated_at": "t",
             "lab": {"title": "L", "cells": []}}
        if completed:
            d["completed_at"] = "2026-01-01T00:00:00Z"
        labs = data_dir / "coding_labs"
        labs.mkdir(parents=True, exist_ok=True)
        (labs / f"{lab_id}.json").write_text(json.dumps(d), encoding="utf-8")

    def test_imports_lab_as_student_artifact(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        lab_id = f"{self.user.id}_{self.course.id}_{self.lesson.id}"
        self._write_lab(data_dir, lab_id, completed=True)
        report = ImportReport("labs")
        import_labs(data_dir, report)

        art = StudentArtifact.objects.get(student=self.user, artifact_type="lab")
        self.assertEqual(art.lesson_id, self.lesson.id)
        self.assertEqual(art.plan_version, IMPORTED_PLAN_VERSION)
        self.assertEqual(art.status, "completed")
        self.assertEqual(art.content_json["lab"]["title"], "L")
        self.assertEqual(len(report.migrated), 1)

    def test_skips_unparseable_lab_id(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        self._write_lab(data_dir, "anonymous_3_1")  # no real student
        report = ImportReport("labs")
        import_labs(data_dir, report)
        self.assertEqual(StudentArtifact.objects.count(), 0)
        assert any("unparseable" in r for _, _, r in report.skipped)

    def test_idempotent_rerun(self):
        import tempfile, pathlib
        data_dir = pathlib.Path(tempfile.mkdtemp())
        lab_id = f"{self.user.id}_{self.course.id}_{self.lesson.id}"
        self._write_lab(data_dir, lab_id)
        import_labs(data_dir, ImportReport("labs"))
        report2 = ImportReport("labs")
        import_labs(data_dir, report2)
        self.assertEqual(StudentArtifact.objects.filter(artifact_type="lab").count(), 1)
        assert any("already imported" in r for _, _, r in report2.skipped)
