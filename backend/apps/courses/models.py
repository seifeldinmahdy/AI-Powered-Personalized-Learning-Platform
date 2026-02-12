from django.db import models
from django.conf import settings


class Course(models.Model):
    """A learning course."""

    DIFFICULTY_CHOICES = [
        ("beginner", "Beginner"),
        ("intermediate", "Intermediate"),
        ("advanced", "Advanced"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses_taught",
    )
    difficulty = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default="beginner"
    )
    tags = models.JSONField(default=list, blank=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "courses"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Enrollment(models.Model):
    """Tracks which students are enrolled in which courses."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    progress = models.FloatField(default=0.0)  # 0.0 – 100.0
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "enrollments"
        unique_together = ["student", "course"]

    def __str__(self):
        return f"{self.student.username} → {self.course.title}"
