import logging

from django.conf import settings

from django.apps import apps
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from .throttles import FeedbackThrottle, AnonFeedbackThrottle

from .models import (
    SessionCompletion, SystemActivityLog, AIChatLog,
    StudentLearningProfile, Bookmark, ConceptMasteryEvent,
    IntentFeedbackBuffer, IntentRetrainingCounter,
)

logger = logging.getLogger(__name__)

# Below this topic→concept match confidence, a checkpoint update is DROPPED
# rather than written — the same conservative stance as a no-match. The mapping
# is on the live mastery write path with no human review, so each one is logged.
MASTERY_TOPIC_MATCH_FLOOR = 0.55
from .serializers import (
    SessionCompletionSerializer,
    SystemActivityLogSerializer,
    AIChatLogSerializer,
    AIChatLogFeedbackSerializer,
    IntentFeedbackBufferSerializer,
    IntentRetrainingCounterSerializer,
    BookmarkSerializer,
    StudentLearningProfileSerializer,
)


class SessionCompletionViewSet(viewsets.ModelViewSet):
    """CRUD for session completions. Scoped to the authenticated user's enrollments."""
    serializer_class = SessionCompletionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = SessionCompletion.objects.filter(enrollment__student=self.request.user)
        enrollment_id = self.request.query_params.get("enrollment_id")
        if enrollment_id:
            qs = qs.filter(enrollment_id=enrollment_id)
        session_number = self.request.query_params.get("session_number")
        if session_number:
            qs = qs.filter(session_number=session_number)
        return qs

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Mark a session completion as Completed (idempotent)."""
        from .completion_service import complete_session

        completion = self.get_object()
        result = complete_session(
            request.user,
            completion.enrollment.course,
            completion.session_number,
            time_spent_minutes=request.data.get("time_spent_minutes"),
            score=request.data.get("score"),
        )
        if result is None:
            return Response(
                {"detail": "No enrollment for this course."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = SessionCompletionSerializer(result["completion"]).data
        data["newly_earned_achievements"] = result["newly_earned_achievements"]
        return Response(data)


class SystemActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only activity logs for the authenticated user."""
    serializer_class = SystemActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SystemActivityLog.objects.filter(user=self.request.user)


class AIChatLogViewSet(viewsets.ModelViewSet):
    """AI chat logs for the authenticated user. Filter by ?lesson_id=<id>. Supports GET + POST."""
    serializer_class = AIChatLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options", "patch"]

    def get_queryset(self):
        qs = AIChatLog.objects.filter(user=self.request.user).order_by("created_at")
        session_number = self.request.query_params.get("session_number")
        if session_number:
            qs = qs.filter(session_number=session_number)
        return qs

    def perform_create(self, serializer):
        """Save chat log, ensuring the user is enrolled in the course."""
        course = serializer.validated_data.get("course")
        if course and not self._user_has_access(course):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You are not enrolled in this course.")
        serializer.save(user=self.request.user)

    def _user_has_access(self, course):
        """Check whether the authenticated user is enrolled in the course."""
        Enrollment = apps.get_model("courses", "Enrollment")
        return Enrollment.objects.filter(
            student=self.request.user,
            course=course,
        ).exists()

    @action(
        detail=True,
        methods=["patch"],
        url_path="feedback",
        throttle_classes=[FeedbackThrottle, AnonFeedbackThrottle],
    )
    def submit_feedback(self, request, pk=None):
        """
        Submit 👍/👎 feedback for a tutor response.

        Body:
          {"feedback": "thumbs_up" | "thumbs_down"}
          For thumbs_down optionally include:
          {"corrected_intent": "On-Topic Question" | ...}

        Adds the chat log to the IntentFeedbackBuffer and increments the
        retraining counter. If the counter threshold is reached, the response
        includes "retraining_recommended": true.
        """
        from .models import INTENT_CHOICES

        chat_log = self.get_object()
        serializer = AIChatLogFeedbackSerializer(chat_log, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        feedback_value = serializer.validated_data.get("feedback")
        if feedback_value not in ("thumbs_up", "thumbs_down"):
            return Response(
                {"detail": "feedback must be 'thumbs_up' or 'thumbs_down'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        corrected_intent = request.data.get("corrected_intent")
        valid_intents = {name for name, _ in INTENT_CHOICES}
        if corrected_intent and corrected_intent not in valid_intents:
            return Response(
                {"detail": f"corrected_intent must be one of {sorted(valid_intents)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if corrected_intent and corrected_intent == chat_log.predicted_intent:
            return Response(
                {"detail": "corrected_intent must differ from the predicted intent."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        chat_log.feedback = feedback_value
        chat_log.feedback_at = timezone.now()
        chat_log.save(update_fields=["feedback", "feedback_at"])

        # Upsert into the dedicated feedback buffer
        buffer_defaults = {
            "student_input": chat_log.transcript_text,
            "session_context": chat_log.session_context,
            "predicted_intent": chat_log.predicted_intent or "On-Topic Question",
            "confidence": chat_log.confidence,
            "feedback": feedback_value,
            "status": "pending",
        }
        if corrected_intent:
            buffer_defaults["corrected_intent"] = corrected_intent
            buffer_defaults["status"] = "relabelled"

        buffer_entry, created = IntentFeedbackBuffer.objects.update_or_create(
            chat_log=chat_log,
            defaults=buffer_defaults,
        )

        # Increment the retraining counter
        counter = IntentRetrainingCounter.increment()

        return Response(
            {
                "id": chat_log.id,
                "feedback": chat_log.feedback,
                "feedback_at": chat_log.feedback_at,
                "retraining_counter": counter.reviews_since_last_train,
                "threshold": counter.threshold,
                "retraining_recommended": counter.threshold_reached(),
            },
            status=status.HTTP_200_OK,
        )


class IntentFeedbackBufferViewSet(viewsets.ModelViewSet):
    """
    Admin/operator view for the reviewed utterance buffer.

    Allows relabelling thumbs-down entries via PATCH corrected_intent.
    """
    serializer_class = IntentFeedbackBufferSerializer
    permission_classes = [permissions.IsAdminUser]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return IntentFeedbackBuffer.objects.select_related("chat_log__user", "chat_log__lesson")

    def partial_update(self, request, *args, **kwargs):
        """Permit admins to set corrected_intent on a buffer entry."""
        instance = self.get_object()
        corrected = request.data.get("corrected_intent")
        if corrected:
            if corrected == instance.predicted_intent:
                return Response(
                    {"detail": "Corrected intent must differ from predicted intent."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            instance.corrected_intent = corrected
            instance.status = "relabelled"
            instance.save(update_fields=["corrected_intent", "status"])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class IntentRetrainingCounterViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only view of the retraining counter. Admins may PATCH threshold."""
    serializer_class = IntentRetrainingCounterSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        # Only the singleton row exists
        return IntentRetrainingCounter.objects.filter(pk=1)

    def list(self, request, *args, **kwargs):
        counter = IntentRetrainingCounter.get()
        serializer = self.get_serializer(counter)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return Response(
                {"detail": "Only staff can update the threshold."},
                status=status.HTTP_403_FORBIDDEN,
            )
        counter = IntentRetrainingCounter.get()
        threshold = request.data.get("threshold")
        if threshold is not None:
            try:
                counter.threshold = max(1, int(threshold))
                counter.save(update_fields=["threshold"])
            except (TypeError, ValueError):
                return Response(
                    {"detail": "threshold must be a positive integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        serializer = self.get_serializer(counter)
        return Response(serializer.data)


class BookmarkViewSet(viewsets.ModelViewSet):
    """Bookmark CRUD for the authenticated user."""
    serializer_class = BookmarkSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return Bookmark.objects.filter(user=self.request.user).select_related("lesson__module__course")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StudentLearningProfileViewSet(viewsets.ModelViewSet):
    """
    Persistent per-student learning profile.
    GET returns the single profile. POST creates or overwrites it.
    PATCH partially updates profile_data fields (e.g. recurrent_mistakes).
    """
    serializer_class = StudentLearningProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return StudentLearningProfile.objects.filter(student=self.request.user)

    def list(self, request, *args, **kwargs):
        """Return the single profile directly, not as a list."""
        profile = StudentLearningProfile.objects.filter(student=request.user).first()
        if not profile:
            return Response(
                {"detail": "No learning profile yet. Complete a session first."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(StudentLearningProfileSerializer(profile).data)

    def create(self, request, *args, **kwargs):
        """
        Create or overwrite the student's learning profile.
        Uses get_or_create to ensure one row per student, then overwrites fields.
        """
        profile, created = StudentLearningProfile.objects.get_or_create(
            student=request.user,
            defaults={
                "sessions_count": request.data.get("sessions_count", 0),
                "profile_summary": request.data.get("profile_summary", ""),
                "profile_data": request.data.get("profile_data", {}),
            },
        )

        if not created:
            # Only sessions_count is writable here. profile_summary / profile_data
            # are owned solely by the single writer (profile_service.apply_claims
            # via /progress/profile/apply/). Overwrites here are ignored.
            if "sessions_count" in request.data:
                profile.sessions_count = request.data.get("sessions_count", profile.sessions_count)
                profile.save(update_fields=["sessions_count"])

        serializer = StudentLearningProfileSerializer(profile)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH — sessions_count only.

        profile_data and profile_summary are owned SOLELY by the single writer
        (profile_service.apply_claims via /progress/profile/apply/), and
        concept_mastery by mastery_service.record_events. Any of those in the
        payload here are IGNORED (logged) — there is one writer per signal.
        """
        pk = kwargs.get("pk")
        if pk:
            profile = StudentLearningProfile.objects.filter(student=request.user, pk=pk).first()
        else:
            profile = StudentLearningProfile.objects.filter(student=request.user).first()

        if not profile:
            return Response(
                {"detail": "No learning profile yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if "sessions_count" in request.data:
            profile.sessions_count = request.data["sessions_count"]
            profile.save(update_fields=["sessions_count"])

        for owned in ("profile_data", "profile_summary", "concept_mastery"):
            if owned in request.data:
                logger.warning(
                    "learning-profile PATCH included %s — IGNORED (single-writer). student=%s",
                    owned, request.user.id,
                )

        return Response(StudentLearningProfileSerializer(profile).data)

    @action(detail=False, methods=["patch"], url_path="update")
    def patch_profile(self, request):
        """PATCH /learning-profile/update/ — list-level patch alias."""
        return self.partial_update(request)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def concept_mastery_view(request):
    """GET /api/progress/concept-mastery/?course=<id>
    Returns the student's concept_mastery vector, optionally filtered by course.
    Each entry is enriched with the concept label.
    """
    from apps.courses.models import Concept

    course_id = request.query_params.get("course")
    profile = StudentLearningProfile.objects.filter(student=request.user).first()
    if not profile:
        return Response([])

    cm = profile.concept_mastery or {}

    if course_id:
        concept_ids_in_course = set(
            str(c_id) for c_id in
            Concept.objects.filter(course_id=course_id).values_list("id", flat=True)
        )
        cm = {k: v for k, v in cm.items() if k in concept_ids_in_course}

    # Resolve labels for the remaining concept IDs
    try:
        numeric_ids = [int(k) for k in cm if k.isdigit()]
        label_map = {
            str(c.id): c.label
            for c in Concept.objects.filter(id__in=numeric_ids)
        }
    except Exception:
        label_map = {}

    result = [
        {"concept_id": k, "label": label_map.get(k, k), **v}
        for k, v in cm.items()
    ]
    return Response(result)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def mastery_record(request):
    """THE single concept-mastery write endpoint (cross-process callers).

    Body: ``{"events": [{outcome, source, alpha?, evidence_delta?, mistake_tag?,
    concept_id? | (topic + course_id)}]}``. The student is the authenticated
    user (service callers impersonate via X-Student-ID). Topic-only events are
    mapped to a Concept here (logged, with a confidence floor below which they
    are DROPPED). All events funnel into the one mutator, mastery_service.record_events.

    TODO(loud): the in-session checkpoint generator should tag its MCQs with
    concept_id end-to-end so we stop fuzzy-mapping topics on the live write path.
    Until then, low-confidence/no-match topics are dropped, not written.
    """
    from apps.courses.models import Concept
    from apps.courses.concept_match import build_matcher
    from .mastery_service import record_events

    student_id = request.user.id
    raw_events = request.data.get("events", [])
    if not isinstance(raw_events, list) or not raw_events:
        return Response({"error": "events (non-empty list) required."}, status=status.HTTP_400_BAD_REQUEST)

    resolved: list[dict] = []
    dropped = 0
    _matchers: dict[str, object] = {}
    for e in raw_events:
        cid = e.get("concept_id")
        if not cid:
            topic = e.get("topic")
            course_id = e.get("course_id")
            if not topic or not course_id:
                dropped += 1
                logger.warning("mastery_record: event lacks concept_id and topic/course_id — DROPPED: %s", e)
                continue
            course_id = str(course_id)
            if course_id not in _matchers:
                _matchers[course_id] = build_matcher(list(Concept.objects.filter(course_id=course_id)))
            concept, conf = _matchers[course_id].match(topic)
            if concept is None or conf < MASTERY_TOPIC_MATCH_FLOOR:
                dropped += 1
                logger.warning(
                    "mastery_record: topic→concept DROP topic=%r course=%s "
                    "match=%s conf=%.2f floor=%.2f source=%s",
                    topic, course_id, getattr(concept, "label", None),
                    conf, MASTERY_TOPIC_MATCH_FLOOR, e.get("source"),
                )
                continue
            logger.info(
                "mastery_record: topic→concept MAP topic=%r -> %s(id=%s) conf=%.2f source=%s",
                topic, concept.label, concept.id, conf, e.get("source"),
            )
            cid = str(concept.id)
        resolved.append({
            "concept_id": str(cid),
            "outcome": e.get("outcome"),
            "source": e.get("source", "checkpoint"),
            "alpha": e.get("alpha", 0.3),
            "evidence_delta": e.get("evidence_delta", 1),
            "mistake_tag": e.get("mistake_tag", ""),
        })

    updated = record_events(student_id, resolved) if resolved else {}

    # Post-generation adaptivity (Batch 11a): when the caller knows the current
    # plan (plan_version + course_id), evaluate remediation off the just-updated
    # read-model. Decoupled from record_events (the pure fold); best-effort.
    remediation = None
    plan_version = request.data.get("plan_version")
    course_id = request.data.get("course_id")
    if updated and plan_version is not None and course_id is not None:
        try:
            from apps.courses.models import Enrollment
            from .remediation_service import evaluate_from_request
            enrollment = Enrollment.objects.filter(
                student_id=student_id, course_id=course_id
            ).first()
            if enrollment:
                remediation = evaluate_from_request(student_id, enrollment, plan_version, updated)
        except Exception:
            logger.exception("remediation evaluation failed (student=%s)", student_id)

    return Response({"updated": updated, "dropped": dropped, "remediation": remediation})


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def profile_apply(request):
    """THE single learning-profile write endpoint.

    Body: ``{"claims": [Claim...], "summary"?: str, "summary_source"?: "session"}``.
    Profilers send structured, validated claims; the writer merges them additively
    under a row lock (provenance/confidence resolve collisions). No reader-side
    merge, no overwrite. The student is the authenticated user.
    """
    from .profile_service import apply_claims
    pd = apply_claims(
        request.user.id,
        request.data.get("claims", []),
        summary=request.data.get("summary"),
        summary_source=request.data.get("summary_source"),
    )
    return Response({"profile_data": pd})


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def internal_complete_session(request):
    """Server-side session-completion trigger (THE genuine end-of-session event).

    Called by the AI service from the problem-set completion handler (service-key
    + X-Student-ID auth resolves the student), so completion is recorded even if
    the student's tab closes right after the final step. Idempotent: the gamified
    transition fires exactly once per session.

    Body: ``{"course_id": int, "session_number": int, "time_spent_minutes"?: int, "score"?: int}``.
    """
    from apps.courses.models import Course
    from .completion_service import complete_session

    course_id = request.data.get("course_id")
    session_number = request.data.get("session_number")

    try:
        course = Course.objects.get(pk=int(course_id))
        session_number = int(session_number)
    except (Course.DoesNotExist, TypeError, ValueError):
        return Response({"detail": "course_id or session_number missing/invalid."}, status=status.HTTP_404_NOT_FOUND)

    result = complete_session(
        request.user,
        course,
        session_number,
        time_spent_minutes=request.data.get("time_spent_minutes"),
        score=request.data.get("score"),
    )
    if result is None:
        return Response(
            {"detail": "No enrollment for this course."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    data = SessionCompletionSerializer(result["completion"]).data
    data["already_completed"] = result["already_completed"]
    data["newly_earned_achievements"] = result["newly_earned_achievements"]
    return Response(data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def concept_mastery_history(request, concept_id):
    """GET /progress/concept-mastery/<concept_id>/history/ — explainability.

    Returns the ordered events for this student+concept and the running score
    after each, so you can say WHY a concept moved (which source, when, how much).
    """
    from .mastery_service import fold_events

    events = list(
        ConceptMasteryEvent.objects
        .filter(student=request.user, concept_id=str(concept_id))
        .order_by("created_at", "id")
    )
    history = []
    for i, ev in enumerate(events, 1):
        folded = fold_events(events[:i])
        history.append({
            "source": ev.source,
            "outcome": ev.outcome,
            "alpha": ev.alpha,
            "evidence_delta": ev.evidence_delta,
            "mistake_tag": ev.mistake_tag,
            "resulting_score": folded["score"],
            "created_at": ev.created_at.isoformat(),
        })
    return Response({
        "concept_id": str(concept_id),
        "events": history,
        "current": fold_events(events) if events else None,
    })


def _emotion_consent_payload(consent):
    return {
        "granted": bool(consent and consent.granted),
        "granted_at": consent.granted_at.isoformat() if consent and consent.granted_at else None,
        "withdrawn_at": consent.withdrawn_at.isoformat() if consent and consent.withdrawn_at else None,
        "policy_version": consent.policy_version if consent else "",
        "required": bool(getattr(settings, "EMOTION_CONSENT_REQUIRED", True)),
        "current_policy_version": getattr(settings, "EMOTION_CONSENT_POLICY_VERSION", ""),
    }


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def emotion_consent(request):
    """GET the caller's emotion-capture consent state (off by default).

    Also the endpoint the AI service calls (service-key + X-Student-ID) to
    enforce consent before any emotion is fused/persisted.
    """
    from .models import EmotionConsent
    consent = EmotionConsent.objects.filter(student=request.user).first()
    return Response(_emotion_consent_payload(consent))


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def emotion_consent_grant(request):
    """Record explicit, informed opt-in for emotion capture."""
    from .models import EmotionConsent
    consent, _ = EmotionConsent.objects.get_or_create(student=request.user)
    consent.granted = True
    consent.granted_at = timezone.now()
    consent.withdrawn_at = None
    consent.policy_version = request.data.get(
        "policy_version", getattr(settings, "EMOTION_CONSENT_POLICY_VERSION", "")
    )
    consent.save()
    logger.info("emotion consent GRANTED student=%s policy=%s", request.user.id, consent.policy_version)
    return Response(_emotion_consent_payload(consent))


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def emotion_consent_withdraw(request):
    """Withdraw consent: stops capture going forward and purges the student's
    retained RAW emotion (best-effort call to the AI raw-emotion store). The
    derived qualitative profile claim — not raw biometric — is unaffected."""
    import os
    import requests as _requests
    from .models import EmotionConsent

    consent, _ = EmotionConsent.objects.get_or_create(student=request.user)
    consent.granted = False
    consent.withdrawn_at = timezone.now()
    consent.save()

    purged = None
    try:
        ai_url = os.getenv("AI_SERVICE_URL", "http://localhost:8001").rstrip("/")
        resp = _requests.post(
            f"{ai_url}/emotion/purge",
            json={"student_id": str(request.user.id)},
            headers={"X-Service-Key": os.getenv("INTERNAL_SERVICE_KEY", "")},
            timeout=8,
        )
        if resp.status_code == 200:
            purged = resp.json().get("purged")
    except Exception:
        logger.warning("emotion withdraw: raw-emotion purge call failed (student=%s)", request.user.id)

    logger.info("emotion consent WITHDRAWN student=%s purged=%s", request.user.id, purged)
    data = _emotion_consent_payload(consent)
    data["purged"] = purged
    return Response(data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def practice_completion(request):
    """Award bonus XP when a student passes a session-end practice problem.

    Body: { session_number: int, score: int }
    Returns: { xp_awarded: int, new_total: int, new_level: int }
    """
    from apps.users.models import StudentProfile

    try:
        score = int(request.data.get('score', 0))
        session_number = int(request.data.get('session_number', 0))
    except (TypeError, ValueError):
        return Response({"error": "Invalid score or session_number"}, status=status.HTTP_400_BAD_REQUEST)

    if score < 60:
        return Response({"xp_awarded": 0, "new_total": 0, "new_level": 0})

    xp_awarded = 50 if score >= 90 else 25

    try:
        profile, _ = StudentProfile.objects.get_or_create(user=request.user)
        profile.current_xp = (profile.current_xp or 0) + xp_awarded
        profile.level = min(10, max(1, profile.current_xp // 200 + 1))
        profile.save(update_fields=["current_xp", "level"])
        return Response({
            "xp_awarded": xp_awarded,
            "new_total": profile.current_xp,
            "new_level": profile.level,
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def trigger_retraining(request):
    """Manually trigger intent model retraining. Admin only.

    Calls the check_intent_retraining management command and returns
    the result.  Rate-limited by AdminWriteThrottle.
    """
    from apps.core.permissions import IsVerifiedAdmin
    from apps.core.audit import log_admin_action
    from apps.core.throttles import AdminWriteThrottle

    if not IsVerifiedAdmin().has_permission(request, None):
        return Response({"error": "Admin access required"}, status=status.HTTP_403_FORBIDDEN)

    # Manual throttle check
    throttle = AdminWriteThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {"error": "Rate limit exceeded. Please wait before triggering again."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    try:
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("check_intent_retraining", stdout=out)
        output = out.getvalue()

        log_admin_action(
            request,
            action="trigger_retraining",
            target_type="IntentModel",
        )

        return Response({
            "status": "success",
            "output": output,
        })
    except Exception as e:
        return Response(
            {"error": f"Retraining failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
