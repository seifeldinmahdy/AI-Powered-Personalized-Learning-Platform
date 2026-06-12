from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


# ------------------------------------------------------------------
# Intent labels shared by the TinyBERT-CNN classifier
# ------------------------------------------------------------------
INTENT_CHOICES = [
    ("On-Topic Question", "On-Topic Question"),
    ("Off-Topic Question", "Off-Topic Question"),
    ("Emotional-State", "Emotional-State"),
    ("Pace-Related", "Pace-Related"),
    ("Repeat/clarification", "Repeat/clarification"),
    ("Debugging/Code-Sharing", "Debugging/Code-Sharing"),
]

FEEDBACK_CHOICES = [
    ("thumbs_up", "👍 Thumbs Up"),
    ("thumbs_down", "👎 Thumbs Down"),
]


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

    # ── Intent classifier metadata ─────────────────────────────────
    session_id = models.CharField(max_length=64, blank=True, default="")
    session_context = models.TextField(blank=True, default="")
    predicted_intent = models.CharField(
        max_length=30,
        choices=INTENT_CHOICES,
        blank=True,
        default="",
        db_index=True,
    )
    confidence = models.FloatField(null=True, blank=True)
    intent_probabilities = models.JSONField(default=dict, blank=True)

    # ── User feedback ──────────────────────────────────────────────
    feedback = models.CharField(
        max_length=16,
        choices=FEEDBACK_CHOICES,
        null=True,
        blank=True,
        db_index=True,
    )
    feedback_at = models.DateTimeField(null=True, blank=True)
    used_for_retraining = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "ai_chat_logs"
        ordering = ["-created_at"]
        verbose_name = "AI Chat Log"
        verbose_name_plural = "AI Chat Logs"

    def __str__(self):
        return f"Chat — {self.user.username} in {self.lesson.title}"


# ------------------------------------------------------------------
# Intent Feedback Buffer — reviewed utterances queued for retraining
# ------------------------------------------------------------------
class IntentFeedbackBuffer(models.Model):
    """
    Dedicated store for utterances that have received user feedback.

    👍 rows are treated as confirmed training examples using the predicted
    intent as the label. 👎 rows enter a review queue; an admin may set
    ``corrected_intent`` to relabel them before retraining.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("used", "Used for Retraining"),
        ("relabelled", "Relabelled"),
    ]

    chat_log = models.OneToOneField(
        AIChatLog,
        on_delete=models.CASCADE,
        related_name="feedback_buffer_entry",
    )
    student_input = models.TextField()
    session_context = models.TextField(blank=True, default="")
    predicted_intent = models.CharField(max_length=30, choices=INTENT_CHOICES)
    confidence = models.FloatField(null=True, blank=True)
    feedback = models.CharField(max_length=16, choices=FEEDBACK_CHOICES)
    corrected_intent = models.CharField(
        max_length=30,
        choices=INTENT_CHOICES,
        null=True,
        blank=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "intent_feedback_buffer"
        ordering = ["-created_at"]
        verbose_name = "Intent Feedback Buffer Entry"
        verbose_name_plural = "Intent Feedback Buffer Entries"

    def __str__(self):
        return f"{self.feedback} — {self.predicted_intent} ({self.status})"

    def clean(self):
        if self.feedback == "thumbs_down" and self.corrected_intent:
            if self.corrected_intent == self.predicted_intent:
                raise ValidationError(
                    "Corrected intent must differ from the originally predicted intent."
                )

    def effective_label(self):
        """Return the label that should be used for training."""
        return self.corrected_intent or self.predicted_intent


# ------------------------------------------------------------------
# Intent Retraining Counter — tracks reviews since last retrain
# ------------------------------------------------------------------
class IntentRetrainingCounter(models.Model):
    """
    Singleton-style counter that triggers drift-aware retraining.

    Only one row should exist. ``reviews_since_last_train`` is incremented
    every time a user submits feedback on a chat log. When it reaches
    ``threshold``, the management command ``check_intent_retraining`` runs
    the retraining pipeline.
    """

    reviews_since_last_train = models.PositiveIntegerField(default=0)
    threshold = models.PositiveIntegerField(default=50)
    last_trained_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "intent_retraining_counter"
        verbose_name = "Intent Retraining Counter"
        verbose_name_plural = "Intent Retraining Counter"

    def __str__(self):
        return f"{self.reviews_since_last_train}/{self.threshold} reviews"

    def save(self, *args, **kwargs):
        # Enforce singleton behaviour
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        """Return the singleton counter row, creating it if necessary."""
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"threshold": 50})
        return obj

    @classmethod
    def increment(cls):
        """Increment reviews_since_last_train and return the counter."""
        counter = cls.get()
        counter.reviews_since_last_train += 1
        counter.save(update_fields=["reviews_since_last_train"])
        return counter

    @classmethod
    def reset(cls):
        """Reset after a successful retraining run."""
        from django.utils import timezone

        counter = cls.get()
        counter.reviews_since_last_train = 0
        counter.last_trained_at = timezone.now()
        counter.save(update_fields=["reviews_since_last_train", "last_trained_at"])
        return counter

    def threshold_reached(self):
        return self.reviews_since_last_train >= self.threshold


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

    class Meta:
        db_table = "student_learning_profiles"
        verbose_name = "Student Learning Profile"
        verbose_name_plural = "Student Learning Profiles"

    def __str__(self):
        return f"Learning Profile — {self.student.username} ({self.sessions_count} sessions)"
