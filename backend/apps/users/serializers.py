from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from .models import User, StudentProfile, UserPreferences


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "bio", "created_at"]
        read_only_fields = ["id", "created_at"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(
        validators=[UniqueValidator(queryset=User.objects.all(), message="An account with this email already exists.")]
    )

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "role"]

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class StudentProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentProfile
        fields = [
            "id", "bio", "location", "timezone", "avatar_url",
            "level", "current_xp", "current_streak", "longest_streak",
            "total_minutes_learned", "daily_goal_minutes", "days_active",
            "messages_count",
        ]
        read_only_fields = ["id", "level", "current_xp", "current_streak",
                            "longest_streak", "days_active", "messages_count"]


class UserPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreferences
        fields = [
            "id", "email_notifications", "ai_tutor_voice_enabled",
            "study_reminders",
        ]
        read_only_fields = ["id"]
