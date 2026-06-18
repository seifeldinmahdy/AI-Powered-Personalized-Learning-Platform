from rest_framework import serializers

from .models import PlacementAttempt, StudentArtifact, ProblemSet, ProblemSetAttempt


class PlacementAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlacementAttempt
        fields = ["id", "enrollment", "student", "course", "answers", "per_question",
                  "score", "concept_results", "created_at"]
        read_only_fields = fields


class StudentArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentArtifact
        fields = ["id", "enrollment", "student", "course", "artifact_type",
                  "session_number", "plan_version", "generation_index",
                  "status", "content_json", "storage_key", "score",
                  "created_at", "updated_at", "completed_at"]
        read_only_fields = ["id", "enrollment", "student", "course", "created_at", "updated_at"]


class StudentArtifactIndexSerializer(serializers.ModelSerializer):
    """Index view — metadata only, no content (content is fetched by id)."""

    class Meta:
        model = StudentArtifact
        fields = ["id", "artifact_type", "session_number", "plan_version",
                  "generation_index", "status", "score",
                  "created_at", "updated_at", "completed_at"]
        read_only_fields = fields


class ProblemSetAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProblemSetAttempt
        fields = ["id", "problem_set", "question_id", "code", "evaluated_rubric",
                  "hints_used", "score", "source", "created_at"]
        read_only_fields = fields


class ProblemSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProblemSet
        fields = ["id", "enrollment", "student", "course", "session_number", "plan_version",
                  "generation_index", "ps_uid", "content_json", "hint_tracking",
                  "superseded", "created_at"]
        read_only_fields = ["id", "enrollment", "student", "course", "generation_index",
                            "superseded", "created_at"]
