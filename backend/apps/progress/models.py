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
    time_spent_minutes = models.IntegerField(default=0)

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
# Bookmark — student-saved lessons or slides
# ------------------------------------------------------------------
class Bookmark(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )
    slide_index = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bookmarks"
        unique_together = ("user", "lesson", "slide_index")
        ordering = ["-created_at"]

    def __str__(self):
        if self.slide_index is not None:
            return f"{self.user.username} bookmarked slide {self.slide_index} of {self.lesson.title}"
        return f"{self.user.username} bookmarked {self.lesson.title}"




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
    # Concept-mastery is a SEPARATE field — the profiler LLM never writes here.
    # Only mastery.py (ai_service) updates these values via deterministic EMA.
    concept_mastery = models.JSONField(
        default=dict,
        help_text=(
            "Keys are concept IDs (str). Per-entry shape: "
            "{score: 0.0-1.0, evidence: int, trend: up|flat|down, "
            "last_updated: iso, linked_mistakes: []}."
        ),
    )

    class Meta:
        db_table = "student_learning_profiles"
        verbose_name = "Student Learning Profile"
        verbose_name_plural = "Student Learning Profiles"

    def __str__(self):
        return f"Learning Profile — {self.student.username} ({self.sessions_count} sessions)"
