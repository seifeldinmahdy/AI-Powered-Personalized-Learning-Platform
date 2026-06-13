from rest_framework import serializers
from .models import (
    Capstone, CapstoneRubricItem, CapstoneProposal, CapstoneSubmission,
    Team, MatchmakingQueueEntry, CapstoneAssistQuota,
)


class CapstoneRubricItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapstoneRubricItem
        fields = [
            "id", "text", "category", "clo", "concept",
            "weight", "min_team_size", "order",
        ]


class CapstoneSerializer(serializers.ModelSerializer):
    rubric_items = CapstoneRubricItemSerializer(many=True, read_only=True)

    class Meta:
        model = Capstone
        fields = [
            "id", "course", "title", "spec_mode", "team_mode", "team_cap",
            "deadline", "status", "brief_text", "github_template_repo",
            "run_command", "rubric_items", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class CapstoneProposalSerializer(serializers.ModelSerializer):
    student_username = serializers.CharField(source="student.username", read_only=True)

    class Meta:
        model = CapstoneProposal
        fields = [
            "id", "capstone", "student", "student_username", "title",
            "description", "planned_features", "approval_status",
            "admin_feedback", "confidence_score", "submitted_at", "reviewed_at",
        ]
        read_only_fields = [
            "student", "approval_status", "confidence_score",
            "submitted_at", "reviewed_at",
        ]


class CapstoneSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapstoneSubmission
        fields = [
            "id", "capstone", "enrollment", "proposal", "team", "repo_url",
            "branch", "latest_commit_sha", "github_username", "results", "score",
            "verdict", "feedback", "contributions", "status",
            "submitted_at", "evaluated_at",
        ]
        read_only_fields = [
            "results", "score", "verdict", "feedback", "contributions", "status",
            "submitted_at", "evaluated_at",
        ]


class TeamSerializer(serializers.ModelSerializer):
    member_usernames = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id", "capstone", "name", "members", "member_usernames",
            "status", "created_at",
        ]
        read_only_fields = ["status", "created_at"]

    def get_member_usernames(self, obj):
        return [u.username for u in obj.members.all()]


class MatchmakingQueueEntrySerializer(serializers.ModelSerializer):
    student_username = serializers.CharField(source="student.username", read_only=True)

    class Meta:
        model = MatchmakingQueueEntry
        fields = [
            "id", "capstone", "student", "student_username", "status",
            "fill_window_expires_at", "team", "joined_at",
        ]
        read_only_fields = [
            "student", "status", "fill_window_expires_at", "team", "joined_at",
        ]


class CapstoneAssistQuotaSerializer(serializers.ModelSerializer):
    remaining = serializers.IntegerField(read_only=True)

    class Meta:
        model = CapstoneAssistQuota
        fields = [
            "id", "capstone", "student", "team", "period",
            "used", "limit", "remaining", "period_start",
        ]
        read_only_fields = ["used", "period_start"]
