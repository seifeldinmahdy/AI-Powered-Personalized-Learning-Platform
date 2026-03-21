from rest_framework import serializers
from .models import Achievement, UserAchievement, DailyStudyStats


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = ["id", "name", "description", "xp_reward", "icon_url"]
        read_only_fields = ["id"]


class UserAchievementSerializer(serializers.ModelSerializer):
    achievement = AchievementSerializer(read_only=True)

    class Meta:
        model = UserAchievement
        fields = ["id", "user", "achievement", "earned_at"]
        read_only_fields = ["id", "earned_at"]


class DailyStudyStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyStudyStats
        fields = ["id", "user", "study_date", "hours_spent"]
        read_only_fields = ["id", "user"]
