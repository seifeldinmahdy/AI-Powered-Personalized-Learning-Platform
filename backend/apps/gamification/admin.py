from django.contrib import admin
from .models import Achievement, UserAchievement, DailyStudyStats


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("name", "xp_reward", "description")
    search_fields = ("name",)


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ("user", "achievement", "earned_at")
    list_filter = ("achievement", "earned_at")
    search_fields = ("user__username", "achievement__name")


@admin.register(DailyStudyStats)
class DailyStudyStatsAdmin(admin.ModelAdmin):
    list_display = ("user", "study_date", "hours_spent")
    list_filter = ("study_date",)
    search_fields = ("user__username",)
