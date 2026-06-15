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
    path("practice-completion/", views.practice_completion, name="practice_completion"),
    # Emotion-capture consent (Batch 11b) — off by default, opt-in, revocable.
    path("emotion-consent/", views.emotion_consent, name="emotion-consent"),
    path("emotion-consent/grant/", views.emotion_consent_grant, name="emotion-consent-grant"),
    path("emotion-consent/withdraw/", views.emotion_consent_withdraw, name="emotion-consent-withdraw"),
    path("concept-mastery/", views.concept_mastery_view, name="concept-mastery"),
    # The single learning-profile write path (additive, provenance-resolved).
    path("profile/apply/", views.profile_apply, name="profile-apply"),
    # The single concept-mastery write path + per-concept history (explainability).
    path("mastery/record/", views.mastery_record, name="mastery-record"),
    # Server-side lesson completion — triggered by the problem-set finish event.
    path("complete-lesson/", views.internal_complete_lesson, name="complete-lesson"),
    path("concept-mastery/<str:concept_id>/history/", views.concept_mastery_history, name="concept-mastery-history"),
]
