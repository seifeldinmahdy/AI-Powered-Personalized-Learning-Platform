from rest_framework import serializers
from .models import (
    LessonCompletion, SystemActivityLog, AIChatLog,
    StudentLearningProfile,
)


class LessonCompletionSerializer(serializers.ModelSerializer):
    lesson_title = serializers.ReadOnlyField(source="lesson.title")

    class Meta:
        model = LessonCompletion
        fields = [
            "id", "enrollment", "lesson", "lesson_title",
            "status", "score", "completed_at",
        ]
        read_only_fields = ["id", "completed_at"]


class SystemActivityLogSerializer(serializers.ModelSerializer):
    course_title = serializers.ReadOnlyField(source="target_course.title")

    class Meta:
        model = SystemActivityLog
        fields = ["id", "user", "action_type", "target_course", "course_title", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class AIChatLogSerializer(serializers.ModelSerializer):
    lesson_title = serializers.ReadOnlyField(source="lesson.title")

    class Meta:
        model = AIChatLog
        fields = [
            "id", "user", "lesson", "lesson_title",
            "user_audio_url", "transcript_text", "ai_response_text", "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]





class StudentLearningProfileSerializer(serializers.ModelSerializer):
    student_username = serializers.ReadOnlyField(source="student.username")

    class Meta:
        model = StudentLearningProfile
        fields = [
            "id", "student", "student_username",
            "last_updated", "sessions_count",
            "profile_summary", "profile_data",
        ]
        read_only_fields = ["id", "student", "last_updated"]
