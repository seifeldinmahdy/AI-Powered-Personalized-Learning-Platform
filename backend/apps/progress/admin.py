from django.contrib import admin
from .models import LessonCompletion, SystemActivityLog, AIChatLog, StudentLearningProfile


@admin.register(LessonCompletion)
class LessonCompletionAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "lesson", "status", "score", "completed_at")
    list_filter = ("status",)
    search_fields = ("enrollment__student__username", "lesson__title")


@admin.register(SystemActivityLog)
class SystemActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action_type", "target_course", "created_at")
    list_filter = ("action_type", "created_at")
    search_fields = ("user__username", "action_type")


@admin.register(AIChatLog)
class AIChatLogAdmin(admin.ModelAdmin):
    list_display = ("user", "lesson", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "lesson__title", "transcript_text")




@admin.register(StudentLearningProfile)
class StudentLearningProfileAdmin(admin.ModelAdmin):
    list_display = ("student", "sessions_count", "last_updated")
    list_filter = ("last_updated",)
    search_fields = ("student__username",)
    readonly_fields = ("profile_summary", "profile_data", "last_updated")

