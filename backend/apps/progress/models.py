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
    # One-shot idempotency latch for the gamification signal: XP/streak/progress
    # are awarded exactly once, the first time this completion transitions to
    # "Completed". Set by the signal via .update() (never re-triggers post_save).
    gamification_awarded = models.BooleanField(default=False)

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
    # Optimistic-concurrency counter for profile writes. Bumped by the single
    # writer (apps.progress.profile_service.apply_claims) on every applied update.
    profile_version = models.IntegerField(default=0)
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


# ------------------------------------------------------------------
# ConceptMasteryEvent — append-only event log; mastery is a fold over it.
# This is the source of truth. ``StudentLearningProfile.concept_mastery`` is a
# derived read-model recomputed from these events by the single writer
# (apps.progress.mastery_service). Append-only ⇒ concurrent writes never
# conflict; full per-concept history ⇒ explainability ("why did it move").
# ------------------------------------------------------------------
class ConceptMasteryEvent(models.Model):
    SOURCE_CHOICES = [
        ("assessment", "Placement assessment"),
        ("checkpoint", "In-session MCQ checkpoint"),
        ("problem_set", "Problem set"),
        ("capstone_grade", "Capstone grade"),
        ("capstone_assist", "Capstone assist penalty"),
        ("backfill", "Migration backfill seed"),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="concept_mastery_events",
    )
    concept_id = models.CharField(
        max_length=64,
        help_text="Django Concept.id (string) — matches concept_mastery projection keys.",
    )
    outcome = models.FloatField(help_text="Observed outcome 0.0–1.0 (fail→pass).")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    alpha = models.FloatField(
        default=0.3,
        help_text="Per-event EMA weight. Lets callers (e.g. Batch 10) down-weight "
                  "an update without the mastery code knowing why.",
    )
    evidence_delta = models.IntegerField(
        default=1,
        help_text="How much independent evidence this event contributes. "
                  "0 for assist penalties (not new independent demonstration); "
                  "for backfill seeds, the prior evidence count.",
    )
    mistake_tag = models.CharField(max_length=120, blank=True, default="")
    # Backfill seeds carry the FULL pre-migration entry ({linked_mistakes, trend})
    # so the fold round-trips the projection exactly. Normal events leave this null.
    seed_meta = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "concept_mastery_events"
        indexes = [
            models.Index(fields=["student", "concept_id", "created_at", "id"]),
        ]
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.student_id}/{self.concept_id} {self.source} {self.outcome} (a={self.alpha})"


class RemediationStep(models.Model):
    """Post-generation adaptivity (Batch 11a): a review step inserted when a
    concept's event-sourced mastery drops below the trigger threshold.

    This is an OVERLAY adjacent to the pathway — it never mutates the (immutable,
    versioned) plan and never changes plan_version. It references the CURRENT
    plan_version + the weak concept; the resume timeline positions it after the
    session that teaches that concept. Append-only in spirit: it auto-resolves
    only when mastery recovers (the review action itself never resolves it).

    Bounding: a partial unique constraint allows at most ONE 'pending' step per
    (enrollment, plan_version, concept), so a drop inserts exactly one and
    further events while still below insert none. A new downward crossing after
    recovery yields a new step.
    """

    PENDING = "pending"
    RESOLVED = "resolved"
    STATUS_CHOICES = [(PENDING, "Pending"), (RESOLVED, "Resolved")]

    enrollment = models.ForeignKey(
        "courses.Enrollment", on_delete=models.CASCADE, related_name="remediation_steps"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="remediation_steps"
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="remediation_steps"
    )
    concept = models.ForeignKey(
        "courses.Concept", on_delete=models.CASCADE, related_name="remediation_steps"
    )
    plan_version = models.IntegerField()
    kind = models.CharField(max_length=20, default="review")
    trigger_threshold = models.FloatField()
    score_at_trigger = models.FloatField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "remediation_steps"
        ordering = ["-created_at"]
        constraints = [
            # At most one OPEN remediation per (enrollment, plan_version, concept).
            models.UniqueConstraint(
                fields=["enrollment", "plan_version", "concept"],
                condition=models.Q(status="pending"),
                name="uniq_open_remediation_per_concept",
            )
        ]
        indexes = [
            models.Index(fields=["enrollment", "plan_version", "status"]),
        ]

    def __str__(self):
        return f"Remediation(student={self.student_id} concept={self.concept_id} {self.status})"


class EmotionConsent(models.Model):
    """Per-student consent for webcam/FER emotion capture (Batch 11b).

    OFF by default (no row, or granted=False = no consent). Capture requires
    explicit, informed opt-in; consent is revocable and withdrawal stops capture
    immediately and purges retained raw emotion. Emotion is auxiliary only — it
    never affects grades.
    """

    student = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="emotion_consent"
    )
    granted = models.BooleanField(default=False)
    granted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    # The consent-text version the student agreed to (audit trail).
    policy_version = models.CharField(max_length=40, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "emotion_consent"

    def __str__(self):
        return f"EmotionConsent(student={self.student_id} granted={self.granted})"
