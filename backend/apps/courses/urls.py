from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"courses", views.CourseViewSet, basename="course")
router.register(r"modules", views.ModuleViewSet, basename="module")
router.register(r"lessons", views.LessonViewSet, basename="lesson")
router.register(r"slides", views.SlideViewSet, basename="slide")
router.register(r"code-challenges", views.CodeChallengeViewSet, basename="code-challenge")
router.register(r"enrollments", views.EnrollmentViewSet, basename="enrollment")

urlpatterns = [
    path("", include(router.urls)),
    path("coding/evaluate/", views.evaluate_student_code, name="evaluate_code"),
    path("admin/stats/", views.admin_stats, name="admin_stats"),
]
