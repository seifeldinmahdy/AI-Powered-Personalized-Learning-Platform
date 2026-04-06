from django.db import models
from django.conf import settings


# ------------------------------------------------------------------
# Lesson Completion — tracks per-lesson progress within an enrollment
# ------------------------------------------------------------------
class LessonCompletion(models.Model):
    STATUS_CHOICES = [
        ("Started", "Started"),
        ("In Progress", "In Progress"),
        ("Completed", "Completed"),
    ]

    enrollment = models.ForeignKey(
        "courses.Enrollment",
        on_delete=models.CASCADE,
        related_name="lesson_completions",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.CASCADE,
        related_name="completions",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Started")
    score = models.IntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "lesson_completions"
        unique_together = ["enrollment", "lesson"]
        verbose_name = "Lesson Completion"
        verbose_name_plural = "Lesson Completions"

    def __str__(self):
        return f"{self.enrollment.student.username} — {self.lesson.title} ({self.status})"


# ------------------------------------------------------------------
# System Activity Log — audit trail of user actions
# ------------------------------------------------------------------
class SystemActivityLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    action_type = models.CharField(max_length=100)
    target_course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "system_activity_log"
        ordering = ["-created_at"]
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"

    def __str__(self):
        return f"{self.user.username} — {self.action_type}"


# ------------------------------------------------------------------
# AI Chat Log — conversation transcripts between user and AI tutor
# ------------------------------------------------------------------
class AIChatLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_chat_logs",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.CASCADE,
        related_name="ai_chat_logs",
    )
    user_audio_url = models.TextField(blank=True, default="")
    transcript_text = models.TextField()
    ai_response_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_chat_logs"
        ordering = ["-created_at"]
        verbose_name = "AI Chat Log"
        verbose_name_plural = "AI Chat Logs"

    def __str__(self):
        return f"Chat — {self.user.username} in {self.lesson.title}"




# ------------------------------------------------------------------
# Student Learning Profile — rewrite-based persistent profile per student.
# Overwritten (not appended) after each session by the profiler LLM.
# Dr. Nova reads profile_summary at session start to personalize teaching.
# ------------------------------------------------------------------
class StudentLearningProfile(models.Model):
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_profile",
    )
    last_updated = models.DateTimeField(auto_now=True)
    sessions_count = models.IntegerField(default=0)
    profile_summary = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Concise plain-English paragraph (max 5 sentences) written by the profiler LLM. "
            "This is what Dr. Nova reads at session start."
        ),
    )
    profile_data = models.JSONField(
        default=dict,
        help_text=(
            "Structured data used by the profiler LLM to rewrite intelligently. "
            "Keys: learning_style_signals, engagement_patterns, emotional_tendencies, "
            "recommended_approaches, topics_of_difficulty, topics_of_strength."
        ),
    )

    class Meta:
        db_table = "student_learning_profiles"
        verbose_name = "Student Learning Profile"
        verbose_name_plural = "Student Learning Profiles"

    def __str__(self):
        return f"Learning Profile — {self.student.username} ({self.sessions_count} sessions)"
