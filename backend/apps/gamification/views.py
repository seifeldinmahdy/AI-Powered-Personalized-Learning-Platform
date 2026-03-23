from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Achievement, UserAchievement, DailyStudyStats
from .serializers import (
    AchievementSerializer,
    UserAchievementSerializer,
    DailyStudyStatsSerializer,
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
