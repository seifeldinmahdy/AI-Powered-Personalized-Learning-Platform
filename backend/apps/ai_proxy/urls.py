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
    # Group D: assessments
    path("assessments/submit-placement/", views.assessments_submit_placement,
         name="ai-assessments-submit-placement"),
    path("assessments/session/", views.assessments_session,
         name="ai-assessments-session"),
    path("assessments/submit/", views.assessments_submit,
         name="ai-assessments-submit"),
    # Group E: problem-set (declare the specific 'lesson/<id>' before '<id>')
    path("problem-set/generate/", views.problem_set_generate,
         name="ai-problem-set-generate"),
    path("problem-set/regenerate/", views.problem_set_regenerate,
         name="ai-problem-set-regenerate"),
    path("problem-set/submit/", views.problem_set_submit,
         name="ai-problem-set-submit"),
    path("problem-set/hint/", views.problem_set_hint,
         name="ai-problem-set-hint"),
    path("problem-set/summary-viewed/", views.problem_set_summary_viewed,
         name="ai-problem-set-summary-viewed"),
    path("problem-set/lesson/<str:lesson_id>/", views.problem_set_by_lesson,
         name="ai-problem-set-by-lesson"),
    path("problem-set/<str:problem_set_id>/", views.problem_set_get,
         name="ai-problem-set-get"),
    # Group F: coding labs
    path("coding/labs/generate/", views.coding_lab_generate,
         name="ai-coding-lab-generate"),
    path("coding/labs/complete/", views.coding_lab_complete,
         name="ai-coding-lab-complete"),
    path("coding/labs/<str:lab_id>/note/cell/", views.coding_lab_note_cell,
         name="ai-coding-lab-note-cell"),
    path("coding/labs/<str:lab_id>/note/general/", views.coding_lab_note_general,
         name="ai-coding-lab-note-general"),
    path("coding/labs/<str:lab_id>/question/asked/", views.coding_lab_question_asked,
         name="ai-coding-lab-question-asked"),
]
