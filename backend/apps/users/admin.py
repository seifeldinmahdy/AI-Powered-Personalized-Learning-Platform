from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, StudentProfile, UserPreferences, ActiveSession


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for the custom User model."""

    list_display = ("username", "email", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "email")

    # Add custom fields to the default UserAdmin fieldsets
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Platform Profile",
            {"fields": ("role", "profile_picture", "bio", "preferences")},
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "Platform Profile",
            {"fields": ("role",)},
        ),
    )


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "level", "current_xp", "current_streak", "days_active")
    search_fields = ("user__username",)


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user", "email_notifications", "ai_tutor_voice_enabled", "study_reminders")
    search_fields = ("user__username",)


@admin.register(ActiveSession)
class ActiveSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "ip_address", "last_active")
    search_fields = ("user__username", "device_name")
    list_filter = ("last_active",)
