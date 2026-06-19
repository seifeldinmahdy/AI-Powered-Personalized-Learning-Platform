"""URL routes for the authenticated AI-service proxy (Track 1)."""

from django.urls import path

from . import views

urlpatterns = [
    path(
        "student-context/<str:course_id>/",
        views.student_context,
        name="ai-student-context",
    ),
    path(
        "student-context/<str:course_id>/update-performance/",
        views.update_performance,
        name="ai-student-context-update-performance",
    ),
    # Group C: profiler
    path("profiler/run-session/", views.profiler_run_session,
         name="ai-profiler-run-session"),
    path("profiler/fuse-emotions/", views.profiler_fuse_emotions,
         name="ai-profiler-fuse-emotions"),
    path("profiler/audit-log/", views.profiler_audit_log,
         name="ai-profiler-audit-log"),
    # Group B: pathway reads + slides
    path("pathway/current/<str:course_id>/", views.pathway_current,
         name="ai-pathway-current"),
    path("pathway/mine/", views.pathway_mine, name="ai-pathway-mine"),
    path("pathway/<str:course_id>/provenance/", views.pathway_provenance,
         name="ai-pathway-provenance"),
    path("pathway/session-chunks/", views.pathway_session_chunks,
         name="ai-pathway-session-chunks"),
    path("slides/generate/", views.slides_generate, name="ai-slides-generate"),
    path("slides/persisted/<str:course_id>/", views.slides_persisted,
         name="ai-slides-persisted"),
    # In-session MCQ knowledge checkpoints
    path("assessments/session/", views.assessments_session,
         name="ai-assessments-session"),
    path("assessments/submit/", views.assessments_submit,
         name="ai-assessments-submit"),
]
