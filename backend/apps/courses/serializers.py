from rest_framework import serializers
from .models import (
    Course, Enrollment, CourseRating,
    Concept, CourseLearningOutcome, CourseCorpus, CorpusSource,
)


class CourseSerializer(serializers.ModelSerializer):
    corpus_id = serializers.SerializerMethodField()

    def get_corpus_id(self, obj):
        # Exposed read-only so clients/diagnostics can see the scope, but the AI
        # service resolves it server-side rather than trusting a client value.
        corpus = getattr(obj, "corpus", None)
        return corpus.corpus_id if corpus else None

    class Meta:
        model = Course
        fields = [
            "id", "title", "description",
            "difficulty", "status", "tags", "is_published", "price",
            "avg_rating", "created_at", "syllabus",
            "corpus_id",
        ]
        read_only_fields = ["id", "created_at"]



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
            "current_session_number", "progress_percentage", "current_score",
            "placement_score", "current_pathway", "is_pathway_ready",
            "is_assessment_started", "is_paid", "enrolled_at", "last_accessed",
        ]
        read_only_fields = ["id", "student", "enrolled_at", "last_accessed"]


class ConceptSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    def get_children(self, obj):
        return ConceptSerializer(obj.children.all(), many=True).data

    class Meta:
        model = Concept
        fields = ["id", "course", "label", "slug", "parent", "order", "children"]
        read_only_fields = ["id", "course", "slug"]


class CorpusSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorpusSource
        fields = ["id", "title", "book_stem", "source_type", "concept", "is_active",
                  "index_status", "chunk_count", "added_at"]
        read_only_fields = ["id", "index_status", "chunk_count", "added_at"]


class CourseCorpusSerializer(serializers.ModelSerializer):
    sources = CorpusSourceSerializer(many=True, read_only=True)

    class Meta:
        model = CourseCorpus
        fields = ["id", "course", "corpus_id", "name", "sources", "created_at", "updated_at"]
        read_only_fields = ["id", "course", "corpus_id", "created_at", "updated_at"]


class CourseLearningOutcomeSerializer(serializers.ModelSerializer):
    concepts = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Concept.objects.all(), required=False
    )

    class Meta:
        model = CourseLearningOutcome
        fields = ["id", "course", "code", "text", "bloom_level", "concepts", "order"]
        read_only_fields = ["id", "course"]
