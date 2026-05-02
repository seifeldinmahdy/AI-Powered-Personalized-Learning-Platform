from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.conf import settings


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
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses_taught",
        null=True,
        blank=True,
    )
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
