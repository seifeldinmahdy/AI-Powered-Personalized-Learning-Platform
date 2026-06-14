"""
Capstone views.

Scoring invariant: The LLM never emits a score or grade.
AI service returns per-rubric-item {passed, evidence} binary results.
All numeric scores are computed here from weights.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.utils import timezone as dj_timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from .models import (
    Capstone, CapstoneProposal, CapstoneRubricItem, CapstoneSubmission,
    Team, MatchmakingQueueEntry, CapstoneAssistQuota, CapstoneAssistLog,
)
from .serializers import (
    CapstoneProposalSerializer,
    CapstoneRubricItemSerializer,
    CapstoneSerializer,
    CapstoneSubmissionSerializer,
    TeamSerializer,
    MatchmakingQueueEntrySerializer,
    CapstoneAssistQuotaSerializer,
)

logger = logging.getLogger(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
CAPSTONE_XP = 500  # base XP for a passing capstone submission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


def _get_effective_rubric(capstone: Capstone, team_size: int) -> list[CapstoneRubricItem]:
    """Return rubric items applicable to this team size."""
    return list(capstone.rubric_items.filter(min_team_size__lte=team_size))


def _compute_score(rubric_items: list[CapstoneRubricItem], results: dict) -> float:
    """
    Deterministic weighted score.  results = {str(item_id): {passed, weight, evidence}}.
    score = sum(weight * passed) / sum(weight * applicable) * 100
    """
    total_weight = sum(item.weight for item in rubric_items)
    if total_weight == 0:
        return 0.0
    earned = sum(
        item.weight
        for item in rubric_items
        if results.get(str(item.id), {}).get("passed", False)
    )
    return round(earned / total_weight * 100, 2)


def _compute_verdict(rubric_items: list, results: dict, pass_policy: str = "all_core") -> str:
    """
    PASS/FAIL computed in Python — the LLM never decides this.

    Policy 'all_core' (the only policy today, uniform across solo/team and
    admin-defined/student-proposed): PASS iff every applicable CORE criterion
    passes. Stretch criteria affect score/feedback but never the verdict.
    """
    core_items = [i for i in rubric_items if i.category == "core"]
    if not core_items:
        return "pass"  # no core criteria to gate on
    all_core_pass = all(
        results.get(str(i.id), {}).get("passed", False) for i in core_items
    )
    return "pass" if all_core_pass else "fail"


def _xp_to_level(xp: int) -> int:
    return min(10, xp // 200 + 1)


def _apply_xp_delta(student_id: int, delta: int) -> None:
    """Apply a signed XP delta to a student's profile (idempotent grading helper)."""
    if not delta:
        return
    from apps.users.models import StudentProfile
    try:
        profile, _ = StudentProfile.objects.get_or_create(user_id=student_id)
        profile.current_xp = max(0, (profile.current_xp or 0) + delta)
        profile.level = _xp_to_level(profile.current_xp)
        profile.save(update_fields=["current_xp", "level"])
    except Exception:
        logger.exception("Failed to apply XP delta to student %s", student_id)


def _update_concept_mastery_sync(student_id: int, results: dict, rubric_items: list[CapstoneRubricItem]) -> None:
    """Record capstone-grade mastery via the SINGLE writer (event-sourced).

    concept_id comes from the rubric item's FK; outcome is the per-concept mean
    pass rate. EMA + concurrency-safety now live in mastery_service.record_events.
    """
    from apps.progress.mastery_service import record_events

    concept_outcomes: dict[str, list[float]] = {}
    for item in rubric_items:
        if not item.concept_id:
            continue
        passed = results.get(str(item.id), {}).get("passed", False)
        concept_outcomes.setdefault(str(item.concept_id), []).append(1.0 if passed else 0.0)

    if not concept_outcomes:
        return

    events = [
        {
            "concept_id": cid,
            "outcome": sum(outcomes) / len(outcomes),
            "source": "capstone_grade",
            "alpha": 0.3,
        }
        for cid, outcomes in concept_outcomes.items()
    ]
    try:
        record_events(student_id, events)
    except Exception:
        logger.exception("Failed to record capstone-grade mastery for student %s", student_id)


def _normalize_results(rubric_items: list[CapstoneRubricItem], ai_result: dict) -> dict:
    """Turn the AI's {results: {id: {passed, evidence}}} into the stored shape,
    keyed by every applicable rubric item id (missing → failed)."""
    ai_results = ai_result.get("results", {})
    results = {}
    for item in rubric_items:
        key = str(item.id)
        item_result = ai_results.get(key) or ai_results.get(int(item.id), {}) or {}
        results[key] = {
            "passed": bool(item_result.get("passed", False)),
            "weight": item.weight,
            "evidence": item_result.get("evidence", ""),
        }
    return results


def _apply_grade(sub, team, rubric_items, results, score, verdict,
                 feedback, contributions, student_id) -> None:
    """
    Persist grade + fire reward side-effects idempotently.

    - results/score/verdict/feedback/contributions are SET every grade
      (re-submitting overwrites the stored result — status never locks).
    - Rewards (capstone XP + concept-mastery EMA + course completion) fire
      EXACTLY ONCE, on the first PASS. A FAIL grants nothing; a re-grade of an
      already-rewarded submission updates the stored result only. This is what
      makes the fail→fix→re-submit loop safe from multiplying rewards.
    """
    sub.team = team
    sub.results = results
    sub.score = score
    sub.verdict = verdict
    sub.feedback = feedback
    sub.contributions = contributions
    sub.status = "completed"
    sub.evaluated_at = dj_timezone.now()

    fields = ["team", "results", "score", "verdict", "feedback",
              "contributions", "status", "evaluated_at"]

    grant_rewards = verdict == "pass" and not sub.mastery_applied
    if grant_rewards:
        sub.mastery_applied = True
        sub.xp_awarded = int(CAPSTONE_XP * score / 100)
        fields += ["mastery_applied", "xp_awarded"]
    sub.save(update_fields=fields)

    if grant_rewards:
        _apply_xp_delta(student_id, sub.xp_awarded)
        _update_concept_mastery_sync(student_id, results, rubric_items)
        # Capstone PASS is the terminal gate → mark the course complete.
        try:
            from apps.courses.completion import mark_complete_if_eligible
            mark_complete_if_eligible(sub.enrollment)
        except Exception:
            logger.exception("Could not mark course completion for submission %s", sub.id)


def _evaluate_and_grade(sub, code_bundle: str, proposal_text: str = "") -> None:
    """
    Core grading path shared by archive upload and repo (final) submission.

    Resolves the size-scaled rubric, calls the AI judge (binary only), computes
    the score in Python, summarizes team contributions, and applies the grade
    idempotently. Sets status='failed' (not an exception) on unrecoverable steps.
    """
    capstone = sub.capstone
    student = sub.enrollment.student

    team = sub.team or Team.objects.filter(capstone=capstone, members=student).first()
    team_size = team.members.count() if team else 1
    rubric_items = _get_effective_rubric(capstone, team_size)
    if not rubric_items:
        sub.status = "failed"
        sub.feedback = "No rubric items defined."
        sub.save(update_fields=["status", "feedback"])
        return

    ai_result = _call_ai_evaluate(capstone, rubric_items, code_bundle, proposal_text)
    if ai_result is None:
        sub.status = "failed"
        sub.feedback = "Evaluation service unavailable. Please retry."
        sub.save(update_fields=["status", "feedback"])
        return

    results = _normalize_results(rubric_items, ai_result)
    score = _compute_score(rubric_items, results)
    verdict = _compute_verdict(rubric_items, results, capstone.pass_policy)

    contributions = {}
    if team and sub.repo_url:
        try:
            from .capstone_git import summarize_contributions
            member_usernames = [m.username for m in team.members.all()]
            contributions = summarize_contributions(sub.repo_url, sub.branch, member_usernames)
        except Exception:
            logger.exception("contribution summary failed")

    _apply_grade(sub, team, rubric_items, results, score, verdict,
                 ai_result.get("feedback", ""), contributions, student.id)


def _call_ai_evaluate(capstone: Capstone, rubric_items: list[CapstoneRubricItem],
                      code_bundle: str, proposal_text: str) -> dict | None:
    """POST to AI service /capstone/evaluate. Returns results dict or None on error."""
    payload = {
        "capstone_title": capstone.title,
        "brief": capstone.brief_text,
        "rubric_items": [
            {"id": item.id, "text": item.text, "weight": item.weight, "category": item.category}
            for item in rubric_items
        ],
        "code_bundle": code_bundle,
        "proposal_text": proposal_text,
    }
    try:
        resp = requests.post(
            f"{AI_SERVICE_URL}/capstone/evaluate",
            json=payload,
            headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("AI capstone evaluate call failed")
        return None


# ---------------------------------------------------------------------------
# CapstoneViewSet
# ---------------------------------------------------------------------------

class CapstoneViewSet(viewsets.ModelViewSet):
    serializer_class = CapstoneSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if _is_admin(user):
            return Capstone.objects.all().prefetch_related("rubric_items")
        from apps.courses.models import Enrollment
        enrolled_course_ids = Enrollment.objects.filter(
            student=user
        ).values_list("course_id", flat=True)
        return Capstone.objects.filter(
            course_id__in=enrolled_course_ids,
            status__in=["active", "completed"],
        ).prefetch_related("rubric_items")

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    def create(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="draft-rubric")
    def draft_rubric(self, request, pk=None):
        """POST /capstone/<id>/draft-rubric/ — ask AI to draft rubric items."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        capstone = self.get_object()
        payload = {
            "capstone_title": capstone.title,
            "brief": capstone.brief_text,
            "spec_mode": capstone.spec_mode,
            "team_mode": capstone.team_mode,
        }
        try:
            resp = requests.post(
                f"{AI_SERVICE_URL}/capstone/draft-rubric",
                json=payload,
                headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
                timeout=60,
            )
            resp.raise_for_status()
            return Response(resp.json())
        except requests.HTTPError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            logger.exception("draft_rubric AI call failed")
            return Response({"error": "AI service unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @action(detail=True, methods=["post"], url_path="extract-spec")
    def extract_spec(self, request, pk=None):
        """POST /capstone/<id>/extract-spec/ — extract rubric criteria from an uploaded spec doc."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        capstone = self.get_object()
        spec_text = request.data.get("spec_text", "")
        if not spec_text:
            return Response({"error": "spec_text required."}, status=status.HTTP_400_BAD_REQUEST)
        payload = {
            "capstone_title": capstone.title,
            "spec_text": spec_text,
            "team_mode": capstone.team_mode,
        }
        try:
            resp = requests.post(
                f"{AI_SERVICE_URL}/capstone/extract-spec",
                json=payload,
                headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
                timeout=60,
            )
            resp.raise_for_status()
            return Response(resp.json())
        except requests.HTTPError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("extract_spec AI call failed")
            return Response({"error": "AI service unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# CapstoneRubricItemViewSet
# ---------------------------------------------------------------------------

class CapstoneRubricItemViewSet(viewsets.ModelViewSet):
    serializer_class = CapstoneRubricItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        capstone_pk = self.kwargs.get("capstone_pk")
        qs = CapstoneRubricItem.objects.filter(capstone_id=capstone_pk)
        if not _is_admin(self.request.user):
            return qs.filter(capstone__status__in=["active", "completed"])
        return qs

    def _require_admin(self):
        if not _is_admin(self.request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        return None

    def create(self, request, *args, **kwargs):
        err = self._require_admin()
        if err:
            return err
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        err = self._require_admin()
        if err:
            return err
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        err = self._require_admin()
        if err:
            return err
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(capstone_id=self.kwargs["capstone_pk"])


# ---------------------------------------------------------------------------
# CapstoneProposalViewSet
# ---------------------------------------------------------------------------

class CapstoneProposalViewSet(viewsets.ModelViewSet):
    serializer_class = CapstoneProposalSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        if _is_admin(user):
            return CapstoneProposal.objects.select_related("student", "capstone").all()
        return CapstoneProposal.objects.filter(student=user)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)

    def create(self, request, *args, **kwargs):
        if _is_admin(request.user):
            return Response({"error": "Admins do not submit proposals."}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        """POST /capstone/proposals/<id>/approve/ — admin approves or rejects."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        proposal = self.get_object()
        new_status = request.data.get("approval_status")
        if new_status not in ("approved", "rejected"):
            return Response({"error": "approval_status must be 'approved' or 'rejected'."}, status=status.HTTP_400_BAD_REQUEST)
        proposal.approval_status = new_status
        proposal.admin_feedback = request.data.get("admin_feedback", "")
        proposal.reviewed_at = dj_timezone.now()
        proposal.save(update_fields=["approval_status", "admin_feedback", "reviewed_at"])
        return Response(CapstoneProposalSerializer(proposal).data)

    @action(detail=True, methods=["post"], url_path="map-rubric")
    def map_rubric(self, request, pk=None):
        """POST /capstone/proposals/<id>/map-rubric/ — AI maps a student proposal to core criteria."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        proposal = self.get_object()
        capstone = proposal.capstone
        core_items = CapstoneRubricItem.objects.filter(capstone=capstone, category="core")
        payload = {
            "capstone_title": capstone.title,
            "brief": capstone.brief_text,
            "core_criteria": [{"id": i.id, "text": i.text} for i in core_items],
            "proposal_title": proposal.title,
            "proposal_description": proposal.description,
            "planned_features": proposal.planned_features,
        }
        try:
            resp = requests.post(
                f"{AI_SERVICE_URL}/capstone/map-proposal",
                json=payload,
                headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            if "confidence_score" in data:
                proposal.confidence_score = float(data["confidence_score"])
                proposal.save(update_fields=["confidence_score"])
            return Response(data)
        except requests.HTTPError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("map_rubric AI call failed")
            return Response({"error": "AI service unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# CapstoneSubmissionViewSet (student read-only)
# ---------------------------------------------------------------------------

class CapstoneSubmissionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CapstoneSubmissionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if _is_admin(user):
            return CapstoneSubmission.objects.select_related("enrollment", "capstone").all()
        return CapstoneSubmission.objects.filter(enrollment__student=user)


# ---------------------------------------------------------------------------
# Function views
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def capstone_for_course(request, course_id):
    """GET /capstone/course/<course_id>/ — return active capstone for a course."""
    user = request.user
    if _is_admin(user):
        cap = Capstone.objects.filter(course_id=course_id).prefetch_related("rubric_items").first()
    else:
        from apps.courses.models import Enrollment
        enrolled = Enrollment.objects.filter(student=user, course_id=course_id).exists()
        if not enrolled:
            return Response({"error": "Not enrolled."}, status=status.HTTP_403_FORBIDDEN)
        cap = Capstone.objects.filter(
            course_id=course_id, status__in=["active", "completed"]
        ).prefetch_related("rubric_items").first()

    if not cap:
        return Response({"error": "No capstone found for this course."}, status=status.HTTP_404_NOT_FOUND)
    return Response(CapstoneSerializer(cap).data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def my_submission(request, capstone_id):
    """GET /capstone/<capstone_id>/my-submission/ — student's own submission."""
    sub = CapstoneSubmission.objects.filter(
        capstone_id=capstone_id, enrollment__student=request.user
    ).first()
    if not sub:
        return Response({"error": "No submission found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(CapstoneSubmissionSerializer(sub).data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_archive(request, capstone_id):
    """
    POST /capstone/<capstone_id>/submit/
    Body: {code_bundle: str, proposal_id?: int}

    1. Resolve enrollment.
    2. Build effective rubric (solo → team_size=1).
    3. Call AI service /capstone/evaluate (LLM returns binary pass/fail only).
    4. Compute score deterministically in Django.
    5. Save CapstoneSubmission.
    6. Fire-and-forget: award XP, update concept mastery.
    """
    user = request.user
    code_bundle = request.data.get("code_bundle", "")
    if not code_bundle:
        return Response({"error": "code_bundle required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        capstone = Capstone.objects.prefetch_related("rubric_items").get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    from apps.courses.models import Enrollment
    enrollment = Enrollment.objects.filter(student=user, course=capstone.course).first()
    if not enrollment:
        return Response({"error": "Not enrolled in this course."}, status=status.HTTP_403_FORBIDDEN)

    # Resolve proposal (optional for admin_defined capstones)
    proposal = None
    proposal_id = request.data.get("proposal_id")
    proposal_text = ""
    if proposal_id:
        try:
            proposal = CapstoneProposal.objects.get(pk=proposal_id, student=user)
            proposal_text = f"{proposal.title}\n{proposal.description}"
        except CapstoneProposal.DoesNotExist:
            return Response({"error": "Proposal not found."}, status=status.HTTP_404_NOT_FOUND)

    # Resolve team + size-scaled rubric (Batch 3).
    # Solo → team_size=1 → core-only; full team → core+stretch.
    team = Team.objects.filter(capstone=capstone, members=user).first()
    team_size = team.members.count() if team else 1
    rubric_items = _get_effective_rubric(capstone, team_size)
    if not rubric_items:
        return Response({"error": "No rubric items defined."}, status=status.HTTP_400_BAD_REQUEST)

    # Create submission in evaluating state
    sub = CapstoneSubmission.objects.create(
        capstone=capstone,
        enrollment=enrollment,
        proposal=proposal,
        team=team,
        status="evaluating",
    )

    # Synchronous grade (archive submit is a one-shot; acceptable to block).
    # Deterministic score computed in Python; LLM only judges pass/fail.
    _evaluate_and_grade(sub, code_bundle, proposal_text)
    sub.refresh_from_db()

    http_status = (
        status.HTTP_201_CREATED if sub.status == "completed"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return Response(CapstoneSubmissionSerializer(sub).data, status=http_status)


# ---------------------------------------------------------------------------
# GitHub integration views
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def provision_repo(request, capstone_id):
    """
    POST /capstone/<capstone_id>/provision-repo/
    Body: {github_username: str}

    Creates a public repo from the capstone template under GITHUB_ORG,
    sets branch protection on main, and invites the student as collaborator.
    Never returns the installation token to the client.
    """
    if not settings.GITHUB_ORG:
        return Response({"error": "GitHub integration not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    github_username = request.data.get("github_username", "").strip()
    if not github_username:
        return Response({"error": "github_username required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    from apps.courses.models import Enrollment
    enrollment = Enrollment.objects.filter(student=request.user, course=capstone.course).first()
    if not enrollment:
        return Response({"error": "Not enrolled."}, status=status.HTTP_403_FORBIDDEN)

    # Idempotent: if this student already has a provisioned repo for this capstone,
    # return it instead of trying to create another (safe for auto-provision-on-start).
    existing = CapstoneSubmission.objects.filter(
        capstone=capstone, enrollment=enrollment
    ).exclude(repo_url="").first()
    if existing and existing.repo_url:
        return Response({
            "repo_url": existing.repo_url,
            "repo_name": existing.repo_url.rstrip("/").split("/")[-1],
            "branch": existing.branch,
            "already_provisioned": True,
        })

    from .github_app import github_headers

    repo_name = f"capstone-{capstone_id}-{request.user.username}"
    org = settings.GITHUB_ORG

    try:
        hdrs = github_headers()

        # 1. Create repo from template (or blank if no template set)
        if capstone.github_template_repo:
            owner, template = capstone.github_template_repo.split("/", 1)
            create_resp = requests.post(
                f"https://api.github.com/repos/{owner}/{template}/generate",
                json={"owner": org, "name": repo_name, "private": False},
                headers=hdrs,
                timeout=30,
            )
        else:
            create_resp = requests.post(
                f"https://api.github.com/orgs/{org}/repos",
                json={"name": repo_name, "private": False, "auto_init": True},
                headers=hdrs,
                timeout=30,
            )

        if create_resp.status_code not in (200, 201):
            return Response({"error": create_resp.json()}, status=status.HTTP_502_BAD_GATEWAY)

        repo_data = create_resp.json()
        repo_url = repo_data.get("html_url", f"https://github.com/{org}/{repo_name}")

        # 2. Branch protection on main
        requests.put(
            f"https://api.github.com/repos/{org}/{repo_name}/branches/main/protection",
            json={
                "required_status_checks": {"strict": True, "contexts": ["ci"]},
                "enforce_admins": False,
                "required_pull_request_reviews": None,
                "restrictions": None,
            },
            headers=hdrs,
            timeout=15,
        )

        # 3. Invite student as collaborator with push access
        requests.put(
            f"https://api.github.com/repos/{org}/{repo_name}/collaborators/{github_username}",
            json={"permission": "push"},
            headers=hdrs,
            timeout=15,
        )

        # 4. Create the 'work' feature branch (students never commit to main)
        branch = "work"
        try:
            from .capstone_git import ensure_branch
            ensure_branch(repo_url, branch)
        except Exception:
            logger.exception("Could not pre-create work branch for %s", repo_name)

        # 5. Persist a submission stub so the workspace can resolve the repo
        CapstoneSubmission.objects.update_or_create(
            capstone=capstone,
            enrollment=enrollment,
            defaults={
                "repo_url": repo_url,
                "branch": branch,
                "github_username": github_username,
                "status": "pending",
            },
        )

        return Response({"repo_url": repo_url, "repo_name": repo_name, "branch": branch})

    except Exception:
        logger.exception("provision_repo failed for capstone %s", capstone_id)
        return Response({"error": "GitHub provisioning failed."}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(["POST"])
@permission_classes([])  # No auth — GitHub sends unsigned webhooks
def github_webhook(request):
    """
    POST /capstone/github-webhook/
    Verifies HMAC-SHA256 signature, then records push/check_suite events.
    Updates CapstoneSubmission on CI completion (check_suite conclusion=success/failure).
    """
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        return Response({"error": "Webhook secret not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    sig_header = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
    body = request.body

    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_header):
        return Response({"error": "Invalid signature."}, status=status.HTTP_403_FORBIDDEN)

    event = request.META.get("HTTP_X_GITHUB_EVENT", "")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response({"error": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)

    if event == "check_suite":
        conclusion = payload.get("check_suite", {}).get("conclusion")
        repo_url = payload.get("repository", {}).get("html_url", "")
        head_sha = payload.get("check_suite", {}).get("head_sha", "")
        if repo_url and head_sha and conclusion in ("success", "failure"):
            CapstoneSubmission.objects.filter(
                repo_url=repo_url,
                latest_commit_sha=head_sha,
                status="evaluating",
            ).update(
                status="completed" if conclusion == "success" else "failed",
                evaluated_at=dj_timezone.now(),
            )

    return Response({"received": event})


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_from_repo(request, capstone_id):
    """
    POST /capstone/<capstone_id>/submit-from-repo/
    Body: {repo_url: str, commit_sha: str, github_username: str}

    Records the submission intent.  Actual evaluation is triggered by the
    github_webhook when the CI check_suite concludes.
    The platform never stores cloned code — only repo_url + commit_sha.
    """
    repo_url = request.data.get("repo_url", "").strip()
    commit_sha = request.data.get("commit_sha", "").strip()
    github_username = request.data.get("github_username", "").strip()

    if not repo_url or not commit_sha:
        return Response({"error": "repo_url and commit_sha required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    from apps.courses.models import Enrollment
    enrollment = Enrollment.objects.filter(student=request.user, course=capstone.course).first()
    if not enrollment:
        return Response({"error": "Not enrolled."}, status=status.HTTP_403_FORBIDDEN)

    sub, created = CapstoneSubmission.objects.update_or_create(
        capstone=capstone,
        enrollment=enrollment,
        defaults={
            "repo_url": repo_url,
            "latest_commit_sha": commit_sha,
            "github_username": github_username,
            "status": "evaluating",
            "score": None,
            "results": {},
            "feedback": "",
        },
    )

    return Response(
        CapstoneSubmissionSerializer(sub).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


def _grade_from_repo(submission_id: int, sha: str) -> None:
    """
    Background worker: read the repo at `sha` into a transient bundle and grade
    it through the shared deterministic pipeline. The code is never persisted.
    """
    from .capstone_git import read_repo_bundle, GitError

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
        sub.status = "failed"
        sub.feedback = "Could not read repository for grading."
        sub.save(update_fields=["status", "feedback"])
        return

    if not bundle.strip():
        sub.status = "failed"
        sub.feedback = "Repository contained no gradable text files."
        sub.save(update_fields=["status", "feedback"])
        return

    _evaluate_and_grade(sub, bundle, proposal_text)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_for_grading(request, capstone_id):
    """
    POST /capstone/<capstone_id>/submit-for-grading/

    Final submission from the in-platform IDE:
      1. Resolve the student's work-branch HEAD.
      2. Require CI to be GREEN on that exact commit (continuous feedback gate).
      3. Fast-forward `main` to that CI-passed commit. Branch protection stays
         satisfied because the required `ci` status check already passed for
         this SHA, and the App may update the ref.
      4. Grade `main` (== that commit) in the background through the shared,
         deterministic pipeline. Idempotent: re-submitting re-scores without
         multiplying XP/mastery. Code is read transiently and never stored.
    """
    sub, _capstone, err = _resolve_submission(request.user, capstone_id)
    if err:
        return err

    from .capstone_git import head_sha, get_check_runs, move_ref, GitError

    # 1. Work-branch HEAD
    try:
        work_sha = head_sha(sub.repo_url, sub.branch)
    except GitError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    # 2. CI must be green on that commit
    try:
        verdict = get_check_runs(sub.repo_url, work_sha)
    except GitError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    if verdict.get("status") != "completed" or verdict.get("conclusion") != "success":
        return Response(
            {
                "error": "CI must pass on your latest commit before submitting for grading.",
                "verdict": verdict,
            },
            status=status.HTTP_409_CONFLICT,
        )

    # 3. Fast-forward main to the CI-passed commit (FF only; never a force push)
    try:
        move_ref(sub.repo_url, "main", work_sha, force=False)
    except GitError as exc:
        logger.warning("submit_for_grading: could not fast-forward main: %s", exc)
        return Response(
            {"error": f"Could not promote your commit to main: {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # 4. Mark evaluating and grade main (== work_sha) in the background
    sub.latest_commit_sha = work_sha
    sub.status = "evaluating"
    sub.save(update_fields=["latest_commit_sha", "status"])

    threading.Thread(
        target=_grade_from_repo,
        args=(sub.id, work_sha),
        daemon=True,
    ).start()

    return Response(
        {
            "status": "evaluating",
            "commit_sha": work_sha,
            "submission": CapstoneSubmissionSerializer(sub).data,
        },
        status=status.HTTP_202_ACCEPTED,
    )


# ===========================================================================
# Batch 3 — In-platform IDE, commit pipeline, CI verdict, run, AI assist, teams
# ===========================================================================

def _resolve_submission(user, capstone_id) -> tuple:
    """
    Return (submission, capstone, error_response). The submission carries the
    repo_url + branch the student works on. Created during repo provisioning.
    """
    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return None, None, Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    sub = CapstoneSubmission.objects.filter(
        capstone_id=capstone_id, enrollment__student=user
    ).first()
    if not sub or not sub.repo_url:
        return None, capstone, Response(
            {"error": "No repo provisioned yet. Provision your repo first."},
            status=status.HTTP_409_CONFLICT,
        )
    return sub, capstone, None


# ---------------------------------------------------------------------------
# Part A — Workspace read endpoints (server-side via github_app.py)
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def repo_tree(request, capstone_id):
    """GET /capstone/<id>/tree/ — recursive file tree on the student's branch."""
    sub, _capstone, err = _resolve_submission(request.user, capstone_id)
    if err:
        return err
    from .capstone_git import get_tree, GitError
    try:
        tree = get_tree(sub.repo_url, sub.branch)
        return Response({"branch": sub.branch, "tree": tree})
    except GitError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        logger.exception("repo_tree failed")
        return Response({"error": "Could not read repo tree."}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def repo_file(request, capstone_id):
    """GET /capstone/<id>/file/?path=... — file contents, fetched lazily."""
    path = request.query_params.get("path", "")
    if not path:
        return Response({"error": "path param required."}, status=status.HTTP_400_BAD_REQUEST)
    sub, _capstone, err = _resolve_submission(request.user, capstone_id)
    if err:
        return err
    from .capstone_git import get_file, GitError
    try:
        return Response(get_file(sub.repo_url, sub.branch, path))
    except GitError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("repo_file failed")
        return Response({"error": "Could not read file."}, status=status.HTTP_502_BAD_GATEWAY)


# ---------------------------------------------------------------------------
# Part B — Commit pipeline
# ---------------------------------------------------------------------------

# Per-student commit rate limit (simple in-process cache).
_COMMIT_RATE_LIMIT = 20          # commits
_COMMIT_RATE_WINDOW = 3600       # seconds


def _commit_rate_ok(user_id) -> bool:
    from django.core.cache import cache
    key = f"capstone_commit_rate_{user_id}"
    count = cache.get(key, 0)
    if count >= _COMMIT_RATE_LIMIT:
        return False
    cache.set(key, count + 1, _COMMIT_RATE_WINDOW)
    return True


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def commit_files(request, capstone_id):
    """
    POST /capstone/<id>/commit/
    Body: {changed_files: [{path, content, deleted?}], message: str}
    Performs a real atomic multi-file commit on the student's feature branch.
    Returns the new commit SHA.
    """
    if not _commit_rate_ok(request.user.id):
        return Response(
            {"error": "Commit rate limit exceeded. Try again later."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    sub, _capstone, err = _resolve_submission(request.user, capstone_id)
    if err:
        return err

    changed_files = request.data.get("changed_files", [])
    message = request.data.get("message", "")
    if not isinstance(changed_files, list) or not changed_files:
        return Response({"error": "changed_files must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)

    from .capstone_git import commit as git_commit, GitError
    author = sub.github_username or request.user.username
    coauthor = f"Co-authored-by: {author} <{author}@users.noreply.github.com>"
    try:
        new_sha = git_commit(
            repo_url=sub.repo_url,
            branch=sub.branch,
            changed_files=changed_files,
            message=message,
            author_name=author,
            coauthor_trailer=coauthor,
        )
    except GitError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("commit_files failed")
        return Response({"error": "Commit failed."}, status=status.HTTP_502_BAD_GATEWAY)

    sub.latest_commit_sha = new_sha
    sub.save(update_fields=["latest_commit_sha"])
    return Response({"commit_sha": new_sha, "branch": sub.branch})


# ---------------------------------------------------------------------------
# Part C — CI verdict (Check Runs API)
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def commit_status(request, sha):
    """
    GET /capstone/commit-status/<sha>/?capstone=<id>
    Reads the Check Runs API for the SHA; returns status + readable reason.
    """
    capstone_id = request.query_params.get("capstone")
    sub = CapstoneSubmission.objects.filter(
        latest_commit_sha=sha, enrollment__student=request.user
    ).first()
    if not sub and capstone_id:
        sub = CapstoneSubmission.objects.filter(
            capstone_id=capstone_id, enrollment__student=request.user
        ).first()
    if not sub or not sub.repo_url:
        return Response({"error": "Submission/repo not found for this SHA."}, status=status.HTTP_404_NOT_FOUND)

    from .capstone_git import get_check_runs, GitError
    try:
        verdict = get_check_runs(sub.repo_url, sha)
        return Response(verdict)
    except GitError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        logger.exception("commit_status failed")
        return Response({"error": "Could not read CI status."}, status=status.HTTP_502_BAD_GATEWAY)


# ---------------------------------------------------------------------------
# Part D — Run uncommitted files in the sandbox (optional local feedback)
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def run_files(request, capstone_id):
    """
    POST /capstone/<id>/run/
    Body: {files: [{path, content}], entry?: str}
    Runs the current (uncommitted) files in the AI-service sandbox and returns
    stdout/stderr. This is LOCAL feedback only — official verdict comes from CI.
    """
    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    files = request.data.get("files", [])
    entry = request.data.get("entry") or capstone.run_command or ""
    if not isinstance(files, list) or not files:
        return Response({"error": "files must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        resp = requests.post(
            f"{AI_SERVICE_URL}/capstone/run",
            json={"files": files, "entry": entry},
            headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        return Response(resp.json())
    except requests.HTTPError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        logger.exception("run_files failed")
        return Response({"error": "Sandbox run unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Part E — Scoped AI assist with quota
# ---------------------------------------------------------------------------

def _get_or_reset_quota(capstone, student) -> CapstoneAssistQuota:
    """Fetch the student's assist quota, resetting `used` if the period elapsed."""
    from datetime import timedelta
    quota, _ = CapstoneAssistQuota.objects.get_or_create(
        capstone=capstone, student=student,
        defaults={"limit": 10, "period": "daily"},
    )
    window = timedelta(days=1) if quota.period == "daily" else timedelta(weeks=1)
    if dj_timezone.now() - quota.period_start >= window:
        quota.used = 0
        quota.period_start = dj_timezone.now()
        quota.save(update_fields=["used", "period_start"])
    return quota


def _apply_assist_mastery_penalty(student_id, concept_id):
    """Heavy assist reliance lowers demonstrated mastery for the concept.

    A gentle (alpha=0.1) nudge toward an "assisted" outcome of 0.3, recorded
    through the SINGLE writer. ``evidence_delta=0`` because assist is NOT new
    independent demonstration — but the event still moves the score, so the
    concept never reads as "no data" (it has an entry; see derive_mastery_level).
    """
    if not concept_id:
        return
    from apps.progress.mastery_service import record_events
    try:
        record_events(student_id, [{
            "concept_id": str(concept_id),
            "outcome": 0.3,
            "source": "capstone_assist",
            "alpha": 0.1,
            "evidence_delta": 0,
        }])
    except Exception:
        logger.exception("assist mastery penalty failed for student %s", student_id)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def assist_quota(request, capstone_id):
    """GET /capstone/<id>/assist-quota/ — remaining assist credits."""
    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)
    quota = _get_or_reset_quota(capstone, request.user)
    return Response(CapstoneAssistQuotaSerializer(quota).data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def assist(request, capstone_id):
    """
    POST /capstone/<id>/assist/
    Body: {question: str, code_snippet?: str, concept_id?: int}

    Rubric-aware Socratic helper. Decrements quota, blocks at zero, caps returned
    code, logs the call, and applies a small mastery penalty for the concept.
    """
    try:
        capstone = Capstone.objects.prefetch_related("rubric_items").get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    quota = _get_or_reset_quota(capstone, request.user)
    if quota.remaining <= 0:
        return Response(
            {"error": "AI assist quota exhausted for this period.", "remaining": 0},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    question = request.data.get("question", "").strip()
    code_snippet = request.data.get("code_snippet", "")
    concept_id = request.data.get("concept_id")
    if not question:
        return Response({"error": "question required."}, status=status.HTTP_400_BAD_REQUEST)

    rubric_texts = [item.text for item in capstone.rubric_items.all()]
    try:
        resp = requests.post(
            f"{AI_SERVICE_URL}/capstone/assist",
            json={
                "capstone_title": capstone.title,
                "brief": capstone.brief_text,
                "rubric_items": rubric_texts,
                "question": question,
                "code_snippet": code_snippet[:4000],
            },
            headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
            timeout=90,
        )
        resp.raise_for_status()
        ai_data = resp.json()
    except Exception:
        logger.exception("assist AI call failed")
        return Response({"error": "AI assist unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    answer = ai_data.get("answer", "")

    # Consume quota + log + mastery penalty (only on a successful answer)
    quota.used += 1
    quota.save(update_fields=["used"])

    CapstoneAssistLog.objects.create(
        capstone=capstone,
        student=request.user,
        concept_id=concept_id if concept_id else None,
        question=question[:2000],
        response_excerpt=answer[:2000],
    )

    threading.Thread(
        target=_apply_assist_mastery_penalty,
        args=(request.user.id, concept_id),
        daemon=True,
    ).start()

    return Response({"answer": answer, "remaining": quota.remaining})


# ---------------------------------------------------------------------------
# Part F — Teams + matchmaking
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def queue_join(request, capstone_id):
    """POST /capstone/<id>/queue/join/ — enter the matchmaking queue."""
    from datetime import timedelta
    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)
    if capstone.team_mode != "team":
        return Response({"error": "This capstone is solo — no matchmaking."}, status=status.HTTP_400_BAD_REQUEST)

    from apps.courses.models import Enrollment
    if not Enrollment.objects.filter(student=request.user, course=capstone.course).exists():
        return Response({"error": "Not enrolled."}, status=status.HTTP_403_FORBIDDEN)

    from .matchmaking import DEFAULT_FILL_WINDOW
    entry, _ = MatchmakingQueueEntry.objects.get_or_create(
        capstone=capstone, student=request.user,
        defaults={"fill_window_expires_at": dj_timezone.now() + DEFAULT_FILL_WINDOW},
    )

    # Try to form full teams immediately if enough are waiting.
    from .matchmaking import process_queue
    try:
        process_queue(capstone, force=False)
    except Exception:
        logger.exception("process_queue after join failed")

    entry.refresh_from_db()
    return Response(MatchmakingQueueEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def queue_leave(request, capstone_id):
    """POST /capstone/<id>/queue/leave/ — leave the matchmaking queue."""
    MatchmakingQueueEntry.objects.filter(
        capstone_id=capstone_id, student=request.user, status="waiting"
    ).delete()
    return Response({"status": "left"})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def teammate_recommendations(request, capstone_id):
    """
    GET /capstone/<id>/recommendations/ — suggested teammates with a one-line why.
    Students confirm; nobody is force-assigned.
    """
    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    from apps.courses.models import Enrollment
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Candidates = other enrolled students currently waiting in the queue.
    waiting_ids = MatchmakingQueueEntry.objects.filter(
        capstone=capstone, status="waiting"
    ).exclude(student=request.user).values_list("student_id", flat=True)
    candidates = list(User.objects.filter(id__in=list(waiting_ids)))

    from .matchmaking import recommend_teammates
    recs = recommend_teammates(request.user, capstone, candidates)
    return Response({"recommendations": recs})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def my_team(request, capstone_id):
    """GET /capstone/<id>/my-team/ — the team the student belongs to, if any."""
    team = Team.objects.filter(
        capstone_id=capstone_id, members=request.user
    ).first()
    if not team:
        return Response({"team": None})
    return Response(TeamSerializer(team).data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def process_matchmaking(request, capstone_id):
    """
    POST /capstone/<id>/process-queue/ — admin forces team formation now
    (forms best available teams, even solo, so the queue never deadlocks).
    """
    if not _is_admin(request.user):
        return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    from .matchmaking import process_queue
    teams = process_queue(capstone, force=True)
    return Response({"teams_formed": len(teams), "teams": TeamSerializer(teams, many=True).data})


# ---------------------------------------------------------------------------
# Team role advisor — advisory suggested division of labor (never feeds scoring)
# ---------------------------------------------------------------------------

def _team_for_member(team_id, user):
    """Return (team, error_response). Access limited to team members + admins."""
    team = Team.objects.filter(pk=team_id).first()
    if not team:
        return None, Response({"error": "Team not found."}, status=status.HTTP_404_NOT_FOUND)
    if not (_is_admin(user) or team.members.filter(pk=user.id).exists()):
        return None, Response({"error": "Not a member of this team."}, status=status.HTTP_403_FORBIDDEN)
    return team, None


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def team_role_advice(request, team_id):
    """GET /capstone/team/<id>/role-advice/ — cached advisory division of labor."""
    team, err = _team_for_member(team_id, request.user)
    if err:
        return err
    return Response({
        "role_advice": team.role_advice or None,
        "generated_at": team.role_advice_generated_at,
        "member_count": team.members.count(),
    })


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def team_role_advice_refresh(request, team_id):
    """POST /capstone/team/<id>/role-advice/refresh/ — regenerate (synchronous)."""
    team, err = _team_for_member(team_id, request.user)
    if err:
        return err
    if team.members.count() < 2:
        return Response(
            {"role_advice": None, "detail": "Solo project — no division of labor."},
            status=status.HTTP_200_OK,
        )
    from .team_roles import generate_for_team
    generate_for_team(team.id)
    team.refresh_from_db()
    return Response({
        "role_advice": team.role_advice or None,
        "generated_at": team.role_advice_generated_at,
        "member_count": team.members.count(),
    })
