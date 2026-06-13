import uuid

from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.conf import settings


def _new_corpus_id() -> str:
    """Generate a stable, opaque corpus identifier.

    Deliberately NOT derived from course_id/title/book — the whole point of the
    corpus refactor is to stop overloading those strings as retrieval scope.
    """
    return uuid.uuid4().hex


class Course(models.Model):
    """
    Represents a learning course on the platform.

    Stores the course metadata, its syllabus (as a structured JSON list
    of topics), and management fields like difficulty and publication status.
    """

    DIFFICULTY_CHOICES = [
        ("Beginner", "Beginner"),
        ("Intermediate", "Intermediate"),
        ("Advanced", "Advanced"),
    ]

    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Published", "Published"),
        ("Archived", "Archived"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    syllabus = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered list of topics/modules for this course.",
    )
    difficulty = models.CharField(
        max_length=50, choices=DIFFICULTY_CHOICES, default="Beginner"
    )
    status = models.CharField(
        max_length=50, choices=STATUS_CHOICES, default="Draft"
    )
    tags = models.JSONField(default=list, blank=True)
    is_published = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_lessons_count = models.IntegerField(default=0)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "courses"
        ordering = ["-created_at"]
        verbose_name = "Course"
        verbose_name_plural = "Courses"

    def __str__(self):
        return self.title


# ------------------------------------------------------------------
# Module — ordered grouping of lessons within a course
# ------------------------------------------------------------------
class Module(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="modules",
    )
    title = models.CharField(max_length=200)
    module_order = models.IntegerField()

    class Meta:
        db_table = "modules"
        ordering = ["module_order"]
        verbose_name = "Module"
        verbose_name_plural = "Modules"

    def __str__(self):
        return f"{self.course.title} → {self.title}"


# ------------------------------------------------------------------
# Lesson — individual learning unit within a module
# ------------------------------------------------------------------
class Lesson(models.Model):
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    title = models.CharField(max_length=200)
    lesson_order = models.IntegerField()

    class Meta:
        db_table = "lessons"
        ordering = ["lesson_order"]
        verbose_name = "Lesson"
        verbose_name_plural = "Lessons"

    def __str__(self):
        return f"{self.module.title} → {self.title}"


# ------------------------------------------------------------------
# Slide — slide-based content within a lesson (JSONB)
# ------------------------------------------------------------------
class Slide(models.Model):
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="slides",
    )
    content_json = models.JSONField(
        help_text="Slide content stored as structured JSON."
    )
    slide_order = models.IntegerField()

    class Meta:
        db_table = "slides"
        ordering = ["slide_order"]
        verbose_name = "Slide"
        verbose_name_plural = "Slides"

    def __str__(self):
        return f"Slide {self.slide_order} of {self.lesson.title}"


# ------------------------------------------------------------------
# Code Challenge — coding exercise attached to a lesson
# ------------------------------------------------------------------
class CodeChallenge(models.Model):
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="code_challenges",
    )
    problem_text = models.TextField()
    starter_code = models.TextField(blank=True, default="")
    solution_code = models.TextField()
    test_cases_json = models.JSONField(
        blank=True,
        null=True,
        help_text="Structured test cases as JSON."
    )
    hint_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "code_challenges"
        verbose_name = "Code Challenge"
        verbose_name_plural = "Code Challenges"

    def __str__(self):
        return f"Challenge for {self.lesson.title}"


# ------------------------------------------------------------------
# Enrollment — tracks a student's enrollment in a course (merged)
# ------------------------------------------------------------------
class Enrollment(models.Model):
    """
    Tracks a student's enrollment in a course.

    Stores the placement quiz score, the AI-generated personalized
    learning pathway, and overall progress through the course.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    current_lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_enrollments",
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    placement_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Score from the initial placement quiz (0.0 – 100.0).",
    )
    current_pathway = models.JSONField(
        default=dict,
        blank=True,
        help_text="The AI-generated personalized learning pathway.",
    )
    progress_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Overall course completion percentage (0.00 – 100.00).",
    )
    current_score = models.IntegerField(default=0)
    is_paid = models.BooleanField(default=False)
    is_pathway_ready = models.BooleanField(default=False)
    is_assessment_started = models.BooleanField(default=False)
    # Set once the course is genuinely complete: material at 100% for courses
    # without a capstone, or a PASSED capstone for courses that have one. Drives
    # the survey trigger and certificate date. See apps.courses.completion.
    completed_at = models.DateTimeField(null=True, blank=True)
    last_accessed = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "enrollments"
        unique_together = ["student", "course"]
        verbose_name = "Enrollment"
        verbose_name_plural = "Enrollments"

    def __str__(self):
        return f"{self.student.username} → {self.course.title} ({self.progress_percentage}%)"


class CourseRating(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="ratings")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "course_ratings"
        unique_together = ("course", "student")

    def __str__(self):
        return f"{self.student.username} → {self.course.title}: {self.rating}★"


# ------------------------------------------------------------------
# Concept — atomic learning unit within a course (shallow tree)
# ------------------------------------------------------------------
class Concept(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="concepts")
    label = models.CharField(max_length=200)
    slug = models.SlugField(max_length=60)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    lessons = models.ManyToManyField(Lesson, blank=True, related_name="concepts")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "concepts"
        ordering = ["order"]
        unique_together = [["course", "slug"]]
        verbose_name = "Concept"
        verbose_name_plural = "Concepts"

    def __str__(self):
        return f"{self.course.title} — {self.label}"


# ------------------------------------------------------------------
# CourseCorpus — the admin-defined source material bound to a course
# ------------------------------------------------------------------
class CourseCorpus(models.Model):
    """One explicit, admin-curated corpus per course.

    ``corpus_id`` is the STABLE retrieval scope used by the vector store and the
    RetrievalService. It is generated independently of the Django course_id /
    title / book filename so retrieval scope is never an overloaded string.
    Exactly one corpus exists per course (auto-created via signal).
    """

    course = models.OneToOneField(
        Course, on_delete=models.CASCADE, related_name="corpus",
    )
    corpus_id = models.CharField(
        max_length=64, unique=True, editable=False, default=_new_corpus_id,
        help_text="Stable, opaque retrieval scope key. Never changes.",
    )
    name = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "course_corpora"
        verbose_name = "Course Corpus"
        verbose_name_plural = "Course Corpora"

    def __str__(self):
        return f"Corpus[{self.corpus_id[:8]}] for {self.course.title}"


class CorpusSource(models.Model):
    """A single source material (book/doc/url) bound to a course's corpus.

    ``book_stem`` is the ingestion key — it must equal the ChromaDB ``book``
    metadata value produced by the indexer for this source, so the backfill can
    map existing vectors to this corpus.
    """

    SOURCE_TYPES = [
        ("pdf", "PDF"),
        ("doc", "Document"),
        ("url", "URL"),
    ]

    corpus = models.ForeignKey(
        CourseCorpus, on_delete=models.CASCADE, related_name="sources",
    )
    title = models.CharField(max_length=300)
    book_stem = models.CharField(
        max_length=200,
        help_text="Ingestion key; must match the ChromaDB 'book' value for this source.",
    )
    source_type = models.CharField(max_length=10, choices=SOURCE_TYPES, default="pdf")
    concept = models.ForeignKey(
        Concept, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="corpus_sources",
        help_text="Optional concept binding. Batch 4 makes concept tagging non-optional.",
    )
    is_active = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "corpus_sources"
        unique_together = [["corpus", "book_stem"]]
        ordering = ["added_at"]
        verbose_name = "Corpus Source"
        verbose_name_plural = "Corpus Sources"

    def __str__(self):
        return f"{self.title} ({self.book_stem})"


# ------------------------------------------------------------------
# CourseLearningOutcome — measurable outcome for a course (CLO)
# ------------------------------------------------------------------
class CourseLearningOutcome(models.Model):
    BLOOM_CHOICES = [
        ("remember", "Remember"),
        ("understand", "Understand"),
        ("apply", "Apply"),
        ("analyze", "Analyze"),
        ("evaluate", "Evaluate"),
        ("create", "Create"),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="clos")
    code = models.CharField(max_length=20, help_text="E.g. CLO1, CLO2")
    text = models.TextField()
    bloom_level = models.CharField(max_length=20, choices=BLOOM_CHOICES, blank=True)
    concepts = models.ManyToManyField(Concept, blank=True, related_name="clos")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "course_learning_outcomes"
        ordering = ["order"]
        unique_together = [["course", "code"]]
        verbose_name = "Course Learning Outcome"
        verbose_name_plural = "Course Learning Outcomes"

    def __str__(self):
        return f"{self.course.title} — {self.code}"
