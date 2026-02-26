from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models

class User(AbstractUser):
    """
    Custom user model for the AI-Powered Personalized Learning Platform.

    Extends Django's AbstractUser to include role-based access,
    a learner profile picture, bio, and a flexible JSON preferences
    field for storing learning styles and accessibility settings.
    """

    ROLE_CHOICES = [
        ("student", "Student"),
        ("admin", "Admin"),
        ("instructor", "Instructor"),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="student",
        help_text="Designates the user's role on the platform.",
    )
    profile_picture = models.ImageField(
        upload_to="profile_pics/",
        blank=True,
        null=True,
        help_text="Optional profile picture for the user.",
    )
    bio = models.TextField(
        blank=True,
        null=True,
        help_text="A short biography or description.",
    )
    preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text="Stores learning style preferences and accessibility settings (e.g., {'learning_style': 'visual'}).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


# ------------------------------------------------------------------
# Student Profile — gamification stats, XP, streaks, daily goals
# ------------------------------------------------------------------
class StudentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    bio = models.TextField(blank=True, default="")
    location = models.CharField(max_length=100, blank=True, default="")
    timezone = models.CharField(max_length=50, blank=True, default="")
    avatar_url = models.TextField(blank=True, default="")

    level = models.IntegerField(default=1)
    current_xp = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    total_minutes_learned = models.IntegerField(default=0)
    daily_goal_minutes = models.IntegerField(default=30)
    days_active = models.IntegerField(default=0)
    messages_count = models.IntegerField(default=0)

    class Meta:
        db_table = "student_profiles"
        verbose_name = "Student Profile"
        verbose_name_plural = "Student Profiles"

    def __str__(self):
        return f"{self.user.username} — Lvl {self.level} ({self.current_xp} XP)"


# ------------------------------------------------------------------
# User Preferences — notification / feature toggles
# ------------------------------------------------------------------
class UserPreferences(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences_profile",
    )
    email_notifications = models.BooleanField(default=True)
    ai_tutor_voice_enabled = models.BooleanField(default=True)
    study_reminders = models.BooleanField(default=True)

    class Meta:
        db_table = "user_preferences"
        verbose_name = "User Preferences"
        verbose_name_plural = "User Preferences"

    def __str__(self):
        return f"Preferences for {self.user.username}"


# ------------------------------------------------------------------
# Active Sessions — device / IP tracking
# ------------------------------------------------------------------
class ActiveSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="active_sessions",
    )
    device_name = models.CharField(max_length=100, blank=True, default="")
    ip_address = models.CharField(max_length=45, blank=True, default="")
    last_active = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "active_sessions"
        verbose_name = "Active Session"
        verbose_name_plural = "Active Sessions"

    def __str__(self):
        return f"{self.user.username} on {self.device_name or 'unknown device'}"
