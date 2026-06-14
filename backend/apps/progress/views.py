from django.apps import apps
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from .throttles import FeedbackThrottle, AnonFeedbackThrottle

from .models import (
    LessonCompletion, SystemActivityLog, AIChatLog,
    StudentLearningProfile, Bookmark,
    IntentFeedbackBuffer, IntentRetrainingCounter,
)
from .serializers import (
    LessonCompletionSerializer,
    SystemActivityLogSerializer,
    AIChatLogSerializer,
    AIChatLogFeedbackSerializer,
    IntentFeedbackBufferSerializer,
    IntentRetrainingCounterSerializer,
    BookmarkSerializer,
    StudentLearningProfileSerializer,
)


class LessonCompletionViewSet(viewsets.ModelViewSet):
    """CRUD for lesson completions. Scoped to the authenticated user's enrollments."""
    serializer_class = LessonCompletionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = LessonCompletion.objects.filter(enrollment__student=self.request.user)
        enrollment_id = self.request.query_params.get("enrollment_id")
        if enrollment_id:
            qs = qs.filter(enrollment_id=enrollment_id)
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Mark a lesson completion as Completed and set completed_at."""
        from apps.gamification.models import UserAchievement

        completion = self.get_object()
        user = request.user

        # Snapshot achievements before save so we can detect newly earned ones
        before_ids = set(
            UserAchievement.objects.filter(user=user).values_list("achievement_id", flat=True)
        )

        completion.status = "Completed"
        completion.completed_at = timezone.now()
        if "score" in request.data:
            completion.score = request.data["score"]
        time_spent = request.data.get("time_spent_minutes")
        if time_spent is not None:
            try:
                completion.time_spent_minutes = max(0, int(time_spent))
            except (TypeError, ValueError):
                pass
        else:
            completion.time_spent_minutes = 30  # backward-compat default
        completion.save()  # triggers gamification signal

        # Detect newly awarded achievements
        after = UserAchievement.objects.filter(user=user).select_related("achievement")
        newly_earned = [
            {"name": ua.achievement.name, "icon_url": ua.achievement.icon_url, "xp_reward": ua.achievement.xp_reward}
            for ua in after if ua.achievement_id not in before_ids
        ]

        data = LessonCompletionSerializer(completion).data
        data["newly_earned_achievements"] = newly_earned
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
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    def perform_create(self, serializer):
        """Save chat log, ensuring the user is enrolled in the lesson's course."""
        lesson = serializer.validated_data.get("lesson")
        if lesson and not self._user_has_access(lesson):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You are not enrolled in this lesson.")
        serializer.save(user=self.request.user)

    def _user_has_access(self, lesson):
        """Check whether the authenticated user is enrolled in the lesson's course."""
        Enrollment = apps.get_model("courses", "Enrollment")
        return Enrollment.objects.filter(
            student=self.request.user,
            course=lesson.module.course,
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
            # Overwrite existing profile with new data
            profile.sessions_count = request.data.get("sessions_count", profile.sessions_count)
            profile.profile_summary = request.data.get("profile_summary", profile.profile_summary)
            profile.profile_data = request.data.get("profile_data", profile.profile_data)
            profile.save()

        serializer = StudentLearningProfileSerializer(profile)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH — merge incoming profile_data fields into existing profile_data.
        Works both at /learning-profile/<pk>/ and /learning-profile/ (list level).
        Useful for updating recurrent_mistakes without overwriting the full profile.
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

        incoming_data = request.data.get("profile_data")
        if incoming_data and isinstance(incoming_data, dict):
            existing = profile.profile_data or {}
            existing.update(incoming_data)
            profile.profile_data = existing
            profile.save(update_fields=["profile_data"])

        if "profile_summary" in request.data:
            profile.profile_summary = request.data["profile_summary"]
            profile.save(update_fields=["profile_summary"])

        return Response(StudentLearningProfileSerializer(profile).data)

    @action(detail=False, methods=["patch"], url_path="update")
    def patch_profile(self, request):
        """PATCH /learning-profile/update/ — list-level patch alias."""
        return self.partial_update(request)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def practice_completion(request):
    """Award bonus XP when a student passes a lesson-end practice problem.

    Body: { lesson_id: int, score: int }
    Returns: { xp_awarded: int, new_total: int, new_level: int }
    """
    from apps.users.models import StudentProfile

    try:
        score = int(request.data.get('score', 0))
        lesson_id = int(request.data.get('lesson_id', 0))
    except (TypeError, ValueError):
        return Response({"error": "Invalid score or lesson_id"}, status=status.HTTP_400_BAD_REQUEST)

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
