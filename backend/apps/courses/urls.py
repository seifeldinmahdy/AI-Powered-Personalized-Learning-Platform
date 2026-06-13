from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import certificate

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
    # Concepts (nested under course)
    path(
        "courses/<int:course_pk>/concepts/",
        views.ConceptViewSet.as_view({"get": "list"}),
        name="concept-list",
    ),
    path(
        "courses/<int:course_pk>/concepts/<int:pk>/",
        views.ConceptViewSet.as_view({"get": "retrieve"}),
        name="concept-detail",
    ),
    # CLOs (nested under course)
    path(
        "courses/<int:course_pk>/clos/",
        views.CourseLearningOutcomeViewSet.as_view({"get": "list", "post": "create"}),
        name="clo-list",
    ),
    path(
        "courses/<int:course_pk>/clos/<int:pk>/",
        views.CourseLearningOutcomeViewSet.as_view({
            "get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"
        }),
        name="clo-detail",
    ),
    path(
        "courses/<int:course_pk>/clos/suggest/",
        views.CourseLearningOutcomeViewSet.as_view({"post": "suggest"}),
        name="clo-suggest",
    ),
    path(
        "courses/<int:course_pk>/clos/attainment/",
        views.CourseLearningOutcomeViewSet.as_view({"get": "attainment"}),
        name="clo-attainment",
    ),
    # Course corpus (admin-defined source material; read open for scope resolution)
    path(
        "courses/<int:course_pk>/corpus/",
        views.CourseCorpusViewSet.as_view({"get": "retrieve_corpus"}),
        name="course-corpus",
    ),
    path(
        "courses/<int:course_pk>/corpus/sources/",
        views.CourseCorpusViewSet.as_view({"post": "add_source"}),
        name="corpus-source-add",
    ),
    path(
        "courses/<int:course_pk>/corpus/sources/<int:pk>/",
        views.CourseCorpusViewSet.as_view({"delete": "remove_source"}),
        name="corpus-source-remove",
    ),
    # Completion certificate (gated on course complete + survey submitted)
    path(
        "courses/<int:course_id>/certificate/",
        certificate.certificate_data,
        name="certificate-data",
    ),
    path(
        "courses/<int:course_id>/certificate/pdf/",
        certificate.certificate_pdf,
        name="certificate-pdf",
    ),
]
