"""Capstone submission-path consolidation (Batch: one grading path + recovery).

Covers the acceptance criteria:
  - exactly one code path produces a rubric score/verdict; submit_from_repo now
    reaches it (and ignores client-supplied repo/sha);
  - a CI-green submission cannot end un-completable (webhook is feedback only);
  - provisioned repos are private;
  - main is never mutated (no move_ref);
  - stuck "evaluating" grades are detected and recovered, concurrency-safe;
  - rewards stay idempotent across the RECOVERY path (PASS twice → XP once).
"""

import threading
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone as dj_tz
from rest_framework.test import APIClient

from apps.users.models import User, StudentProfile
from apps.courses.models import Course, Enrollment
from apps.capstone.models import Capstone, CapstoneRubricItem, CapstoneSubmission
from apps.capstone import grading
from apps.capstone.views import CAPSTONE_XP

GIT = "apps.capstone.capstone_git"


def sync_worker():
    """Fresh patcher: run the grading worker synchronously in-process."""
    return mock.patch.object(
        grading, "_launch_worker",
        side_effect=lambda sid, sha: grading._run_grade(sid, sha),
    )


def _passing_ai(item_ids):
    return {"results": {str(i): {"passed": True, "evidence": "ok"} for i in item_ids},
            "feedback": "great"}


def _make(username="stu", with_repo=True, status="pending"):
    course = Course.objects.create(title="C", total_lessons_count=1)
    cap = Capstone.objects.create(course=course, title="Cap", status="active")
    item = CapstoneRubricItem.objects.create(capstone=cap, text="works", category="core", weight=1)
    user = User.objects.create_user(username=username, email=f"{username}@x.com", password="pw")
    StudentProfile.objects.create(user=user)
    enr = Enrollment.objects.create(student=user, course=course)
    sub = CapstoneSubmission.objects.create(
        capstone=cap, enrollment=enr,
        repo_url="https://github.com/org/repo" if with_repo else "",
        branch="work", status=status,
    )
    return {"course": course, "cap": cap, "item": item, "user": user, "enr": enr, "sub": sub}


# ── A) One grading path: submit_from_repo reaches the evaluator ──────────────

class SubmitFromRepoTests(TestCase):
    def setUp(self):
        self.c = _make()

    @sync_worker()
    @mock.patch(f"{GIT}.read_repo_bundle", return_value="print('hi')")
    @mock.patch("apps.capstone.views._call_ai_evaluate")
    @mock.patch(f"{GIT}.get_check_runs", return_value={"status": "completed", "conclusion": "success"})
    @mock.patch(f"{GIT}.head_sha", return_value="a" * 40)
    def test_reaches_evaluator_and_ignores_client_repo(self, m_head, m_ci, m_ai, m_bundle, m_worker):
        m_ai.return_value = _passing_ai([self.c["item"].id])
        client = APIClient(); client.force_authenticate(self.c["user"])
        resp = client.post(
            f"/api/capstone/capstones/{self.c['cap'].id}/submit-from-repo/",
            {"repo_url": "https://github.com/evil/copy", "commit_sha": "dead", "github_username": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        sub = self.c["sub"]; sub.refresh_from_db()
        # Verdict (the sole completion signal) is set — not a dead-end.
        self.assertEqual(sub.verdict, "pass")
        self.assertEqual(sub.status, "completed")
        # Client repo/sha ignored: graded the PROVISIONED repo at the server SHA.
        self.assertEqual(sub.repo_url, "https://github.com/org/repo")
        m_bundle.assert_called_once_with("https://github.com/org/repo", "a" * 40)

    @mock.patch(f"{GIT}.head_sha", return_value="a" * 40)
    @mock.patch(f"{GIT}.get_check_runs", return_value={"status": "completed", "conclusion": "failure"})
    def test_ci_red_blocks_with_409(self, m_ci, m_head):
        client = APIClient(); client.force_authenticate(self.c["user"])
        resp = client.post(f"/api/capstone/capstones/{self.c['cap'].id}/submit-from-repo/", {}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_requires_provisioned_repo(self):
        c = _make(username="norepo", with_repo=False)
        client = APIClient(); client.force_authenticate(c["user"])
        resp = client.post(f"/api/capstone/capstones/{c['cap'].id}/submit-from-repo/", {}, format="json")
        self.assertEqual(resp.status_code, 409)


# ── D) submit_for_grading never mutates main ────────────────────────────────

class SubmitForGradingTests(TestCase):
    def setUp(self):
        self.c = _make()

    @sync_worker()
    @mock.patch(f"{GIT}.move_ref")
    @mock.patch(f"{GIT}.read_repo_bundle", return_value="print('hi')")
    @mock.patch("apps.capstone.views._call_ai_evaluate")
    @mock.patch(f"{GIT}.get_check_runs", return_value={"status": "completed", "conclusion": "success"})
    @mock.patch(f"{GIT}.head_sha", return_value="b" * 40)
    def test_no_move_ref_grades_work_sha(self, m_head, m_ci, m_ai, m_bundle, m_move, m_worker):
        m_ai.return_value = _passing_ai([self.c["item"].id])
        client = APIClient(); client.force_authenticate(self.c["user"])
        resp = client.post(f"/api/capstone/capstones/{self.c['cap'].id}/submit-for-grading/", {}, format="json")
        self.assertEqual(resp.status_code, 202, resp.content)
        m_move.assert_not_called()  # main is never moved
        m_bundle.assert_called_once_with("https://github.com/org/repo", "b" * 40)
        self.c["sub"].refresh_from_db()
        self.assertEqual(self.c["sub"].verdict, "pass")


# ── A) Webhook is feedback only — never completion ───────────────────────────

class WebhookTests(TestCase):
    def setUp(self):
        self.c = _make(status="evaluating")
        self.c["sub"].latest_commit_sha = "c" * 40
        self.c["sub"].save()

    @override_settings(GITHUB_WEBHOOK_SECRET="s3cret")
    def test_check_suite_does_not_touch_status_or_verdict(self):
        import hashlib, hmac, json
        body = json.dumps({
            "check_suite": {"conclusion": "success", "head_sha": "c" * 40},
            "repository": {"html_url": "https://github.com/org/repo"},
        }).encode()
        sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        client = APIClient()
        resp = client.post(
            "/api/capstone/github-webhook/", data=body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig, HTTP_X_GITHUB_EVENT="check_suite",
        )
        self.assertEqual(resp.status_code, 200)
        self.c["sub"].refresh_from_db()
        self.assertEqual(self.c["sub"].status, "evaluating")  # unchanged
        self.assertEqual(self.c["sub"].verdict, "pending")    # never set by webhook


# ── B) Provisioned repos are private ─────────────────────────────────────────

class ProvisionPrivacyTests(TestCase):
    @override_settings(GITHUB_ORG="myorg")
    @mock.patch(f"{GIT}.ensure_branch")
    @mock.patch("apps.capstone.github_app.github_headers", return_value={})
    @mock.patch("apps.capstone.views.requests")
    def test_repo_created_private(self, m_req, m_hdrs, m_branch):
        m_req.post.return_value.status_code = 201
        m_req.post.return_value.json.return_value = {"html_url": "https://github.com/myorg/repo"}
        m_req.put.return_value.status_code = 200
        c = _make(username="prov", with_repo=False)
        client = APIClient(); client.force_authenticate(c["user"])
        resp = client.post(
            f"/api/capstone/capstones/{c['cap'].id}/provision-repo/",
            {"github_username": "prov-gh"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        create_call = m_req.post.call_args
        self.assertTrue(create_call.kwargs["json"]["private"])


# ── C) Stuck-grade recovery ──────────────────────────────────────────────────

def _make_stuck(username, *, attempts=1, with_repo=True, minutes_ago=30):
    c = _make(username=username, with_repo=with_repo, status="evaluating")
    sub = c["sub"]
    sub.grading_attempts = attempts
    sub.grading_started_at = dj_tz.now() - timedelta(minutes=minutes_ago)
    if with_repo:
        sub.latest_commit_sha = "d" * 40
    sub.save()
    return c


class RecoveryTests(TestCase):
    @sync_worker()
    @mock.patch(f"{GIT}.read_repo_bundle", return_value="print('hi')")
    @mock.patch("apps.capstone.views._call_ai_evaluate")
    def test_repo_backed_stuck_is_requeued_and_graded(self, m_ai, m_bundle, m_worker):
        c = _make_stuck("req")
        m_ai.return_value = _passing_ai([c["item"].id])
        result = grading.recover_stuck_grades()
        self.assertIn(c["sub"].id, result["requeued"])
        c["sub"].refresh_from_db()
        self.assertEqual(c["sub"].status, "completed")
        self.assertEqual(c["sub"].verdict, "pass")

    def test_out_of_attempts_fails(self):
        c = _make_stuck("exhausted", attempts=grading.MAX_GRADING_ATTEMPTS)
        result = grading.recover_stuck_grades()
        self.assertIn(c["sub"].id, result["failed"])
        c["sub"].refresh_from_db()
        self.assertEqual(c["sub"].status, "failed")

    def test_archive_stuck_no_repo_fails(self):
        c = _make_stuck("archive", with_repo=False)
        result = grading.recover_stuck_grades()
        self.assertIn(c["sub"].id, result["failed"])
        c["sub"].refresh_from_db()
        self.assertEqual(c["sub"].status, "failed")

    def test_fresh_grade_not_recovered(self):
        c = _make_stuck("fresh", minutes_ago=1)  # within timeout
        result = grading.recover_stuck_grades()
        self.assertNotIn(c["sub"].id, result["requeued"] + result["failed"])


# ── C+4) Idempotent rewards across the RECOVERY path ─────────────────────────

class RecoveryRewardIdempotencyTests(TestCase):
    @sync_worker()
    @mock.patch(f"{GIT}.read_repo_bundle", return_value="print('hi')")
    @mock.patch("apps.capstone.views._call_ai_evaluate")
    def test_pass_twice_via_recovery_awards_xp_once(self, m_ai, m_bundle, m_worker):
        c = _make_stuck("rew")
        m_ai.return_value = _passing_ai([c["item"].id])

        # First recovery: stuck → recovered → graded → PASS (rewards granted once).
        grading.recover_stuck_grades()
        sub = c["sub"]; sub.refresh_from_db()
        self.assertEqual(sub.verdict, "pass")
        self.assertTrue(sub.mastery_applied)
        xp_first = StudentProfile.objects.get(user=c["user"]).current_xp
        self.assertEqual(xp_first, CAPSTONE_XP)  # score 100 → full XP
        awarded_first = sub.xp_awarded

        # Make it look stuck again and recover a SECOND time → grades PASS again.
        sub.status = "evaluating"
        sub.grading_started_at = dj_tz.now() - timedelta(minutes=30)
        sub.save(update_fields=["status", "grading_started_at"])
        grading.recover_stuck_grades()

        sub.refresh_from_db()
        self.assertEqual(sub.verdict, "pass")
        # Rewards did NOT multiply across the recovery re-grade.
        self.assertEqual(sub.xp_awarded, awarded_first)
        self.assertEqual(StudentProfile.objects.get(user=c["user"]).current_xp, xp_first)


# ── 2) start_grading claim is atomic (no double worker) ──────────────────────

class StartGradingConcurrencyTests(TransactionTestCase):
    def test_concurrent_starts_launch_one_worker(self):
        c = _make(username="concur")
        launches = []
        lock = threading.Lock()

        def record(sid, sha):
            with lock:
                launches.append(sid)

        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            try:
                grading.start_grading(c["sub"], "e" * 40)
            finally:
                connection.close()

        with mock.patch.object(grading, "_launch_worker", side_effect=record):
            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start(); t2.start(); t1.join(); t2.join()

        self.assertEqual(len(launches), 1)  # exactly one worker launched
        c["sub"].refresh_from_db()
        self.assertEqual(c["sub"].grading_attempts, 1)  # claimed once


# ── 3) recover_stuck_grades is concurrency-safe (no double requeue) ───────────

class RecoveryConcurrencyTests(TransactionTestCase):
    def test_concurrent_recovery_requeues_once(self):
        c = _make_stuck("concur_rec")  # attempts=1, stuck 30m
        launches = []
        lock = threading.Lock()

        def record(sid, sha):
            with lock:
                launches.append(sid)

        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            try:
                grading.recover_stuck_grades()
            finally:
                connection.close()

        with mock.patch.object(grading, "_launch_worker", side_effect=record):
            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start(); t2.start(); t1.join(); t2.join()

        self.assertEqual(len(launches), 1)  # only one pass requeued
        c["sub"].refresh_from_db()
        self.assertEqual(c["sub"].grading_attempts, 2)  # incremented exactly once
