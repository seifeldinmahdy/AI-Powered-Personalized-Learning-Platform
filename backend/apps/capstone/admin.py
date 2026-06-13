from django.contrib import admin
from .models import (
    Capstone, CapstoneRubricItem, CapstoneProposal, CapstoneSubmission,
    Team, MatchmakingQueueEntry, CapstoneAssistQuota, CapstoneAssistLog,
)


class RubricItemInline(admin.TabularInline):
    model = CapstoneRubricItem
    extra = 1
    fields = ("text", "category", "clo", "concept", "weight", "min_team_size", "order")


@admin.register(Capstone)
class CapstoneAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "spec_mode", "team_mode", "status", "created_at")
    list_filter = ("spec_mode", "team_mode", "status")
    inlines = [RubricItemInline]


@admin.register(CapstoneRubricItem)
class CapstoneRubricItemAdmin(admin.ModelAdmin):
    list_display = ("capstone", "category", "weight", "min_team_size", "order")
    list_filter = ("category",)


@admin.register(CapstoneProposal)
class CapstoneProposalAdmin(admin.ModelAdmin):
    list_display = ("capstone", "student", "approval_status", "submitted_at")
    list_filter = ("approval_status",)


@admin.register(CapstoneSubmission)
class CapstoneSubmissionAdmin(admin.ModelAdmin):
    list_display = ("capstone", "enrollment", "team", "score", "status", "submitted_at")
    list_filter = ("status",)
    readonly_fields = ("results", "score", "feedback", "contributions", "evaluated_at")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "capstone", "status", "created_at")
    list_filter = ("status",)
    filter_horizontal = ("members",)


@admin.register(MatchmakingQueueEntry)
class MatchmakingQueueEntryAdmin(admin.ModelAdmin):
    list_display = ("student", "capstone", "status", "joined_at", "fill_window_expires_at")
    list_filter = ("status",)


@admin.register(CapstoneAssistQuota)
class CapstoneAssistQuotaAdmin(admin.ModelAdmin):
    list_display = ("capstone", "student", "team", "used", "limit", "period", "period_start")
    list_filter = ("period",)


@admin.register(CapstoneAssistLog)
class CapstoneAssistLogAdmin(admin.ModelAdmin):
    list_display = ("student", "capstone", "concept", "created_at")
    readonly_fields = ("question", "response_excerpt", "created_at")
