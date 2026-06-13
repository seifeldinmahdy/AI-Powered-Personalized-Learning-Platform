from django.contrib import admin
from django import forms
from .models import (
    Course, Module, Lesson, Slide, CodeChallenge, Enrollment,
    CourseCorpus, CorpusSource,
)


class CourseAdminForm(forms.ModelForm):
    """Use plain Textarea for JSONFields to avoid Django 4.2 admin widget bug."""
    syllabus = forms.CharField(widget=forms.Textarea(attrs={"rows": 4, "cols": 60}), required=False)
    tags = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "cols": 60}), required=False)

    class Meta:
        model = Course
        fields = "__all__"

    def clean_syllabus(self):
        import json
        value = self.cleaned_data.get("syllabus", "[]")
        if not value:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise forms.ValidationError("Enter valid JSON (e.g. [\"topic1\", \"topic2\"]).")

    def clean_tags(self):
        import json
        value = self.cleaned_data.get("tags", "[]")
        if not value:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise forms.ValidationError("Enter valid JSON (e.g. [\"tag1\", \"tag2\"]).")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    """Admin configuration for the Course model."""

    form = CourseAdminForm
    list_display = ("title", "difficulty", "status", "is_published", "price", "created_at")
    list_filter = ("difficulty", "status", "is_published")
    search_fields = ("title", "description")


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    ordering = ["lesson_order"]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "module_order")
    list_filter = ("course",)
    ordering = ["course", "module_order"]
    inlines = [LessonInline]


class SlideInline(admin.TabularInline):
    model = Slide
    extra = 0
    ordering = ["slide_order"]


class CodeChallengeInline(admin.StackedInline):
    model = CodeChallenge
    extra = 0


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "module", "lesson_order")
    list_filter = ("module__course",)
    ordering = ["module", "lesson_order"]
    inlines = [SlideInline, CodeChallengeInline]


@admin.register(Slide)
class SlideAdmin(admin.ModelAdmin):
    list_display = ("lesson", "slide_order")
    list_filter = ("lesson__module__course",)


@admin.register(CodeChallenge)
class CodeChallengeAdmin(admin.ModelAdmin):
    list_display = ("lesson", "problem_text")
    search_fields = ("problem_text",)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    """Admin configuration for the Enrollment model."""

    list_display = ("student", "course", "progress_percentage", "current_score", "is_paid", "enrolled_at")
    list_filter = ("course", "is_paid")
    search_fields = ("student__username", "course__title")


class CorpusSourceInline(admin.TabularInline):
    model = CorpusSource
    extra = 0


@admin.register(CourseCorpus)
class CourseCorpusAdmin(admin.ModelAdmin):
    list_display = ("course", "corpus_id", "name", "created_at")
    search_fields = ("course__title", "corpus_id")
    readonly_fields = ("corpus_id",)
    inlines = [CorpusSourceInline]


@admin.register(CorpusSource)
class CorpusSourceAdmin(admin.ModelAdmin):
    list_display = ("title", "book_stem", "corpus", "source_type", "is_active", "added_at")
    list_filter = ("source_type", "is_active")
    search_fields = ("title", "book_stem", "corpus__course__title")
