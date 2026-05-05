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
    path("coding/evaluate-graded/", views.evaluate_student_code_graded, name="evaluate_code_graded"),
    path("coding/rubric/", views.get_coding_rubric, name="coding_rubric"),
    path("coding/hint/", views.get_coding_hint, name="coding_hint"),
    path("admin/stats/", views.admin_stats, name="admin_stats"),
    path("my-courses/", views.my_courses, name="my_courses"),
    path("my-courses/<int:course_id>/students/", views.my_course_students, name="my_course_students"),
]
