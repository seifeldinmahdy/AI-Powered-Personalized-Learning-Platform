from rest_framework import serializers
from .models import SurveyTemplate, SurveyQuestion, SurveyResponse, SurveySummary


class SurveyQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveyQuestion
        fields = ["id", "template", "kind", "prompt", "clo", "options", "order"]
        read_only_fields = ["id"]


class SurveyTemplateSerializer(serializers.ModelSerializer):
    questions = SurveyQuestionSerializer(many=True, read_only=True)

    class Meta:
        model = SurveyTemplate
        fields = ["id", "course", "title", "is_default", "questions", "created_at"]
        read_only_fields = ["id", "created_at"]


class SurveyResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveyResponse
        fields = ["id", "enrollment", "template", "answers", "submitted_at"]
        read_only_fields = ["id", "submitted_at"]


class SurveySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveySummary
        fields = ["id", "course", "summary_json", "response_count", "generated_at"]
        read_only_fields = ["id", "generated_at"]
