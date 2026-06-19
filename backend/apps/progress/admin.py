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
    list_display = ("student", "sessions_count", "profile_summary_source", "last_updated")
    list_filter = ("last_updated", "profile_summary_source")
    search_fields = ("student__username",)
    # concept_mastery is an event-sourced READ-MODEL (folded from
    # ConceptMasteryEvent). Hide the raw editable JSON so it can't be hand-edited
    # out of sync with its event log, and show a label-resolved, readable view.
    exclude = ("concept_mastery",)
    readonly_fields = (
        "profile_summary", "profile_summary_source", "profile_data",
        "concept_mastery_readable", "last_updated",
    )

    @admin.display(description="Concept mastery (read-model — folded, read-only)")
    def concept_mastery_readable(self, obj):
        from django.utils.html import format_html, format_html_join
        from apps.courses.models import Concept

        cm = obj.concept_mastery or {}
        if not cm:
            return "—"
        numeric_ids = [int(k) for k in cm if str(k).isdigit()]
        labels = {str(c.id): c.label for c in Concept.objects.filter(id__in=numeric_ids)}
        rows = format_html_join(
            "",
            "<tr><td style='padding:2px 14px 2px 0'>{}</td>"
            "<td style='padding:2px 14px 2px 0'>{}</td>"
            "<td style='padding:2px 14px 2px 0'>{}</td>"
            "<td style='padding:2px 14px 2px 0'>{}</td></tr>",
            (
                (labels.get(str(cid), "concept %s" % cid),
                 entry.get("score"), entry.get("trend"), entry.get("evidence"))
                for cid, entry in cm.items() if isinstance(entry, dict)
            ),
        )
        return format_html(
            "<table><thead><tr>"
            "<th style='text-align:left;padding:2px 14px 2px 0'>Concept</th>"
            "<th style='text-align:left;padding:2px 14px 2px 0'>Score</th>"
            "<th style='text-align:left;padding:2px 14px 2px 0'>Trend</th>"
            "<th style='text-align:left;padding:2px 14px 2px 0'>Evidence</th>"
            "</tr></thead><tbody>{}</tbody></table>",
            rows,
        )
