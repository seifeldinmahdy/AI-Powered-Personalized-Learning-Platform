"""Batch 11a — remediation trigger: insertion, boundedness, determinism,
plan-immutability, resume surfacing, and the concurrent partial-unique backstop.
"""

import threading
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.courses.models import Course, Module, Lesson, Enrollment, Concept
from apps.progress.models import StudentLearningProfile, RemediationStep
from apps.progress import remediation_service as rem


def _setup():
    user = User.objects.create_user(username="r1", email="r1@x.com", password="pw")
    course = Course.objects.create(title="C", total_lessons_count=1)
    module = Module.objects.create(course=course, title="M", module_order=1)
    lesson = Lesson.objects.create(module=module, title="L", lesson_order=1)
    enr = Enrollment.objects.create(student=user, course=course, current_lesson=lesson)
    concept = Concept.objects.create(course=course, label="Loops", slug="loops")
    StudentLearningProfile.objects.create(student=user)
    return user, course, lesson, enr, concept


class EvaluateTests(TestCase):
    def setUp(self):
        self.user, self.course, self.lesson, self.enr, self.concept = _setup()

    def _eval(self, score, plan_version=2):
        return rem.evaluate(self.user.id, self.enr, plan_version, {str(self.concept.id): score})

    def test_drop_inserts_exactly_one(self):
        r1 = self._eval(0.30)
        self.assertEqual(r1["inserted"], [str(self.concept.id)])
        # A second event while still below inserts nothing more (one per crossing).
        r2 = self._eval(0.20)
        self.assertEqual(r2["inserted"], [])
        self.assertEqual(
            RemediationStep.objects.filter(status="pending").count(), 1)
        step = RemediationStep.objects.get()
        self.assertEqual(step.plan_version, 2)
        self.assertEqual(step.kind, "review")
        self.assertEqual(step.concept_id, self.concept.id)

    def test_above_threshold_inserts_nothing(self):
        self._eval(0.80)
        self.assertEqual(RemediationStep.objects.count(), 0)

    def test_hysteresis_band_does_not_flap(self):
        self._eval(0.30)  # pending
        # Score recovers into the band (0.45–0.55): NOT resolved yet.
        r = self._eval(0.50)
        self.assertEqual(r["resolved"], [])
        self.assertEqual(RemediationStep.objects.filter(status="pending").count(), 1)

    def test_recovery_resolves_then_new_drop_creates_new(self):
        self._eval(0.30)
        r = self._eval(0.60)  # >= resolve bar
        self.assertEqual(r["resolved"], [str(self.concept.id)])
        self.assertEqual(RemediationStep.objects.filter(status="resolved").count(), 1)
        self.assertEqual(RemediationStep.objects.filter(status="pending").count(), 0)
        # A subsequent drop is a NEW crossing → a new pending step.
        r2 = self._eval(0.20)
        self.assertEqual(r2["inserted"], [str(self.concept.id)])
        self.assertEqual(RemediationStep.objects.count(), 2)
        self.assertEqual(RemediationStep.objects.filter(status="pending").count(), 1)

    def test_deterministic_idempotent(self):
        a = self._eval(0.30)
        b = self._eval(0.30)  # same state
        self.assertEqual(a["inserted"], [str(self.concept.id)])
        self.assertEqual(b["inserted"], [])  # no change → no new row
        self.assertEqual(RemediationStep.objects.count(), 1)

    def test_uses_configured_thresholds(self):
        with self.settings(REMEDIATION_TRIGGER_THRESHOLD=0.6, REMEDIATION_RESOLVE_THRESHOLD=0.8):
            self._eval(0.55)  # below the (raised) trigger
            self.assertEqual(RemediationStep.objects.filter(status="pending").count(), 1)


class MasteryRecordIntegrationTests(TestCase):
    """The mastery writer triggers remediation only when plan_version+course given."""

    def setUp(self):
        self.user, self.course, self.lesson, self.enr, self.concept = _setup()
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def _post(self, outcome, with_plan=True):
        body = {"events": [{"concept_id": str(self.concept.id), "outcome": outcome,
                            "source": "problem_set", "alpha": 1.0}]}
        if with_plan:
            body["plan_version"] = 2
            body["course_id"] = self.course.id
        return self.client.post("/api/progress/mastery/record/", body, format="json")

    def test_low_outcome_triggers_remediation(self):
        resp = self._post(0.0)  # fold from 0.5 prior with alpha 1.0 -> 0.0 (< 0.45)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(RemediationStep.objects.filter(status="pending").count(), 1)

    def test_no_plan_version_skips_remediation(self):
        resp = self._post(0.0, with_plan=False)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RemediationStep.objects.count(), 0)  # no plan → no remediation


class ResumeSurfacingTests(TestCase):
    def setUp(self):
        self.user, self.course, self.lesson, self.enr, self.concept = _setup()
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_pending_remediation_in_timeline_positioned_after_session(self):
        from apps.artifacts.models import StudentArtifact
        # An existing artifact (must still resolve, unchanged).
        StudentArtifact.objects.create(
            enrollment=self.enr, student=self.user, course=self.course,
            artifact_type="slides", session_number=1, plan_version=2,
            content_json={"x": 1})
        rem.evaluate(self.user.id, self.enr, 2, {str(self.concept.id): 0.2})

        plan = {"plan_version": 2, "total_sessions": 1,
                "sessions": [{"session_number": 1, "concept_ids": [str(self.concept.id)]}]}
        with mock.patch("apps.courses.views._fetch_current_plan", return_value=plan):
            d = self.client.get(f"/api/courses/{self.course.id}/resume/").json()

        types = [e["type"] for e in d["timeline"]]
        self.assertIn("remediation", types)
        self.assertIn("slides", types)  # existing artifact still resolves
        rem_entry = next(e for e in d["timeline"] if e["type"] == "remediation")
        slides_entry = next(e for e in d["timeline"] if e["type"] == "slides")
        # Remediation sorts AFTER its concept's session (session 1).
        self.assertGreater(rem_entry["sort_key"], slides_entry["sort_key"])

    def test_remediation_timeline_is_index_light(self):
        from django.db import connection as conn
        from django.test.utils import CaptureQueriesContext
        rem.evaluate(self.user.id, self.enr, 2, {str(self.concept.id): 0.2})
        plan = {"plan_version": 2, "total_sessions": 1,
                "sessions": [{"session_number": 1, "concept_ids": [str(self.concept.id)]}]}
        with mock.patch("apps.courses.views._fetch_current_plan", return_value=plan):
            with CaptureQueriesContext(conn) as ctx:
                self.client.get(f"/api/courses/{self.course.id}/resume/")
        sql = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("content_json", sql)   # remediation join stays index-light


class ConcurrencyTests(TransactionTestCase):
    def test_concurrent_inserts_hit_partial_unique_backstop(self):
        user, course, lesson, enr, concept = _setup()
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            barrier.wait()
            try:
                rem.evaluate(user.id, enr, 2, {str(concept.id): 0.2})
            except Exception as e:   # an unhandled IntegrityError would land here
                errors.append(e)
            finally:
                connection.close()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start(); t1.join(); t2.join()

        self.assertEqual(errors, [])  # second insert caught gracefully, not raised
        self.assertEqual(
            RemediationStep.objects.filter(status="pending").count(), 1)  # exactly one
