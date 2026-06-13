from django.db import models


class SurveyTemplate(models.Model):
    course = models.ForeignKey(
        "courses.Course", null=True, blank=True, on_delete=models.CASCADE,
        related_name="survey_templates",
    )
    title = models.CharField(max_length=200)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "survey_templates"
        verbose_name = "Survey Template"
        verbose_name_plural = "Survey Templates"

    def __str__(self):
        return self.title


class SurveyQuestion(models.Model):
    KIND_CHOICES = [
        ("likert", "Likert (1-5)"),
        ("text", "Free Text"),
        ("single", "Single Choice"),
        ("multi", "Multiple Choice"),
    ]

    template = models.ForeignKey(
        SurveyTemplate, on_delete=models.CASCADE, related_name="questions"
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    prompt = models.TextField()
    clo = models.ForeignKey(
        "courses.CourseLearningOutcome", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="survey_questions",
    )
    options = models.JSONField(default=list, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "survey_questions"
        ordering = ["order"]
        verbose_name = "Survey Question"
        verbose_name_plural = "Survey Questions"

    def __str__(self):
        return f"{self.template.title} — Q{self.order}: {self.prompt[:60]}"


class SurveyResponse(models.Model):
    enrollment = models.OneToOneField(
        "courses.Enrollment", on_delete=models.CASCADE, related_name="survey_response"
    )
    template = models.ForeignKey(
        SurveyTemplate, on_delete=models.CASCADE, related_name="responses"
    )
    answers = models.JSONField(help_text="Dict of {question_id: answer_value}.")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "survey_responses"
        verbose_name = "Survey Response"
        verbose_name_plural = "Survey Responses"

    def __str__(self):
        return f"Response — {self.enrollment.student.username} ({self.submitted_at.date()})"


class SurveySummary(models.Model):
    course = models.OneToOneField(
        "courses.Course", on_delete=models.CASCADE, related_name="survey_summary"
    )
    summary_json = models.JSONField(default=dict)
    response_count = models.IntegerField(default=0)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "survey_summaries"
        verbose_name = "Survey Summary"
        verbose_name_plural = "Survey Summaries"

    def __str__(self):
        return f"Summary — {self.course.title} ({self.response_count} responses)"
