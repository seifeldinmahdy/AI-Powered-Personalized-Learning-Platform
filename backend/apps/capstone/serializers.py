from rest_framework import serializers
from .models import (
    Capstone, CapstoneRubricItem, CapstoneProposal, CapstoneSubmission,
    Team, MatchmakingQueueEntry, CapstoneAssistQuota,
)


class CapstoneRubricItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapstoneRubricItem
        fields = [
            "id", "text", "checks", "category", "clo", "concept",
            "weight", "min_team_size", "order",
        ]


class CapstoneSerializer(serializers.ModelSerializer):
    rubric_items = CapstoneRubricItemSerializer(many=True, read_only=True)

    class Meta:
        model = Capstone
        fields = [
            "id", "course", "title", "spec_mode", "team_mode", "team_cap",
            "language", "deadline", "status", "brief_text", "github_template_repo",
            "run_command", "ci_workflow", "rubric_items", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        """Enforce coherent team config (the issue: solo capstones could carry a
        cap > 1, team capstones a cap < 2). Solo silently normalizes to 1; team
        must be at least 2 (an explicit error so the admin fixes the form)."""
        def _cur(field, default):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, default)

        team_mode = _cur("team_mode", "solo")
        team_cap = _cur("team_cap", 1)
        if team_mode == "solo":
            attrs["team_cap"] = 1
        elif team_mode == "team" and (team_cap or 0) < 2:
            raise serializers.ValidationError(
                {"team_cap": "Team capstones need a team cap of at least 2."}
            )
        return attrs


class CapstoneProposalSerializer(serializers.ModelSerializer):
    student_username = serializers.CharField(source="student.username", read_only=True)
    agreed_member_ids = serializers.SerializerMethodField()
    fully_agreed = serializers.SerializerMethodField()

    class Meta:
        model = CapstoneProposal
        fields = [
            "id", "capstone", "student", "student_username", "team", "title",
            "description", "planned_features", "approval_status",
            "admin_feedback", "confidence_score", "submitted_at", "reviewed_at",
            "agreed_member_ids", "fully_agreed",
        ]
        read_only_fields = [
            "student", "team", "approval_status", "confidence_score",
            "submitted_at", "reviewed_at",
        ]

    def get_agreed_member_ids(self, obj):
        return list(obj.agreed_members.values_list("id", flat=True))

    def get_fully_agreed(self, obj):
        """A solo proposal is trivially agreed; a team proposal needs every member."""
        if not obj.team_id:
            return True
        member_ids = set(obj.team.members.values_list("id", flat=True))
        agreed_ids = set(obj.agreed_members.values_list("id", flat=True))
        return bool(member_ids) and member_ids <= agreed_ids


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
    confirmed_member_ids = serializers.SerializerMethodField()
    awaiting_confirmation = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id", "capstone", "name", "members", "member_usernames",
            "confirmed_member_ids", "awaiting_confirmation",
            "status", "repo_url", "branch", "created_at",
        ]
        read_only_fields = ["status", "repo_url", "branch", "created_at"]

    def get_member_usernames(self, obj):
        return [u.username for u in obj.members.all()]

    def get_confirmed_member_ids(self, obj):
        return list(obj.confirmed_members.values_list("id", flat=True))

    def get_awaiting_confirmation(self, obj):
        """Usernames of members who haven't yet accepted a proposed ('forming') team."""
        if obj.status != "forming":
            return []
        confirmed = set(obj.confirmed_members.values_list("id", flat=True))
        return [u.username for u in obj.members.all() if u.id not in confirmed]


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
