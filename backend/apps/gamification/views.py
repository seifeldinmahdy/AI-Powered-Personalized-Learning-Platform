from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Achievement, UserAchievement, DailyStudyStats, Notification
from .serializers import (
    AchievementSerializer,
    UserAchievementSerializer,
    DailyStudyStatsSerializer,
    NotificationSerializer,
)


class AchievementViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve all available achievements."""
    queryset = Achievement.objects.all()
    serializer_class = AchievementSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def mine(self, request):
        """Return achievements earned by the authenticated user."""
        earned = UserAchievement.objects.filter(user=request.user).select_related("achievement")
        serializer = UserAchievementSerializer(earned, many=True)
        return Response(serializer.data)


class DailyStudyStatsViewSet(viewsets.ModelViewSet):
    """CRUD for daily study stats. Scoped to authenticated user."""
    serializer_class = DailyStudyStatsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DailyStudyStats.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """In-app notifications for the authenticated user."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["post"])
    def read_all(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({"status": "all marked read"})
