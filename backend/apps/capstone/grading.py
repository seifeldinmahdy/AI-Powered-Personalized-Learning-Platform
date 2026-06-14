"""
Capstone grading state machine + stuck-grade recovery.

Grading runs in a worker thread (no task queue in this stack). The risk is a
process death mid-grade leaving a submission pinned in ``status="evaluating"``
forever — and since course completion gates on ``verdict=="pass"`` (set ONLY by
the deterministic evaluator in views._evaluate_and_grade), a stuck row is an
un-completable course.

This module wraps grading in a small state machine:

  - ``start_grading`` claims a submission atomically (check-and-set under a row
    lock) before launching the worker, so two near-simultaneous submits for the
    same submission cannot both launch a worker.
  - ``recover_stuck_grades`` finds rows stuck in "evaluating" past a timeout and
    either re-queues them (repo-backed, bounded by max attempts) or fails them.
    It runs from both cron and an opportunistic GET, so every decision is
    re-checked UNDER the lock to prevent double-requeue / double-increment.

The rubric verdict remains the sole completion signal; the CI webhook is
feedback only and never touches this state machine.
"""

import logging
import threading
from datetime import timedelta

from django.db import transaction
from django.utils import timezone as dj_timezone

from .models import CapstoneSubmission

logger = logging.getLogger(__name__)

# A grade attempt older than this (and still "evaluating") is considered stuck.
GRADING_TIMEOUT_MINUTES = 10
# Total launch attempts (initial + recoveries) before giving up on a submission.
MAX_GRADING_ATTEMPTS = 3


def _is_stuck(sub: CapstoneSubmission, cutoff) -> bool:
    """True if this submission is mid-grade but its attempt predates the cutoff."""
    return (
        sub.status == "evaluating"
        and sub.grading_started_at is not None
        and sub.grading_started_at < cutoff
    )


def _claim_new_grade(submission_id: int, sha: str, timeout_minutes: int) -> bool:
    """Atomically claim a submission for a FRESH grade.

    Returns True iff THIS call transitioned it into grading. A submission that is
    already actively grading (status="evaluating" with a non-stale start) is left
    alone and False is returned — guaranteeing a single worker per active grade.
    """
    cutoff = dj_timezone.now() - timedelta(minutes=timeout_minutes)
    with transaction.atomic():
        sub = CapstoneSubmission.objects.select_for_update().get(pk=submission_id)
        actively_grading = (
            sub.status == "evaluating"
            and sub.grading_started_at is not None
            and sub.grading_started_at >= cutoff
        )
        if actively_grading:
            return False
        sub.status = "evaluating"
        sub.grading_started_at = dj_timezone.now()
        sub.grading_attempts = (sub.grading_attempts or 0) + 1
        sub.latest_commit_sha = sha
        sub.save(update_fields=[
            "status", "grading_started_at", "grading_attempts", "latest_commit_sha",
        ])
    return True


def start_grading(sub: CapstoneSubmission, sha: str, *,
                  timeout_minutes: int = GRADING_TIMEOUT_MINUTES) -> bool:
    """Check-and-set under a row lock, then launch the grading worker.

    Returns True if a worker was launched, False if the submission was already
    being graded (the caller can surface "already grading" without re-launching).
    """
    if not _claim_new_grade(sub.id, sha, timeout_minutes):
        logger.info("start_grading: submission %s already grading; not relaunching", sub.id)
        return False
    _launch_worker(sub.id, sha)
    return True


def _launch_worker(submission_id: int, sha: str) -> None:
    """Launch the grading worker. Isolated so tests can run it synchronously."""
    threading.Thread(target=_run_grade, args=(submission_id, sha), daemon=True).start()


def _fail(sub: CapstoneSubmission, message: str) -> None:
    sub.status = "failed"
    sub.feedback = message
    sub.grading_started_at = None
    sub.save(update_fields=["status", "feedback", "grading_started_at"])


def _run_grade(submission_id: int, sha: str) -> None:
    """Worker: read the repo at ``sha`` and grade it through the ONE shared,
    deterministic evaluator. Sets a terminal status on every handled path so the
    row never lingers in 'evaluating' on a known error (unhandled process death
    is what recover_stuck_grades exists for)."""
    from .capstone_git import read_repo_bundle, GitError
    from .views import _evaluate_and_grade  # the single rubric evaluator

    try:
        sub = CapstoneSubmission.objects.select_related(
            "capstone", "enrollment__student", "proposal", "team"
        ).get(pk=submission_id)
    except CapstoneSubmission.DoesNotExist:
        return

    proposal_text = ""
    if sub.proposal_id:
        try:
            proposal_text = f"{sub.proposal.title}\n{sub.proposal.description}"
        except Exception:
            proposal_text = ""

    try:
        bundle = read_repo_bundle(sub.repo_url, sha)
    except GitError:
        logger.exception("read_repo_bundle failed during grading for submission %s", submission_id)
        _fail(sub, "Could not read repository for grading.")
        return

    if not bundle.strip():
        _fail(sub, "Repository contained no gradable text files.")
        return

    try:
        _evaluate_and_grade(sub, bundle, proposal_text)
    except Exception:
        logger.exception("grading crashed for submission %s", submission_id)
        sub.refresh_from_db()
        if sub.status == "evaluating":  # don't clobber a grade that did land
            _fail(sub, "Grading failed unexpectedly. Please re-submit.")


def _recover_one(submission_id: int, timeout_minutes: int, max_attempts: int) -> tuple:
    """Atomically re-check the stuck condition under the lock and claim ONE
    recovery action. Returns ("requeue", sha) | ("failed", None) | (None, None).

    Re-checking inside the lock is what makes concurrent recovery passes (cron +
    opportunistic GET) safe: whoever wins the lock first acts and bumps
    grading_started_at to now; the next pass sees a non-stale row and bows out,
    so attempts are never double-incremented and no second worker is launched.
    """
    cutoff = dj_timezone.now() - timedelta(minutes=timeout_minutes)
    with transaction.atomic():
        sub = CapstoneSubmission.objects.select_for_update().get(pk=submission_id)
        if not _is_stuck(sub, cutoff):
            return (None, None)  # another pass (or the worker) already handled it
        repo_backed = bool(sub.repo_url and sub.latest_commit_sha)
        if repo_backed and (sub.grading_attempts or 0) < max_attempts:
            sub.grading_started_at = dj_timezone.now()
            sub.grading_attempts = (sub.grading_attempts or 0) + 1
            sub.save(update_fields=["grading_started_at", "grading_attempts"])
            return ("requeue", sub.latest_commit_sha)
        # No repo to re-read (e.g. archive upload, bundle not stored), or out of
        # attempts → terminal failure with a clear, recoverable-by-resubmit message.
        sub.status = "failed"
        sub.grading_started_at = None
        sub.feedback = "Grading timed out and could not be recovered. Please re-submit."
        sub.save(update_fields=["status", "grading_started_at", "feedback"])
        return ("failed", None)


def recover_stuck_grades(timeout_minutes: int = GRADING_TIMEOUT_MINUTES,
                         max_attempts: int = MAX_GRADING_ATTEMPTS) -> dict:
    """Detect and recover submissions stuck in 'evaluating' past the timeout.

    Safe to run concurrently and repeatedly. Returns
    ``{"requeued": [ids], "failed": [ids]}``.
    """
    cutoff = dj_timezone.now() - timedelta(minutes=timeout_minutes)
    candidate_ids = list(
        CapstoneSubmission.objects.filter(
            status="evaluating", grading_started_at__lt=cutoff
        ).values_list("id", flat=True)
    )
    requeued, failed = [], []
    for sid in candidate_ids:
        action, sha = _recover_one(sid, timeout_minutes, max_attempts)
        if action == "requeue":
            requeued.append(sid)
            _launch_worker(sid, sha)
        elif action == "failed":
            failed.append(sid)
    if requeued or failed:
        logger.info("recover_stuck_grades: requeued=%s failed=%s", requeued, failed)
    return {"requeued": requeued, "failed": failed}
