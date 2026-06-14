from django.urls import path

from . import views

urlpatterns = [
    # Placement attempts (events)
    path("placement-attempts/", views.placement_attempt_create, name="placement-attempt-create"),
    path("placement-attempts/latest/", views.placement_attempt_latest, name="placement-attempt-latest"),

    # Slides + labs (index + inline content)
    path("", views.artifact_upsert, name="artifact-upsert"),
    path("index/", views.artifact_index, name="artifact-index"),
    path("<int:pk>/content/", views.artifact_content, name="artifact-content"),

    # Problem sets (index) + attempts (events).
    # NOTE: specific paths precede the <ps_uid> catch-alls.
    path("problem-sets/", views.problem_set_create, name="problem-set-create"),
    path("problem-sets/regen-count/", views.problem_set_regen_count, name="problem-set-regen-count"),
    path("problem-sets/score/", views.problem_set_score, name="problem-set-score"),
    path("problem-sets/<str:ps_uid>/", views.problem_set_detail, name="problem-set-detail"),
    path("problem-sets/<str:ps_uid>/attempts/", views.problem_set_attempt_create, name="problem-set-attempt-create"),
    path("problem-sets/<str:ps_uid>/hint-tracking/", views.problem_set_hint_tracking, name="problem-set-hint-tracking"),
]
