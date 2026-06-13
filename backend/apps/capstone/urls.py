from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"capstones", views.CapstoneViewSet, basename="capstone")
router.register(
    r"capstones/(?P<capstone_pk>[^/.]+)/rubric-items",
    views.CapstoneRubricItemViewSet,
    basename="capstone-rubric-item",
)
router.register(r"proposals", views.CapstoneProposalViewSet, basename="capstone-proposal")
router.register(r"submissions", views.CapstoneSubmissionViewSet, basename="capstone-submission")

urlpatterns = [
    path("", include(router.urls)),
    path("course/<int:course_id>/", views.capstone_for_course, name="capstone-for-course"),
    path("capstones/<int:capstone_id>/my-submission/", views.my_submission, name="capstone-my-submission"),
    path("capstones/<int:capstone_id>/submit/", views.submit_archive, name="capstone-submit-archive"),
    path("capstones/<int:capstone_id>/provision-repo/", views.provision_repo, name="capstone-provision-repo"),
    path("capstones/<int:capstone_id>/submit-from-repo/", views.submit_from_repo, name="capstone-submit-from-repo"),
    path("capstones/<int:capstone_id>/submit-for-grading/", views.submit_for_grading, name="capstone-submit-for-grading"),
    path("github-webhook/", views.github_webhook, name="capstone-github-webhook"),

    # Batch 3 — in-platform IDE
    path("capstones/<int:capstone_id>/tree/", views.repo_tree, name="capstone-tree"),
    path("capstones/<int:capstone_id>/file/", views.repo_file, name="capstone-file"),
    path("capstones/<int:capstone_id>/commit/", views.commit_files, name="capstone-commit"),
    path("commit-status/<str:sha>/", views.commit_status, name="capstone-commit-status"),
    path("capstones/<int:capstone_id>/run/", views.run_files, name="capstone-run"),

    # Batch 3 — AI assist
    path("capstones/<int:capstone_id>/assist/", views.assist, name="capstone-assist"),
    path("capstones/<int:capstone_id>/assist-quota/", views.assist_quota, name="capstone-assist-quota"),

    # Batch 3 — teams + matchmaking
    path("capstones/<int:capstone_id>/queue/join/", views.queue_join, name="capstone-queue-join"),
    path("capstones/<int:capstone_id>/queue/leave/", views.queue_leave, name="capstone-queue-leave"),
    path("capstones/<int:capstone_id>/recommendations/", views.teammate_recommendations, name="capstone-recommendations"),
    path("capstones/<int:capstone_id>/my-team/", views.my_team, name="capstone-my-team"),
    path("capstones/<int:capstone_id>/process-queue/", views.process_matchmaking, name="capstone-process-queue"),

    # Team role advisor (advisory only)
    path("team/<int:team_id>/role-advice/", views.team_role_advice, name="capstone-team-role-advice"),
    path("team/<int:team_id>/role-advice/refresh/", views.team_role_advice_refresh, name="capstone-team-role-advice-refresh"),
]
