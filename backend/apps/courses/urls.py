from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import certificate

router = DefaultRouter()
router.register(r"courses", views.CourseViewSet, basename="course")
router.register(r"enrollments", views.EnrollmentViewSet, basename="enrollment")

urlpatterns = [
    path("", include(router.urls)),
    path("coding/evaluate/", views.evaluate_student_code, name="evaluate_code"),
    path("coding/evaluate-graded/", views.evaluate_student_code_graded, name="evaluate_code_graded"),
    path("coding/rubric/", views.get_coding_rubric, name="coding_rubric"),
    path("coding/hint/", views.get_coding_hint, name="coding_hint"),
    path("admin/stats/", views.admin_stats, name="admin_stats"),
    # Resume summary (index + current plan; no content scan).
    path("<int:course_id>/resume/", views.course_resume, name="course-resume"),
    # Admin-only pathway regeneration (students get 403; proxies to AI service).
    path(
        "courses/<int:course_id>/pathway/regenerate/",
        views.regenerate_pathway,
        name="pathway-regenerate",
    ),
    # Admin-only: list a student's plan versions (proxies AI pathway store).
    path(
        "courses/<int:course_id>/pathway/versions/",
        views.pathway_versions,
        name="pathway-versions",
    ),
    # Concepts (nested under course)
    path(
        "courses/<int:course_pk>/concepts/",
        views.ConceptViewSet.as_view({"get": "list", "post": "create"}),
        name="concept-list",
    ),
    path(
        "courses/<int:course_pk>/concepts/<int:pk>/",
        views.ConceptViewSet.as_view({"get": "retrieve"}),
        name="concept-detail",
    ),
    path(
        "courses/<int:course_pk>/concepts/bulk-extract/",
        views.ConceptViewSet.as_view({"post": "bulk_extract"}),
        name="concept-bulk-extract",
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
    # Admin authoring: available books, upload, and index status.
    path(
        "courses/<int:course_pk>/corpus/available-books/",
        views.CourseCorpusViewSet.as_view({"get": "available_books"}),
        name="corpus-available-books",
    ),
    path(
        "courses/<int:course_pk>/corpus/upload/",
        views.CourseCorpusViewSet.as_view({"post": "upload_book"}),
        name="corpus-upload",
    ),
    path(
        "courses/<int:course_pk>/corpus/index-status/",
        views.CourseCorpusViewSet.as_view({"get": "index_status"}),
        name="corpus-index-status",
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
    # Admin: delete a book from the shared vector library ENTIRELY (all corpora).
    path(
        "courses/<int:course_pk>/corpus/library/<str:book_stem>/",
        views.CourseCorpusViewSet.as_view({"delete": "delete_book"}),
        name="corpus-library-delete",
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
    # Placement test (admin and student)
    path(
        'courses/<int:course_pk>/placement-questions/',
        views.PlacementQuestionViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='placement-questions-list',
    ),
    path(
        'courses/<int:course_pk>/placement-questions/bulk-save/',
        views.PlacementQuestionViewSet.as_view({'post': 'bulk_save'}),
        name='placement-questions-bulk-save',
    ),
    path(
        'courses/<int:course_pk>/placement-questions/<int:pk>/',
        views.PlacementQuestionViewSet.as_view({
            'get': 'retrieve', 'put': 'update',
            'patch': 'partial_update', 'delete': 'destroy'
        }),
        name='placement-questions-detail',
    ),
    path(
        'courses/<int:course_pk>/placement-test/',
        views.StudentPlacementTestView.as_view(),
        name='student-placement-test',
    ),
    path(
        'courses/<int:course_pk>/placement-test/score/',
        views.score_placement_submission,
        name='score-placement-submission',
    ),
]
