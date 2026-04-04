from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import LessonCompletion, SystemActivityLog, AIChatLog
from .serializers import (
    LessonCompletionSerializer,
    SystemActivityLogSerializer,
    AIChatLogSerializer,
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


class AIChatLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only AI chat logs for the authenticated user. Filter by ?lesson_id=<id>."""
    serializer_class = AIChatLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = AIChatLog.objects.filter(user=self.request.user)
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs
