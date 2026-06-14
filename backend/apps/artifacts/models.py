"""
Durable storage backbone for generated learning artifacts (Batch 10a).

Replaces the AI service's local JSON files with a queryable, transactional
Postgres store. Two-part design throughout:

  - INDEX rows (this module) are the source of truth for existence/metadata and
    drive every UI/resume query. They are scanned and filtered.
  - CONTENT is the JSON bytes, carried inline in a JSONB ``content_json`` column
    for now. A nullable ``storage_key`` + the ``content_ref`` accessor are
    reserved so content can later move to an object store WITHOUT touching the
    index or the resume queries. (Decision: no object storage this batch — blobs
    are small structured JSON.)

Events vs snapshots:
  - PlacementAttempt and ProblemSetAttempt are EVENTS: append-only, immutable.
    A re-take / retry is a NEW row; derived state (the student-context snapshot,
    the best score) is RECOMPUTED, never overwritten in place.
  - ProblemSet / StudentArtifact are INDEX rows for generated content.

plan_version note: the authoritative plan version lives in the course_pathway
SQLite store (no cross-DB FK). We treat ``plan_version`` as an opaque int here;
the AI service validates it against known versions at the write boundary and
logs mismatches (it must never be silently coerced to "current").
"""

from django.conf import settings
from django.db import models


class PlacementAttempt(models.Model):
    """EVENT (append-only, immutable): one row per placement-test submission.

    A re-take is a NEW row. The derived UnifiedStudentContext / profile is a
    SNAPSHOT recomputed from the LATEST attempt — this row is never mutated.
    """

    enrollment = models.ForeignKey(
        "courses.Enrollment", on_delete=models.CASCADE, related_name="placement_attempts"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="placement_attempts"
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="placement_attempts"
    )
    # Full submitted answers, exactly as received (audit + recompute).
    answers = models.JSONField(default=list)
    # Per-question correctness: [{question, chosen_option, correct_option, is_correct, concept_id}]
    per_question = models.JSONField(default=list)
    score = models.IntegerField(default=0)  # overall score_pct
    # Concept-keyed results: {concept_id: score_0_1}
    concept_results = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "artifact_placement_attempts"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["enrollment", "-created_at"])]

    def __str__(self):
        return f"PlacementAttempt(student={self.student_id} course={self.course_id} score={self.score})"


class StudentArtifact(models.Model):
    """INDEX row for a generated artifact whose content is inline JSONB.

    Used for slides (keyed by session_number) and labs (keyed by lesson).
    Problem sets are modeled separately (ProblemSet) because they additionally
    need append-only attempts, a regeneration counter, and supersession.
    """

    SLIDES = "slides"
    LAB = "lab"
    ARTIFACT_TYPES = [(SLIDES, "Slides"), (LAB, "Lab")]

    STATUS_CHOICES = [
        ("generated", "Generated"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
    ]

    enrollment = models.ForeignKey(
        "courses.Enrollment", on_delete=models.CASCADE, related_name="artifacts"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="artifacts"
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="artifacts"
    )
    artifact_type = models.CharField(max_length=20, choices=ARTIFACT_TYPES)
    session_number = models.IntegerField(null=True, blank=True)  # slides
    lesson = models.ForeignKey(
        "courses.Lesson", null=True, blank=True, on_delete=models.CASCADE, related_name="artifacts"
    )
    plan_version = models.IntegerField()
    generation_index = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="generated")
    # CONTENT (inline for now). Exactly one of content_json / storage_key is the
    # live source; storage_key is reserved for a future object-store swap.
    content_json = models.JSONField(default=dict)
    storage_key = models.CharField(max_length=255, null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "artifact_student_artifacts"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "artifact_type", "session_number", "lesson",
                        "plan_version", "generation_index"],
                name="uniq_student_artifact_key",
            )
        ]
        indexes = [
            models.Index(fields=["enrollment", "artifact_type", "plan_version"]),
        ]

    def __str__(self):
        return (f"StudentArtifact({self.artifact_type} student={self.student_id} "
                f"session={self.session_number} lesson={self.lesson_id} v{self.plan_version})")

    @property
    def content_ref(self):
        """Resolve content regardless of where it lives. Today: inline JSONB.

        When content later moves to an object store, this is the ONE place that
        learns to fetch by storage_key — the index and resume queries don't change.
        """
        return self.content_json


class ProblemSet(models.Model):
    """INDEX row for one generated problem set (a generation).

    Keyed by (enrollment, lesson, plan_version, generation_index). A student
    regeneration creates generation_index+1 and marks the prior one superseded;
    the prior set and ALL its attempts are RETAINED (audit + mastery provenance).
    """

    enrollment = models.ForeignKey(
        "courses.Enrollment", on_delete=models.CASCADE, related_name="problem_sets"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="problem_sets"
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="problem_sets"
    )
    lesson = models.ForeignKey(
        "courses.Lesson", on_delete=models.CASCADE, related_name="problem_sets"
    )
    plan_version = models.IntegerField()
    generation_index = models.IntegerField(default=0)
    # The AI service's problem_set_id (uuid) — submit resolves the set by this.
    ps_uid = models.CharField(max_length=64, unique=True)
    # CONTENT: the generated questions + rubric (no submissions; those are attempts).
    content_json = models.JSONField(default=dict)
    storage_key = models.CharField(max_length=255, null=True, blank=True)
    # Mutable per-question working state for in-progress hint reveals (deductions
    # + revealed hints), keyed by question_id. This is NOT an attempt — it is the
    # pre-submission scratch the evaluator reads to apply hint penalties. Lets the
    # submit hot path do one GET (content + hint_tracking + generation) + one POST.
    hint_tracking = models.JSONField(default=dict)
    # Marks "not the active generation" (a newer generation_index exists). The
    # set is RETAINED; it still counts for best-score and mastery audit.
    superseded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "artifact_problem_sets"
        ordering = ["enrollment_id", "lesson_id", "generation_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "lesson", "plan_version", "generation_index"],
                name="uniq_problem_set_generation",
            )
        ]
        indexes = [
            models.Index(fields=["enrollment", "lesson", "plan_version"]),
        ]

    def __str__(self):
        return (f"ProblemSet(student={self.student_id} lesson={self.lesson_id} "
                f"v{self.plan_version} gen{self.generation_index})")

    @property
    def content_ref(self):
        return self.content_json


class ProblemSetAttempt(models.Model):
    """EVENT (append-only, immutable): one row per question submission.

    A retry is a NEW row; an attempt is NEVER overwritten. ``source`` records the
    generation context so mastery can down-weight regenerated-set attempts and so
    imported history can be excluded from re-folding.
    """

    ORIGINAL = "original"
    REGENERATED = "regenerated"
    IMPORTED = "imported"
    SOURCE_CHOICES = [(ORIGINAL, "Original"), (REGENERATED, "Regenerated"), (IMPORTED, "Imported")]

    problem_set = models.ForeignKey(
        ProblemSet, on_delete=models.CASCADE, related_name="attempts"
    )
    question_id = models.CharField(max_length=64)
    code = models.TextField(blank=True, default="")
    # Evaluated rubric: per-check {id, result(bool), evidence, ...}
    evaluated_rubric = models.JSONField(default=list)
    hints_used = models.IntegerField(default=0)
    score = models.IntegerField(default=0)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=ORIGINAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "artifact_problem_set_attempts"
        ordering = ["created_at", "id"]  # submission order — the mastery trajectory
        indexes = [
            models.Index(fields=["problem_set", "question_id", "created_at"]),
        ]

    def __str__(self):
        return f"ProblemSetAttempt(ps={self.problem_set_id} q={self.question_id} score={self.score})"
