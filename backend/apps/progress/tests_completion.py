"""Server-side, idempotent lesson completion (Option A).

A lesson is "Completed" only once its problem set finishes, and that transition
is initiated server-side (AI service → /progress/complete-lesson/), not by a
frontend call at the end of the live session. These tests pin the three
acceptance criteria:

  (a) progress_percentage (the capstone-CTA gate) cannot reach 100 until the
      LAST lesson is completed — i.e. after its problem set.
  (b) completion is recorded by the server-side trigger alone, with no follow-up
      frontend call (resilient to a closed tab).
  (c) XP / streak / progress fire exactly once, idempotently.
"""

from datetime import date
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User, StudentProfile
from apps.courses.models import Course, Module, Lesson, Enrollment
from apps.gamification.signals import XP_LESSON_COMPLETE, XP_FIRST_LESSON, XP_COURSE_COMPLETE
from apps.gamification.models import DailyStudyStats
from apps.progress.models import LessonCompletion
from apps.progress.completion_service import complete_lesson
from apps.core import authentication


def _make_course(num_lessons=2):
    course = Course.objects.create(title="Intro", total_lessons_count=num_lessons)
    module = Module.objects.create(course=course, title="M1", module_order=1)
    lessons = [
        Lesson.objects.create(module=module, title=f"L{i}", lesson_order=i)
        for i in range(1, num_lessons + 1)
    ]
    return course, lessons


class CompletionServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="s1", email="s1@x.com", password="pw")
        self.profile = StudentProfile.objects.create(user=self.user)
        self.course, self.lessons = _make_course(2)
        self.enrollment = Enrollment.objects.create(student=self.user, course=self.course)

    def test_xp_streak_first_lesson_bonus_fire_once(self):
        """(c) First completion awards lesson XP + first-lesson bonus + streak,
        and a second call is a no-op (no double award)."""
        r1 = complete_lesson(self.user, self.lessons[0], time_spent_minutes=12)
        self.assertFalse(r1["already_completed"])

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_xp, XP_LESSON_COMPLETE + XP_FIRST_LESSON)
        self.assertEqual(self.profile.current_streak, 1)
        self.assertTrue(DailyStudyStats.objects.filter(user=self.user, study_date=date.today()).exists())

        c = LessonCompletion.objects.get(enrollment=self.enrollment, lesson=self.lessons[0])
        self.assertEqual(c.status, "Completed")
        self.assertIsNotNone(c.completed_at)
        self.assertTrue(c.gamification_awarded)
        self.assertEqual(c.time_spent_minutes, 12)  # measured time preserved

        # Idempotent: calling again awards nothing more.
        r2 = complete_lesson(self.user, self.lessons[0], time_spent_minutes=99)
        self.assertTrue(r2["already_completed"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_xp, XP_LESSON_COMPLETE + XP_FIRST_LESSON)

    def test_progress_gate_requires_last_lesson(self):
        """(a) progress stays < 100 until the final lesson completes — so the
        capstone CTA cannot appear before the last problem set runs."""
        complete_lesson(self.user, self.lessons[0])
        self.enrollment.refresh_from_db()
        self.assertLess(float(self.enrollment.progress_percentage), 100.0)

        complete_lesson(self.user, self.lessons[1])
        self.enrollment.refresh_from_db()
        self.assertEqual(float(self.enrollment.progress_percentage), 100.0)

    def test_idempotent_does_not_re_award_course_bonus(self):
        """Re-triggering the last lesson does not re-grant the course-complete bonus."""
        complete_lesson(self.user, self.lessons[0])
        complete_lesson(self.user, self.lessons[1])
        self.profile.refresh_from_db()
        xp_after_course = self.profile.current_xp
        # second L0 + L1 lessons + first bonus + course bonus
        expected = XP_LESSON_COMPLETE * 2 + XP_FIRST_LESSON + XP_COURSE_COMPLETE
        self.assertEqual(xp_after_course, expected)

        complete_lesson(self.user, self.lessons[1])  # retried trigger
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_xp, expected)

    def test_no_enrollment_returns_none(self):
        other = User.objects.create_user(username="s2", email="s2@x.com", password="pw")
        StudentProfile.objects.create(user=other)
        self.assertIsNone(complete_lesson(other, self.lessons[0]))


class InternalCompleteEndpointTests(TestCase):
    """(b) The server-side trigger records completion alone — no frontend call."""

    def setUp(self):
        self.user = User.objects.create_user(username="s3", email="s3@x.com", password="pw")
        StudentProfile.objects.create(user=self.user)
        self.course, self.lessons = _make_course(1)
        self.enrollment = Enrollment.objects.create(student=self.user, course=self.course)

    def test_service_call_completes_lesson_without_frontend(self):
        client = APIClient()
        with mock.patch.object(authentication, "INTERNAL_SERVICE_KEY", "testkey"):
            resp = client.post(
                "/api/progress/complete-lesson/",
                {"lesson_id": self.lessons[0].id},
                format="json",
                HTTP_X_SERVICE_KEY="testkey",
                HTTP_X_STUDENT_ID=str(self.user.id),
            )
        self.assertEqual(resp.status_code, 200, resp.content)

        c = LessonCompletion.objects.get(enrollment=self.enrollment, lesson=self.lessons[0])
        self.assertEqual(c.status, "Completed")
        self.assertTrue(c.gamification_awarded)
        # Single-lesson course → completing it drives the gate to 100.
        self.enrollment.refresh_from_db()
        self.assertEqual(float(self.enrollment.progress_percentage), 100.0)

    def test_service_call_is_idempotent(self):
        client = APIClient()
        with mock.patch.object(authentication, "INTERNAL_SERVICE_KEY", "testkey"):
            headers = dict(HTTP_X_SERVICE_KEY="testkey", HTTP_X_STUDENT_ID=str(self.user.id))
            client.post("/api/progress/complete-lesson/", {"lesson_id": self.lessons[0].id},
                        format="json", **headers)
            resp2 = client.post("/api/progress/complete-lesson/", {"lesson_id": self.lessons[0].id},
                                format="json", **headers)
        self.assertEqual(resp2.status_code, 200, resp2.content)
        self.assertTrue(resp2.json()["already_completed"])
        StudentProfile.objects.get(user=self.user)
        prof = StudentProfile.objects.get(user=self.user)
        self.assertEqual(prof.current_xp, XP_LESSON_COMPLETE + XP_FIRST_LESSON + XP_COURSE_COMPLETE)
