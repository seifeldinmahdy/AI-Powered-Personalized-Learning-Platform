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


def _last_github_username(user) -> str:
    """The student's most recently used GitHub handle across their submissions.

    Lets repo provisioning reuse it so the student types their handle once, ever.
    """
    prior = (
        CapstoneSubmission.objects
        .filter(enrollment__student=user)
        .exclude(github_username="")
        .order_by("-submitted_at")
        .first()
    )
    return prior.github_username if prior else ""


def _get_effective_rubric(capstone: Capstone, team_size: int) -> list[CapstoneRubricItem]:
    """Return rubric items applicable to this team size."""
    return list(capstone.rubric_items.filter(min_team_size__lte=team_size))


def _compute_score(rubric_items: list[CapstoneRubricItem], results: dict) -> float:
    """
    Deterministic weighted score with PARTIAL CREDIT per atomic check (mirrors the
    problem-set scoring). For each criterion, fraction = checks_passed/checks_total
    (legacy no-check items: fraction = 1 if passed else 0).
    score = sum(weight * fraction) / sum(weight) * 100
    """
    total_weight = sum(item.weight for item in rubric_items)
    if total_weight == 0:
        return 0.0
    earned = 0.0
    for item in rubric_items:
        r = results.get(str(item.id), {})
        total = r.get("checks_total") or 0
        if total > 0:
            fraction = (r.get("checks_passed") or 0) / total
        else:
            fraction = 1.0 if r.get("passed", False) else 0.0
        earned += item.weight * fraction
    return round(earned / total_weight * 100, 2)


def _compute_verdict(rubric_items: list, results: dict, pass_policy: str = "all_core") -> str:
    """
    PASS/FAIL computed in Python — the LLM never decides this.

    Policy 'all_core': PASS iff every applicable CORE criterion passes, where a
    criterion passes iff ALL of its atomic checks pass (the stored ``passed`` flag
    is already that conjunction). Stretch criteria affect score but never the verdict.
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
    """Turn the AI's per-check results into the stored shape, keyed by every
    applicable rubric item id (missing → failed). A criterion passes iff all of
    its atomic checks pass; checks_passed/checks_total drive partial-credit scoring.
    Legacy criteria (no checks) collapse to a single coarse yes/no."""
    ai_results = ai_result.get("results", {})
    results = {}
    for item in rubric_items:
        key = str(item.id)
        raw = ai_results.get(key) or ai_results.get(int(item.id)) or {}
        raw_checks = raw.get("checks", {}) if isinstance(raw, dict) else {}
        item_checks = item.checks or []

        check_results = {}
        if item_checks:
            for i, chk in enumerate(item_checks):
                cid = str(chk.get("id") or i)
                cval = (raw_checks.get(cid) or raw_checks.get(str(i)) or {}) if isinstance(raw_checks, dict) else {}
                check_results[cid] = {
                    "text": chk.get("text", ""),
                    "passed": bool(cval.get("passed", False)),
                    "evidence": cval.get("evidence", ""),
                }
            total = len(check_results)
            passed_count = sum(1 for c in check_results.values() if c["passed"])
            item_passed = total > 0 and passed_count == total
            evidence = "; ".join(c["evidence"] for c in check_results.values() if c["evidence"])[:500]
        else:
            # Legacy item: AI may return an "_all" check or a coarse item-level flag.
            cval = raw_checks.get("_all") if isinstance(raw_checks, dict) else None
            if cval is None:
                item_passed = bool(raw.get("passed", False))
                evidence = raw.get("evidence", "")
            else:
                item_passed = bool(cval.get("passed", False))
                evidence = cval.get("evidence", "")
            total, passed_count = 1, (1 if item_passed else 0)

        results[key] = {
            "passed": item_passed,
            "weight": item.weight,
            "evidence": evidence,
            "checks": check_results,
            "checks_passed": passed_count,
            "checks_total": total,
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
        # Reward recipients: for a TEAM submission, every member earns XP + mastery
        # + course completion (a shared PASS completes the course for the whole
        # team); for solo, just the one student.
        from apps.courses.models import Enrollment
        if team:
            recipients = list(team.members.all())
        else:
            recipients = [sub.enrollment.student]

        for member in recipients:
            _apply_xp_delta(member.id, sub.xp_awarded)
            _update_concept_mastery_sync(member.id, results, rubric_items)
            # Capstone PASS is the terminal gate → mark the course complete.
            try:
                from apps.courses.completion import mark_complete_if_eligible
                enr = Enrollment.objects.filter(
                    course=sub.capstone.course, student=member
                ).first()
                if enr:
                    mark_complete_if_eligible(enr)
            except Exception:
                logger.exception("Could not mark course completion for member %s", member.id)


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
            {
                "id": item.id,
                "text": item.text,
                "checks": [
                    {"id": str(c.get("id") or i), "text": c.get("text", "")}
                    for i, c in enumerate(item.checks or [])
                ],
                "weight": item.weight,
                "category": item.category,
            }
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

    @action(detail=True, methods=["post"], url_path="suggest-language")
    def suggest_language(self, request, pk=None):
        """POST /capstone/<id>/suggest-language/ — AI suggests the course's language.

        Suggestion only: returns {language, confidence, rationale}. The admin
        reviews/overrides, then PATCHes the capstone to persist `language`.
        """
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        capstone = self.get_object()
        from apps.courses.models import Concept
        concepts = list(
            Concept.objects.filter(course=capstone.course).values_list("label", flat=True)[:40]
        )
        payload = {
            "course_title": capstone.course.title,
            "course_description": capstone.course.description or "",
            "concepts": concepts,
        }
        try:
            resp = requests.post(
                f"{AI_SERVICE_URL}/capstone/suggest-language",
                json=payload,
                headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
                timeout=60,
            )
            resp.raise_for_status()
            return Response(resp.json())
        except Exception:
            logger.exception("suggest_language AI call failed")
            return Response({"error": "AI service unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @action(detail=True, methods=["post"], url_path="draft-ci")
    def draft_ci(self, request, pk=None):
        """POST /capstone/<id>/draft-ci/ — generate a standardized CI workflow.

        Deterministic (not LLM): a malformed ci.yml would block grading for every
        student, so the YAML is assembled from vetted per-language templates. The
        admin can preview with a chosen language/run_command in the body, then
        PATCH `ci_workflow` (+ language/run_command) onto the capstone to save it.
        """
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        capstone = self.get_object()
        from .ci_templates import generate_ci_workflow

        language = (request.data.get("language") or capstone.language or "python")
        run_command = request.data.get("run_command")
        if run_command is None:
            run_command = capstone.run_command or ""
        workflow = generate_ci_workflow(language, run_command)
        return Response({"language": language, "run_command": run_command, "ci_workflow": workflow})


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
        """Solo → a per-student proposal. Team → ONE shared proposal attached to the
        author's team (so a team proposes a single agreed idea, not N competing ones)."""
        user = self.request.user
        capstone = serializer.validated_data.get("capstone")
        team = None
        if capstone and capstone.team_mode == "team":
            team = Team.objects.filter(capstone=capstone, members=user).first()
            if not team:
                from rest_framework.exceptions import ValidationError
                raise ValidationError("Join or form a team before proposing a project idea.")
            if CapstoneProposal.objects.filter(capstone=capstone, team=team).exists():
                from rest_framework.exceptions import ValidationError
                raise ValidationError("Your team already has a proposal.")
        proposal = serializer.save(student=user, team=team)
        # The author agrees by submitting; remaining team members must agree too
        # before the proposal is the team's official one.
        proposal.agreed_members.add(user)

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

    def _team_proposal_or_error(self, pk, user):
        """Look up a team proposal that `user` may act on (a member of its team).
        Bypasses the per-author queryset so any teammate can agree/reject."""
        proposal = CapstoneProposal.objects.filter(pk=pk).first()
        if not proposal:
            return None, Response({"error": "Proposal not found."}, status=status.HTTP_404_NOT_FOUND)
        if not (proposal.team_id and proposal.team.members.filter(pk=user.id).exists()):
            return None, Response({"error": "Not a member of this proposal's team."},
                                  status=status.HTTP_403_FORBIDDEN)
        return proposal, None

    @action(detail=True, methods=["post"], url_path="agree")
    def agree(self, request, pk=None):
        """POST /capstone/proposals/<id>/agree/ — a team member agrees to the shared idea."""
        proposal, err = self._team_proposal_or_error(pk, request.user)
        if err:
            return err
        proposal.agreed_members.add(request.user)
        return Response(CapstoneProposalSerializer(proposal).data)

    @action(detail=True, methods=["post"], url_path="reject-idea")
    def reject_idea(self, request, pk=None):
        """POST /capstone/proposals/<id>/reject-idea/ — a team member rejects the shared
        idea, removing it so the team can draft a new one together."""
        proposal, err = self._team_proposal_or_error(pk, request.user)
        if err:
            return err
        proposal.delete()
        return Response({"status": "rejected"})


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
    data = CapstoneSerializer(cap).data
    if not _is_admin(user):
        # Pre-fill the provisioning input so the student doesn't retype their
        # GitHub handle (empty on their very first capstone).
        data["suggested_github_username"] = _last_github_username(user)
    return Response(data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def my_submission(request, capstone_id):
    """GET /capstone/<capstone_id>/my-submission/ — student's own submission.

    Opportunistically recovers stuck grades so a student polling their result can
    self-heal a grade whose worker died (in addition to the cron sweep). Safe and
    idempotent — recovery re-checks each row under a lock.
    """
    try:
        from .grading import recover_stuck_grades
        recover_stuck_grades()
    except Exception:
        logger.exception("opportunistic stuck-grade recovery failed")

    sub = CapstoneSubmission.objects.filter(
        capstone_id=capstone_id, enrollment__student=request.user
    ).first()
    if not sub:
        return Response({"error": "No submission found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(CapstoneSubmissionSerializer(sub).data)


# NOTE: the old paste-a-code-bundle path (submit_archive / POST .../submit/) was
# removed. It bypassed the repo + CI-green integrity model (a student could paste
# arbitrary code), so the single submission surface is now the provisioned repo
# graded at its CI-passed work-branch HEAD (submit_for_grading / submit_from_repo).
# The shared deterministic evaluator (_evaluate_and_grade) is still used by the
# repo grading worker.


# ---------------------------------------------------------------------------
# GitHub integration views
# ---------------------------------------------------------------------------

def _invite_collaborator(org: str, repo_name: str, username: str, hdrs: dict) -> None:
    """Best-effort: invite a GitHub user to the repo with push access."""
    if not username:
        return
    try:
        requests.put(
            f"https://api.github.com/repos/{org}/{repo_name}/collaborators/{username}",
            json={"permission": "push"}, headers=hdrs, timeout=15,
        )
    except Exception:
        logger.exception("collaborator invite failed for %s", username)


def _create_capstone_repo(capstone, repo_name: str, org: str, hdrs: dict,
                          invite_usernames, seed_author: str) -> str:
    """Create a PRIVATE repo (template or blank), protect main (required 'ci'
    check), invite every collaborator, create the 'work' branch, and seed the
    standardized CI workflow. Returns repo_url; raises RuntimeError on create."""
    if capstone.github_template_repo:
        owner, template = capstone.github_template_repo.split("/", 1)
        create_resp = requests.post(
            f"https://api.github.com/repos/{owner}/{template}/generate",
            json={"owner": org, "name": repo_name, "private": True}, headers=hdrs, timeout=30,
        )
    else:
        create_resp = requests.post(
            f"https://api.github.com/orgs/{org}/repos",
            json={"name": repo_name, "private": True, "auto_init": True}, headers=hdrs, timeout=30,
        )
    if create_resp.status_code not in (200, 201):
        raise RuntimeError(create_resp.text)
    repo_url = create_resp.json().get("html_url", f"https://github.com/{org}/{repo_name}")

    requests.put(
        f"https://api.github.com/repos/{org}/{repo_name}/branches/main/protection",
        json={
            "required_status_checks": {"strict": True, "contexts": ["ci"]},
            "enforce_admins": False,
            "required_pull_request_reviews": None,
            "restrictions": None,
        },
        headers=hdrs, timeout=15,
    )

    for username in {u for u in invite_usernames if u}:
        _invite_collaborator(org, repo_name, username, hdrs)

    branch = "work"
    try:
        from .capstone_git import ensure_branch
        ensure_branch(repo_url, branch)
    except Exception:
        logger.exception("Could not pre-create work branch for %s", repo_name)

    # Seed the standardized CI workflow onto the work branch (canonical wins; else
    # a language default when no template repo provides one). Best-effort.
    workflow = (capstone.ci_workflow or "").strip()
    if not workflow and not capstone.github_template_repo:
        from .ci_templates import generate_ci_workflow
        workflow = generate_ci_workflow(capstone.language, capstone.run_command)
    if workflow:
        try:
            from .capstone_git import commit as git_commit
            git_commit(
                repo_url=repo_url, branch=branch,
                changed_files=[{"path": ".github/workflows/ci.yml", "content": workflow}],
                message="ci: standardized course workflow", author_name=seed_author,
            )
        except Exception:
            logger.exception("Could not seed CI workflow for %s", repo_name)
    return repo_url


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def provision_repo(request, capstone_id):
    """
    POST /capstone/<capstone_id>/provision-repo/
    Body: {github_username: str}

    Solo: one PRIVATE repo per student. Team: ONE shared PRIVATE repo per TEAM —
    every member is invited as a collaborator, so the team collaborates on a single
    codebase (instead of each member getting a separate repo). Private repos protect
    academic integrity; the installation token never reaches the client.
    """
    if not settings.GITHUB_ORG:
        return Response({"error": "GitHub integration not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    github_username = request.data.get("github_username", "").strip()
    if not github_username:
        github_username = _last_github_username(request.user)
    if not github_username:
        return Response(
            {"error": "github_username required.", "reason": "first_time"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        capstone = Capstone.objects.get(pk=capstone_id)
    except Capstone.DoesNotExist:
        return Response({"error": "Capstone not found."}, status=status.HTTP_404_NOT_FOUND)

    from apps.courses.models import Enrollment
    enrollment = Enrollment.objects.filter(student=request.user, course=capstone.course).first()
    if not enrollment:
        return Response({"error": "Not enrolled."}, status=status.HTTP_403_FORBIDDEN)

    from .github_app import github_headers
    org = settings.GITHUB_ORG

    # ── Team mode: one shared repo per team ──────────────────────────────
    if capstone.team_mode == "team":
        team = Team.objects.filter(capstone=capstone, members=request.user).first()
        if not team:
            return Response(
                {"error": "Form or join a team before provisioning a repo.", "reason": "no_team"},
                status=status.HTTP_409_CONFLICT,
            )
        if team.status == "forming":
            return Response(
                {"error": "Confirm your team (all members must accept) before provisioning the repo.",
                 "reason": "team_unconfirmed"},
                status=status.HTTP_409_CONFLICT,
            )
        # Idempotent: team already has a repo → just ensure THIS member is invited
        # and that they have a submission row pointing at it.
        if team.repo_url:
            repo_name = team.repo_url.rstrip("/").split("/")[-1]
            try:
                _invite_collaborator(org, repo_name, github_username, github_headers())
            except Exception:
                logger.exception("re-invite to team repo failed")
            CapstoneSubmission.objects.update_or_create(
                capstone=capstone, enrollment=enrollment,
                defaults={"repo_url": team.repo_url, "branch": team.branch,
                          "team": team, "github_username": github_username, "status": "pending"},
            )
            return Response({"repo_url": team.repo_url, "repo_name": repo_name,
                             "branch": team.branch, "already_provisioned": True})

        repo_name = f"capstone-{capstone_id}-team-{team.id}"
        invites = [github_username] + [_last_github_username(m) for m in team.members.all()]
        try:
            hdrs = github_headers()
            repo_url = _create_capstone_repo(capstone, repo_name, org, hdrs, invites, github_username)
        except Exception:
            logger.exception("team provision_repo failed for capstone %s", capstone_id)
            return Response({"error": "GitHub provisioning failed."}, status=status.HTTP_502_BAD_GATEWAY)

        team.repo_url = repo_url
        team.branch = "work"
        team.save(update_fields=["repo_url", "branch"])
        CapstoneSubmission.objects.update_or_create(
            capstone=capstone, enrollment=enrollment,
            defaults={"repo_url": repo_url, "branch": "work", "team": team,
                      "github_username": github_username, "status": "pending"},
        )
        return Response({"repo_url": repo_url, "repo_name": repo_name, "branch": "work"})

    # ── Solo mode: one repo per student ──────────────────────────────────
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

    repo_name = f"capstone-{capstone_id}-{request.user.username}"
    try:
        hdrs = github_headers()
        repo_url = _create_capstone_repo(capstone, repo_name, org, hdrs, [github_username], github_username)
    except Exception:
        logger.exception("provision_repo failed for capstone %s", capstone_id)
        return Response({"error": "GitHub provisioning failed."}, status=status.HTTP_502_BAD_GATEWAY)

    CapstoneSubmission.objects.update_or_create(
        capstone=capstone, enrollment=enrollment,
        defaults={"repo_url": repo_url, "branch": "work",
                  "github_username": github_username, "status": "pending"},
    )
    return Response({"repo_url": repo_url, "repo_name": repo_name, "branch": "work"})


@api_view(["POST"])
@permission_classes([])  # Auth is the HMAC signature check below, not a user.
def github_webhook(request):
    """
    POST /capstone/github-webhook/
    Verifies the HMAC-SHA256 signature, then acknowledges push/check_suite events.

    CI status is FEEDBACK ONLY. It is deliberately NOT written to the submission's
    grading status/verdict: the rubric verdict (computed by _evaluate_and_grade)
    is the sole completion signal, and grading state is owned by the grading state
    machine. The workspace reads live CI via the commit-status endpoint, so the
    webhook does not need to mutate any submission row.
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
        # Log only — never touch submission status/verdict (feedback, not completion).
        conclusion = payload.get("check_suite", {}).get("conclusion")
        repo_url = payload.get("repository", {}).get("html_url", "")
        head_sha = payload.get("check_suite", {}).get("head_sha", "")
        logger.info(
            "github_webhook check_suite: repo=%s sha=%s conclusion=%s (feedback only)",
            repo_url, head_sha, conclusion,
        )

    return Response({"received": event})


def _start_repo_grading(sub) -> Response:
    """The single repo-grading entry. Derives everything server-side from the
    student's PROVISIONED submission:

      1. Resolve the work-branch HEAD (the exact SHA, server-side).
      2. Require CI GREEN on that commit (continuous-feedback gate).
      3. Grade THAT SHA through the shared deterministic pipeline. `main` is
         never mutated (no admin permission needed) — read_repo_bundle reads the
         exact CI-passed work commit. Idempotent: re-grading re-scores without
         multiplying XP/mastery. Code is read transiently and never stored.

    The grading worker is launched via the grading state machine, which claims
    the submission atomically so concurrent submits cannot double-launch.
    """
    from .capstone_git import head_sha, get_check_runs, GitError
    from .grading import start_grading

    # 1. Work-branch HEAD (server-resolved — client cannot choose the SHA).
    try:
        work_sha = head_sha(sub.repo_url, sub.branch)
    except GitError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    # 2. CI must be green on that commit.
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

    # 3. Grade the exact work SHA in the background (main is never moved).
    launched = start_grading(sub, work_sha)
    sub.refresh_from_db()

    return Response(
        {
            "status": "evaluating",
            "commit_sha": work_sha,
            "already_grading": not launched,
            "submission": CapstoneSubmissionSerializer(sub).data,
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_from_repo(request, capstone_id):
    """
    POST /capstone/<capstone_id>/submit-from-repo/

    Grades the student's PROVISIONED repo. Any repo_url / commit_sha /
    github_username in the request body are IGNORED for academic integrity — the
    platform never grades an arbitrary external repo. Everything is derived
    server-side from the provisioned submission (work-branch HEAD, CI-gated),
    so this is the same single grading path as submit_for_grading.
    """
    sub, _capstone, err = _resolve_submission(request.user, capstone_id)
    if err:
        return err
    return _start_repo_grading(sub)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_for_grading(request, capstone_id):
    """
    POST /capstone/<capstone_id>/submit-for-grading/

    Final submission from the in-platform IDE. Resolves the provisioned
    work-branch HEAD, requires CI green, and grades that exact commit through the
    shared deterministic pipeline. Returns 409 (with the CI verdict) if CI hasn't
    passed yet. `main` is never mutated.
    """
    sub, _capstone, err = _resolve_submission(request.user, capstone_id)
    if err:
        return err
    return _start_repo_grading(sub)


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

    sub = None
    # Team mode: any member resolves the team's single shared submission/repo.
    if capstone.team_mode == "team":
        team = Team.objects.filter(capstone=capstone, members=user).first()
        if team:
            sub = (CapstoneSubmission.objects
                   .filter(capstone=capstone, team=team).exclude(repo_url="").first())
            # Fall back to the team's own repo_url if a submission row isn't keyed
            # to the team yet (e.g. provisioned by another member).
            if not sub and team.repo_url:
                sub = (CapstoneSubmission.objects
                       .filter(capstone=capstone, enrollment__student=user).first())
    if sub is None:
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
    # `entry` is a STUDENT hint (a file to run); the admin-trusted shell command
    # and the course language come from the capstone, so any language is runnable.
    entry = request.data.get("entry") or ""
    if not isinstance(files, list) or not files:
        return Response({"error": "files must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        resp = requests.post(
            f"{AI_SERVICE_URL}/capstone/run",
            json={
                "files": files,
                "entry": entry,
                "run_command": capstone.run_command or "",
                "language": capstone.language or "",
            },
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


def _requeue_student(capstone, user):
    """Put a student back into the waiting queue with a fresh fill window,
    preserving their declined-pairs list."""
    from .matchmaking import DEFAULT_FILL_WINDOW
    MatchmakingQueueEntry.objects.update_or_create(
        capstone=capstone, student=user,
        defaults={"status": "waiting", "team": None,
                  "fill_window_expires_at": dj_timezone.now() + DEFAULT_FILL_WINDOW},
    )


def _record_mutual_declines(capstone, decliner_id, other_ids):
    """Remember that `decliner` and each `other` declined each other, so the
    matchmaker won't re-propose that pairing."""
    entries = {e.student_id: e for e in MatchmakingQueueEntry.objects.filter(
        capstone=capstone, student_id__in=[decliner_id, *other_ids])}
    de = entries.get(decliner_id)
    if de is not None:
        de.declined_user_ids = sorted(set(de.declined_user_ids or []) | set(other_ids))
        de.save(update_fields=["declined_user_ids"])
    for oid in other_ids:
        oe = entries.get(oid)
        if oe is not None:
            oe.declined_user_ids = sorted(set(oe.declined_user_ids or []) | {decliner_id})
            oe.save(update_fields=["declined_user_ids"])


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def accept_match(request, team_id):
    """POST /capstone/team/<id>/accept/ — confirm a proposed team. Once every
    member accepts, the team becomes active."""
    team, err = _team_for_member(team_id, request.user)
    if err:
        return err
    if team.status != "forming":
        return Response(TeamSerializer(team).data)  # already resolved
    team.confirmed_members.add(request.user)
    member_ids = set(team.members.values_list("id", flat=True))
    confirmed_ids = set(team.confirmed_members.values_list("id", flat=True))
    if member_ids and member_ids <= confirmed_ids:
        team.status = "active"
        team.save(update_fields=["status"])
    return Response(TeamSerializer(team).data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def decline_match(request, team_id):
    """POST /capstone/team/<id>/decline/ — decline a proposed team. The decliner
    is removed and re-queued (and won't be re-paired with these teammates). If
    fewer than two members remain, the team disbands and the rest are re-queued."""
    team, err = _team_for_member(team_id, request.user)
    if err:
        return err
    if team.status != "forming":
        return Response({"error": "This team is already confirmed; leave it instead."},
                        status=status.HTTP_409_CONFLICT)

    user = request.user
    capstone = team.capstone
    other_ids = list(team.members.exclude(pk=user.id).values_list("id", flat=True))
    _record_mutual_declines(capstone, user.id, other_ids)

    team.members.remove(user)
    team.confirmed_members.remove(user)
    _requeue_student(capstone, user)

    remaining = list(team.members.all())
    if len(remaining) < 2:
        for m in remaining:
            _requeue_student(capstone, m)
        team.members.clear()
        team.confirmed_members.clear()
        team.status = "disbanded"
        team.save(update_fields=["status"])

    # Best-effort: try to re-form teams from the refreshed queue.
    try:
        from .matchmaking import process_queue
        process_queue(capstone, force=False)
    except Exception:
        logger.exception("re-process after decline failed")

    return Response({"status": "declined"})


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
