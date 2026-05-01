from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"achievements", views.AchievementViewSet, basename="achievement")
router.register(r"daily-stats", views.DailyStudyStatsViewSet, basename="daily-stats")
router.register(r"notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [
    path("", include(router.urls)),
]
