"""Stage 1 — durable artifact backbone (Batch 10a).

Covers the backbone-level acceptance criteria via the Django models/endpoints:
durability round-trip, append-only retry, regen cap + per-plan_version reset,
the exact best-score aggregation, placement re-take immutability, and ownership.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.courses.models import Course, Module, Lesson, Enrollment
from apps.artifacts.models import (
    PlacementAttempt, StudentArtifact, ProblemSet, ProblemSetAttempt,
)
from apps.artifacts.scoring import generation_score, best_lesson_score


def _course_with_lesson(title="C"):
    course = Course.objects.create(title=title, total_lessons_count=1)
    module = Module.objects.create(course=course, title="M", module_order=1)
    lesson = Lesson.objects.create(module=module, title="L", lesson_order=1)
    return course, lesson


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="s1", email="s1@x.com", password="pw")
        self.course, self.lesson = _course_with_lesson()
        self.enr = Enrollment.objects.create(student=self.user, course=self.course)
        self.client = _client(self.user)


# ── Durability round-trip ─────────────────────────────────────────────────────

class DurabilityTests(Base):
    def test_slides_artifact_roundtrip(self):
        resp = self.client.post("/api/artifacts/", {
            "artifact_type": "slides", "course_id": self.course.id,
            "session_number": 1, "plan_version": 2,
            "content_json": {"slides": [{"title": "Loops"}]},
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        art_id = resp.json()["id"]
        # Fetched back from a fresh query (simulates a restart) → content intact.
        got = self.client.get(f"/api/artifacts/{art_id}/content/")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["content_json"]["slides"][0]["title"], "Loops")

    def test_upsert_overwrites_same_key(self):
        payload = {"artifact_type": "slides", "course_id": self.course.id,
                   "session_number": 1, "plan_version": 2, "content_json": {"v": 1}}
        r1 = self.client.post("/api/artifacts/", payload, format="json")
        payload["content_json"] = {"v": 2}
        r2 = self.client.post("/api/artifacts/", payload, format="json")
        self.assertEqual(r2.status_code, 200)  # updated, not created
        self.assertEqual(r1.json()["id"], r2.json()["id"])
        self.assertEqual(StudentArtifact.objects.filter(student=self.user).count(), 1)


# ── Problem-set attempts: append-only retry ───────────────────────────────────

class AttemptAppendTests(Base):
    def _make_ps(self, uid="ps-1", gen=0, questions=None):
        return ProblemSet.objects.create(
            enrollment=self.enr, student=self.user, course=self.course, lesson=self.lesson,
            plan_version=1, generation_index=gen, ps_uid=uid,
            content_json={"questions": questions or [{"id": "q1"}]},
        )

    def test_retry_creates_new_attempt_old_intact(self):
        self._make_ps()
        a1 = self.client.post("/api/artifacts/problem-sets/ps-1/attempts/",
                              {"question_id": "q1", "code": "v1", "score": 40}, format="json")
        a2 = self.client.post("/api/artifacts/problem-sets/ps-1/attempts/",
                              {"question_id": "q1", "code": "v2", "score": 80}, format="json")
        self.assertEqual(a1.status_code, 201)
        self.assertEqual(a2.status_code, 201)
        attempts = ProblemSetAttempt.objects.filter(question_id="q1").order_by("created_at", "id")
        self.assertEqual(attempts.count(), 2)
        self.assertEqual(attempts[0].code, "v1")  # first attempt untouched
        self.assertEqual(attempts[0].score, 40)
        self.assertEqual(attempts[1].score, 80)

    def test_attempt_source_reflects_generation(self):
        self._make_ps(uid="ps-orig", gen=0)
        self._make_ps(uid="ps-regen", gen=1)
        self.client.post("/api/artifacts/problem-sets/ps-orig/attempts/",
                         {"question_id": "q1", "score": 50}, format="json")
        self.client.post("/api/artifacts/problem-sets/ps-regen/attempts/",
                         {"question_id": "q1", "score": 50}, format="json")
        self.assertEqual(ProblemSetAttempt.objects.get(problem_set__ps_uid="ps-orig").source, "original")
        self.assertEqual(ProblemSetAttempt.objects.get(problem_set__ps_uid="ps-regen").source, "regenerated")


# ── Regeneration cap + per-plan_version reset ─────────────────────────────────

class RegenCapTests(Base):
    def _create(self, plan_version, regenerate, uid):
        return self.client.post("/api/artifacts/problem-sets/", {
            "course_id": self.course.id, "lesson_id": self.lesson.id,
            "plan_version": plan_version, "regenerate": regenerate, "ps_uid": uid,
            "content_json": {"questions": [{"id": "q1"}]},
        }, format="json")

    def test_three_regens_then_fourth_rejected_and_reset_on_new_plan(self):
        self.assertEqual(self._create(1, False, "v1-g0").status_code, 201)  # gen 0
        self.assertEqual(self._create(1, True, "v1-g1").status_code, 201)   # regen 1
        self.assertEqual(self._create(1, True, "v1-g2").status_code, 201)   # regen 2
        self.assertEqual(self._create(1, True, "v1-g3").status_code, 201)   # regen 3
        self.assertEqual(self._create(1, True, "v1-g4").status_code, 409)   # 4th → rejected

        # Old generations are RETAINED (superseded), never deleted.
        self.assertEqual(ProblemSet.objects.filter(plan_version=1).count(), 4)
        self.assertEqual(ProblemSet.objects.filter(plan_version=1, superseded=False).count(), 1)

        # Counter RESETS when plan_version changes (a new plan = different course).
        self.assertEqual(self._create(2, False, "v2-g0").status_code, 201)
        self.assertEqual(self._create(2, True, "v2-g1").status_code, 201)   # allowed again

    def test_regen_count_endpoint(self):
        self._create(1, False, "g0")
        self._create(1, True, "g1")
        resp = self.client.get("/api/artifacts/problem-sets/regen-count/", {
            "course": self.course.id, "lesson": self.lesson.id, "plan_version": 1,
        })
        self.assertEqual(resp.json(), {"regenerations_used": 1, "remaining": 2, "max": 3})


# ── Best-score aggregation (per-question-best → mean → best-generation) ────────

class BestScoreTests(Base):
    def _ps(self, uid, gen, questions):
        return ProblemSet.objects.create(
            enrollment=self.enr, student=self.user, course=self.course, lesson=self.lesson,
            plan_version=1, generation_index=gen, ps_uid=uid,
            content_json={"questions": questions}, num_questions=len(questions),
        )

    def _attempt(self, ps, qid, score):
        ProblemSetAttempt.objects.create(problem_set=ps, question_id=qid, score=score)

    def test_single_question_best_attempt(self):
        ps = self._ps("g0", 0, [{"id": "q1"}])
        for s in (40, 80, 60):  # acceptance: 40, 80, 60 -> 80
            self._attempt(ps, "q1", s)
        self.assertEqual(generation_score(ps), 80.0)
        resp = self.client.get("/api/artifacts/problem-sets/score/", {
            "course": self.course.id, "lesson": self.lesson.id, "plan_version": 1,
        })
        self.assertEqual(resp.json()["best_score"], 80.0)

    def test_aggregation_is_mean_across_questions_not_single_best(self):
        # gen A: q1 best 80, q2 best 40 -> mean 60
        a = self._ps("gA", 0, [{"id": "q1"}, {"id": "q2"}])
        self._attempt(a, "q1", 80); self._attempt(a, "q2", 40)
        # gen B: q1 best 100, q2 best 0 -> mean 50
        b = self._ps("gB", 1, [{"id": "q1"}, {"id": "q2"}])
        self._attempt(b, "q1", 100); self._attempt(b, "q2", 0)
        self.assertEqual(generation_score(a), 60.0)
        self.assertEqual(generation_score(b), 50.0)
        # Lesson best = best generation (60), NOT the single highest attempt (100).
        self.assertEqual(best_lesson_score(self.enr.id, self.lesson.id, 1), 60.0)

    def test_unattempted_question_counts_zero(self):
        ps = self._ps("g0", 0, [{"id": "q1"}, {"id": "q2"}])
        self._attempt(ps, "q1", 100)  # q2 never attempted
        self.assertEqual(generation_score(ps), 50.0)


# ── Placement re-take: event immutability + latest snapshot source ────────────

class PlacementTests(Base):
    def _submit(self, score, concept_results):
        return self.client.post("/api/artifacts/placement-attempts/", {
            "course_id": self.course.id, "answers": [{"q": 1}],
            "per_question": [{"is_correct": score > 50}],
            "score": score, "concept_results": concept_results,
        }, format="json")

    def test_retake_appends_and_latest_recomputes(self):
        r1 = self._submit(40, {"c1": 0.4})
        r2 = self._submit(80, {"c1": 0.8})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(PlacementAttempt.objects.filter(student=self.user).count(), 2)

        latest = self.client.get("/api/artifacts/placement-attempts/latest/",
                                 {"course": self.course.id})
        self.assertEqual(latest.json()["score"], 80)  # snapshot source = latest

        # First attempt remains immutable / queryable.
        first = PlacementAttempt.objects.get(pk=r1.json()["id"])
        self.assertEqual(first.score, 40)
        self.assertEqual(first.concept_results, {"c1": 0.4})


# ── Ownership: key obscurity is not access control ────────────────────────────

class OwnershipTests(Base):
    def test_other_user_cannot_fetch_content(self):
        resp = self.client.post("/api/artifacts/", {
            "artifact_type": "slides", "course_id": self.course.id,
            "session_number": 1, "plan_version": 1, "content_json": {"x": 1},
        }, format="json")
        art_id = resp.json()["id"]

        intruder = User.objects.create_user(username="bad", email="bad@x.com", password="pw")
        got = _client(intruder).get(f"/api/artifacts/{art_id}/content/")
        self.assertEqual(got.status_code, 403)

    def test_other_user_cannot_append_attempt(self):
        ProblemSet.objects.create(
            enrollment=self.enr, student=self.user, course=self.course, lesson=self.lesson,
            plan_version=1, generation_index=0, ps_uid="ps-x",
            content_json={"questions": [{"id": "q1"}]},
        )
        intruder = User.objects.create_user(username="bad2", email="bad2@x.com", password="pw")
        got = _client(intruder).post("/api/artifacts/problem-sets/ps-x/attempts/",
                                     {"question_id": "q1", "score": 100}, format="json")
        self.assertEqual(got.status_code, 403)
