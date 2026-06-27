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

INTENT_DEFINITIONS = {
    "On-Topic Question": (
        "Asking about the current material — explanations, examples, or conceptual "
        "questions without a specific broken code artifact."
    ),
    "Off-Topic Question": (
        "Completely unrelated to the lesson or programming."
    ),
    "Emotional-State": (
        "Expressing a feeling or internal state such as frustration, confusion, "
        "excitement, boredom, or anxiety."
    ),
    "Pace-Related": (
        "Wants to change speed — slow down, speed up, skip, take a break, or ask "
        "about timing."
    ),
    "Repeat/clarification": (
        "Wants something repeated or explained again — signals like 'again', "
        "'repeat', 'missed', or 'go back'."
    ),
    "Debugging/Code-Sharing": (
        "Sharing a broken code artifact, error message, traceback, or asking for "
        "debugging help."
    ),
}

FEEDBACK_CHOICES = [
    ("thumbs_up", "👍 Thumbs Up"),
    ("thumbs_down", "👎 Thumbs Down"),
]


# ------------------------------------------------------------------
# Session Completion — tracks per-session progress within an enrollment
# ------------------------------------------------------------------
class SessionCompletion(models.Model):
    STATUS_CHOICES = [
        ("Started", "Started"),
        ("In Progress", "In Progress"),
        ("Completed", "Completed"),
    ]

    enrollment = models.ForeignKey(
        "courses.Enrollment",
        on_delete=models.CASCADE,
        related_name="session_completions",
    )
    session_number = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Started")
    score = models.IntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent_minutes = models.IntegerField(default=0)
    # One-shot idempotency latch for the gamification signal: XP/streak/progress
    # are awarded exactly once, the first time this completion transitions to
    # "Completed". Set by the signal via .update() (never re-triggers post_save).
    gamification_awarded = models.BooleanField(default=False)

    class Meta:
        db_table = "session_completions"
        unique_together = ["enrollment", "session_number"]
        ordering = ["-completed_at"]
        verbose_name = "Session Completion"
        verbose_name_plural = "Session Completions"

    def __str__(self):
        return f"{self.enrollment.student.username} — Session {self.session_number} ({self.status})"


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
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="ai_chat_logs",
    )
    session_number = models.IntegerField(default=1)
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
    corrected_intent = models.CharField(
        max_length=30,
        choices=INTENT_CHOICES,
        null=True,
        blank=True,
        db_index=True,
    )
    used_for_retraining = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "ai_chat_logs"
        ordering = ["-created_at"]
        verbose_name = "AI Chat Log"
        verbose_name_plural = "AI Chat Logs"

    def __str__(self):
        return f"Chat — {self.user.username} in {self.course.title} (Session {self.session_number})"


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
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )
    session_number = models.IntegerField(default=1)
    slide_index = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bookmarks"
        unique_together = ("user", "course", "session_number", "slide_index")
        ordering = ["-created_at"]

    def __str__(self):
        if self.slide_index is not None:
            return f"{self.user.username} bookmarked slide {self.slide_index} of Session {self.session_number}"
        return f"{self.user.username} bookmarked Session {self.session_number}"




# ------------------------------------------------------------------
# Student Learning Profile — rewrite-based persistent profile per student.
# Overwritten (not appended) after each session by the profiler LLM.
# LearnPal reads profile_summary at session start to personalize teaching.
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
            "This is what LearnPal reads at session start."
        ),
    )
    # Provenance of the current profile_summary: "session" = canonical (authored
    # by the session profiler, the single canonical author) or "provisional" = a
    # deterministic stopgap synthesized from claims until the first live session
    # completes. A provisional summary never overwrites a canonical one.
    profile_summary_source = models.CharField(max_length=20, blank=True, default="")
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
