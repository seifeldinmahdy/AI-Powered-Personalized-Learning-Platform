from rest_framework import serializers
from .models import Course, Module, Lesson, Slide, CodeChallenge, Enrollment, CourseRating


class CourseSerializer(serializers.ModelSerializer):
    instructor_name = serializers.ReadOnlyField(source="instructor.username")
    total_lessons_count = serializers.SerializerMethodField()

    def get_total_lessons_count(self, obj):
        from .models import Lesson
        return Lesson.objects.filter(module__course=obj).count()

    class Meta:
        model = Course
        fields = [
            "id", "title", "description", "instructor", "instructor_name",
            "difficulty", "status", "tags", "is_published", "price",
            "total_lessons_count", "avg_rating", "created_at", "syllabus",
        ]
        read_only_fields = ["id", "created_at"]


class ModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["id", "course", "title", "module_order"]
        read_only_fields = ["id"]


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ["id", "module", "title", "lesson_order"]
        read_only_fields = ["id"]


class SlideSerializer(serializers.ModelSerializer):
    class Meta:
        model = Slide
        fields = ["id", "lesson", "content_json", "slide_order"]
        read_only_fields = ["id"]


class CodeChallengeSerializer(serializers.ModelSerializer):
    """Full serializer for admin/instructor use."""
    class Meta:
        model = CodeChallenge
        fields = ["id", "lesson", "problem_text", "starter_code", "solution_code", "test_cases_json", "hint_text"]
        read_only_fields = ["id"]


class CodeChallengeStudentSerializer(serializers.ModelSerializer):
    """Safe serializer for students — hides solution_code and test_cases_json."""
    class Meta:
        model = CodeChallenge
        fields = ["id", "lesson", "problem_text", "starter_code", "hint_text"]
        read_only_fields = ["id"]


class LessonDetailSerializer(serializers.ModelSerializer):
    """Lesson with nested slides and code challenges (read-only detail view)."""
    slides = SlideSerializer(many=True, read_only=True)
    code_challenges = CodeChallengeStudentSerializer(many=True, read_only=True)

    class Meta:
        model = Lesson
        fields = ["id", "module", "title", "lesson_order", "slides", "code_challenges"]
        read_only_fields = ["id"]


class CourseRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseRating
        fields = ["id", "course", "student", "rating", "created_at"]
        read_only_fields = ["id", "student", "created_at"]


class EnrollmentSerializer(serializers.ModelSerializer):
    course_title = serializers.ReadOnlyField(source="course.title")

    class Meta:
        model = Enrollment
        fields = [
            "id", "student", "course", "course_title",
            "current_lesson", "progress_percentage", "current_score",
            "placement_score", "current_pathway", "is_pathway_ready",
            "is_assessment_started", "is_paid", "enrolled_at", "last_accessed",
        ]
        read_only_fields = ["id", "student", "enrolled_at", "last_accessed"]
