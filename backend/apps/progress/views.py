from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from .models import (
    LessonCompletion, SystemActivityLog, AIChatLog,
    StudentLearningProfile, Bookmark,
)
from .serializers import (
    LessonCompletionSerializer,
    SystemActivityLogSerializer,
    AIChatLogSerializer,
    StudentLearningProfileSerializer,
    BookmarkSerializer,
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
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = AIChatLog.objects.filter(user=self.request.user).order_by("created_at")
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)





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
    """
    serializer_class = StudentLearningProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

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
