from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"lesson-completions", views.LessonCompletionViewSet, basename="lesson-completion")
router.register(r"activity-logs", views.SystemActivityLogViewSet, basename="activity-log")
router.register(r"chat-logs", views.AIChatLogViewSet, basename="chat-log")
router.register(r"bookmarks", views.BookmarkViewSet, basename="bookmark")
router.register(r"learning-profile", views.StudentLearningProfileViewSet, basename="learning-profile")

urlpatterns = [
    path("", include(router.urls)),
]
