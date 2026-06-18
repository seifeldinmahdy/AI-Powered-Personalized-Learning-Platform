from rest_framework import serializers

from .models import (
    SessionCompletion, SystemActivityLog, AIChatLog,
    StudentLearningProfile, Bookmark,
    IntentFeedbackBuffer, IntentRetrainingCounter,
)


class SessionCompletionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionCompletion
        fields = [
            "id", "enrollment", "session_number",
            "status", "score", "completed_at", "time_spent_minutes",
        ]
        read_only_fields = ["id", "completed_at"]


class SystemActivityLogSerializer(serializers.ModelSerializer):
    course_title = serializers.ReadOnlyField(source="target_course.title")

    class Meta:
        model = SystemActivityLog
        fields = ["id", "user", "action_type", "target_course", "course_title", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class AIChatLogSerializer(serializers.ModelSerializer):
    course_title = serializers.ReadOnlyField(source="course.title")

    class Meta:
        model = AIChatLog
        fields = [
            "id", "user", "course", "course_title", "session_number",
            "user_audio_url", "transcript_text", "ai_response_text", "created_at",
            "session_id", "session_context", "predicted_intent", "confidence",
            "intent_probabilities", "feedback", "feedback_at", "used_for_retraining",
        ]
        read_only_fields = [
            "id", "user", "created_at",
            "feedback", "feedback_at", "used_for_retraining",
        ]


class AIChatLogFeedbackSerializer(serializers.ModelSerializer):
    """Lightweight serializer for PATCH /chat-logs/<id>/feedback/."""

    class Meta:
        model = AIChatLog
        fields = ["feedback"]


class IntentFeedbackBufferSerializer(serializers.ModelSerializer):
    course_title = serializers.ReadOnlyField(source="chat_log.course.title")
    username = serializers.ReadOnlyField(source="chat_log.user.username")

    class Meta:
        model = IntentFeedbackBuffer
        fields = [
            "id", "chat_log", "username", "course_title",
            "student_input", "session_context", "predicted_intent",
            "confidence", "feedback", "corrected_intent", "status",
            "created_at", "used_at",
        ]
        read_only_fields = ["id", "created_at", "used_at"]


class IntentRetrainingCounterSerializer(serializers.ModelSerializer):
    threshold_reached = serializers.BooleanField(source="threshold_reached", read_only=True)

    class Meta:
        model = IntentRetrainingCounter
        fields = [
            "reviews_since_last_train", "threshold", "last_trained_at",
            "updated_at", "threshold_reached",
        ]
        read_only_fields = ["reviews_since_last_train", "last_trained_at", "updated_at"]


class BookmarkSerializer(serializers.ModelSerializer):
    course_title = serializers.ReadOnlyField(source="course.title")

    class Meta:
        model = Bookmark
        fields = ["id", "user", "course", "course_title", "session_number", "slide_index", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class StudentLearningProfileSerializer(serializers.ModelSerializer):
    student_username = serializers.ReadOnlyField(source="student.username")

    class Meta:
        model = StudentLearningProfile
        fields = [
            "id", "student", "student_username",
            "last_updated", "sessions_count",
            "profile_summary", "profile_data", "concept_mastery",
        ]
        read_only_fields = ["id", "student", "last_updated"]
