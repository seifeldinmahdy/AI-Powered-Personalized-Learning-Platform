from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"lesson-completions", views.LessonCompletionViewSet, basename="lesson-completion")
router.register(r"activity-logs", views.SystemActivityLogViewSet, basename="activity-log")
router.register(r"chat-logs", views.AIChatLogViewSet, basename="chat-log")

urlpatterns = [
    path("", include(router.urls)),
]
