from django.contrib import admin
from .models import (
    SessionCompletion, SystemActivityLog, AIChatLog,
    StudentLearningProfile, Bookmark,
    IntentFeedbackBuffer, IntentRetrainingCounter,
)


@admin.register(SessionCompletion)
class SessionCompletionAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "session_number", "status", "score", "completed_at")
    list_filter = ("status",)
    search_fields = ("enrollment__student__username",)


@admin.register(SystemActivityLog)
class SystemActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action_type", "target_course", "created_at")
    list_filter = ("action_type", "created_at")
    search_fields = ("user__username", "action_type")


@admin.register(AIChatLog)
class AIChatLogAdmin(admin.ModelAdmin):
    list_display = (
        "user", "course", "session_number", "predicted_intent", "confidence",
        "feedback", "created_at", "used_for_retraining",
    )
    list_filter = ("predicted_intent", "feedback", "used_for_retraining", "created_at")
    search_fields = ("user__username", "course__title", "transcript_text", "session_id")
    readonly_fields = ("created_at", "feedback_at")


@admin.register(IntentFeedbackBuffer)
class IntentFeedbackBufferAdmin(admin.ModelAdmin):
    list_display = (
        "chat_log", "predicted_intent", "feedback",
        "corrected_intent", "status", "confidence", "created_at",
    )
    list_filter = ("feedback", "status", "predicted_intent", "corrected_intent")
    search_fields = ("student_input", "chat_log__user__username")
    readonly_fields = ("created_at", "used_at")


@admin.register(IntentRetrainingCounter)
class IntentRetrainingCounterAdmin(admin.ModelAdmin):
    list_display = ("reviews_since_last_train", "threshold", "last_trained_at", "updated_at")
    readonly_fields = ("reviews_since_last_train", "last_trained_at", "updated_at")


@admin.register(StudentLearningProfile)
class StudentLearningProfileAdmin(admin.ModelAdmin):
    list_display = ("student", "sessions_count", "last_updated")
    list_filter = ("last_updated",)
    search_fields = ("student__username",)
    readonly_fields = ("profile_summary", "profile_data", "last_updated")
