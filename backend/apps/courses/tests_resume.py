"""Batch 10b — course resume (index + current plan, no content scan)."""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.courses.models import Course, Module, Lesson, Enrollment
from apps.progress.models import LessonCompletion
from apps.progress.completion_service import complete_lesson
from apps.artifacts.models import StudentArtifact, ProblemSet, ProblemSetAttempt

PLAN = "apps.courses.views._fetch_current_plan"


def _course(n_lessons=3):
    course = Course.objects.create(title="C", total_lessons_count=n_lessons)
    module = Module.objects.create(course=course, title="M", module_order=1)
    lessons = [Lesson.objects.create(module=module, title=f"L{i}", lesson_order=i)
               for i in range(1, n_lessons + 1)]
    return course, lessons


class ResumeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="s1", email="s1@x.com", password="pw")
        self.course, self.lessons = _course(3)
        self.enr = Enrollment.objects.create(
            student=self.user, course=self.course, current_lesson=self.lessons[0],
            progress_percentage=33,
        )
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def _art(self, atype, *, plan_version, session=None, lesson=None, status="generated"):
        return StudentArtifact.objects.create(
            enrollment=self.enr, student=self.user, course=self.course,
            artifact_type=atype, session_number=session, lesson_id=lesson,
            plan_version=plan_version, content_json={"big": "x" * 1000}, status=status)

    def _ps(self, *, plan_version, lesson, uid, attempts=(), num_questions=1):
        ps = ProblemSet.objects.create(
            enrollment=self.enr, student=self.user, course=self.course, lesson_id=lesson,
            plan_version=plan_version, generation_index=0, ps_uid=uid,
            content_json={"questions": [{"id": "q1"}]}, num_questions=num_questions)
        for sc in attempts:
            ProblemSetAttempt.objects.create(problem_set=ps, question_id="q1", score=sc)
        return ps

    def test_resume_counts_pointer_and_timeline_from_index(self):
        self._art("slides", plan_version=2, session=1)
        self._art("lab", plan_version=2, lesson=self.lessons[0].id)
        self._ps(plan_version=2, lesson=self.lessons[0].id, uid="ps-1", attempts=(40, 80, 60))
        LessonCompletion.objects.create(enrollment=self.enr, lesson=self.lessons[0], status="Completed")

        with mock.patch(PLAN, return_value={"plan_version": 2, "total_sessions": 3}):
            resp = self.client.get(f"/api/courses/{self.course.id}/resume/")
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()
        self.assertEqual(d["total_sessions"], 3)
        self.assertEqual(d["completed"], 1)
        self.assertEqual(d["sessions_left"], 2)
        self.assertEqual(d["current_lesson"], self.lessons[0].id)
        self.assertEqual(d["current_session_number"], 1)
        kinds = {e["type"] for e in d["timeline"]}
        self.assertEqual(kinds, {"slides", "lab", "problem_set"})
        ps_entry = next(e for e in d["timeline"] if e["type"] == "problem_set")
        self.assertEqual(ps_entry["best_score"], 80.0)  # max attempt on the one question

    def test_timeline_excludes_orphaned_old_plan_version(self):
        self._art("slides", plan_version=1, session=1)   # orphaned (old plan)
        self._art("slides", plan_version=2, session=1)   # current
        with mock.patch(PLAN, return_value={"plan_version": 2, "total_sessions": 3}):
            d = self.client.get(f"/api/courses/{self.course.id}/resume/").json()
        self.assertTrue(all(e.get("session_number") is None or e["status"] for e in d["timeline"]))
        self.assertEqual(len(d["timeline"]), 1)  # only the v2 slides, not the v1 orphan

    def test_reopen_after_completion_shows_advanced_pointer(self):
        # Complete the first lesson → pointer advances to the next incomplete one.
        complete_lesson(self.user, self.lessons[0])
        with mock.patch(PLAN, return_value={"plan_version": 2, "total_sessions": 3}):
            d = self.client.get(f"/api/courses/{self.course.id}/resume/").json()
        self.assertEqual(d["current_lesson"], self.lessons[1].id)  # advanced
        self.assertEqual(d["completed"], 1)
        self.assertEqual(d["sessions_left"], 2)

    def test_no_content_scan(self):
        # Several artifacts with large content — resume must NEVER load content
        # columns (proven by inspecting the SQL), and stays bounded.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for i in range(1, 4):
            self._art("slides", plan_version=2, session=i)
        self._ps(plan_version=2, lesson=self.lessons[0].id, uid="ps-q", attempts=(70,))
        with mock.patch(PLAN, return_value={"plan_version": 2, "total_sessions": 3}):
            with CaptureQueriesContext(connection) as ctx:
                resp = self.client.get(f"/api/courses/{self.course.id}/resume/")
        self.assertEqual(resp.status_code, 200)
        sql = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("content_json", sql)   # no content scan
        self.assertNotIn("hint_tracking", sql)
        self.assertLess(len(ctx.captured_queries), 12)  # bounded, not per-content

    def test_not_enrolled_404(self):
        other = Course.objects.create(title="X", total_lessons_count=1)
        with mock.patch(PLAN, return_value=None):
            resp = self.client.get(f"/api/courses/{other.id}/resume/")
        self.assertEqual(resp.status_code, 404)


class ProblemSetHistoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="h1", email="h1@x.com", password="pw")
        self.course, self.lessons = _course(1)
        self.enr = Enrollment.objects.create(student=self.user, course=self.course)
        self.ps = ProblemSet.objects.create(
            enrollment=self.enr, student=self.user, course=self.course,
            lesson_id=self.lessons[0].id, plan_version=2, generation_index=0,
            ps_uid="ps-h", content_json={"questions": [{"id": "q1"}]}, num_questions=1)
        for sc in (40, 80, 60):
            ProblemSetAttempt.objects.create(problem_set=self.ps, question_id="q1", score=sc)

    def test_owner_sees_history_and_best_score(self):
        c = APIClient(); c.force_authenticate(self.user)
        d = c.get("/api/artifacts/problem-sets/ps-h/history/").json()
        self.assertEqual(len(d["attempts"]), 3)
        self.assertEqual([a["score"] for a in d["attempts"]], [40, 80, 60])  # submission order
        self.assertEqual(d["best_score"], 80.0)

    def test_other_student_history_forbidden(self):
        intruder = User.objects.create_user(username="bad", email="bad@x.com", password="pw")
        c = APIClient(); c.force_authenticate(intruder)
        resp = c.get("/api/artifacts/problem-sets/ps-h/history/")
        self.assertEqual(resp.status_code, 403)
