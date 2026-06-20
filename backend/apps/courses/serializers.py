from rest_framework import serializers
from .models import (
    Course, Enrollment, CourseRating,
    Concept, CourseLearningOutcome, CourseCorpus, CorpusSource, PlacementQuestion
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
        fields = ["id", "course", "label", "slug", "parent", "order", "source", "children"]
        read_only_fields = ["id", "course", "slug", "source"]


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


class PlacementQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlacementQuestion
        fields = ['id', 'question', 'options', 'correct_answer', 'topic',
                  'concept_id', 'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class PlacementQuestionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlacementQuestion
        fields = ['id', 'question', 'options', 'correct_answer', 'topic', 'concept_id', 'order']
        read_only_fields = ['id']

    def validate_options(self, value):
        if not isinstance(value, list) or len(value) != 4:
            raise serializers.ValidationError("options must be a list of exactly 4 strings.")
        if not all(isinstance(o, str) for o in value):
            raise serializers.ValidationError("All options must be strings.")
        return value

    def validate(self, data):
        correct = data.get('correct_answer')
        options = data.get('options', []) or []
        if correct:
            match = self._match_option(correct, options)
            if match is None:
                raise serializers.ValidationError({
                    "correct_answer": (
                        f"correct_answer {correct!r} must match one of the options "
                        f"{[o for o in options]!r}."
                    )
                })
            # Normalize to the EXACT option text so storage is canonical and the
            # scoring path (student_ans.strip() == correct_answer.strip()) matches.
            data['correct_answer'] = match
        return data

    @staticmethod
    def _match_option(correct, options):
        """Map an AI-supplied correct_answer to the exact option string, or None.

        Tolerant of the ways generators diverge — but only ever returns an actual
        option (never fabricates), so stored data stays canonical and scoring is
        unaffected. Tries, in order:

        1. Exact match on stripped text (case-sensitive) — the strict path.
        2. A bare option letter ("A".."D") → that option by position.
        3. A letter-prefixed answer ("B) Paris", "B. Paris", "B: Paris", "B - Paris")
           → strip the prefix, then match the remainder.
        4. Case-insensitive stripped match as a last resort.
        """
        opts = [o for o in options if isinstance(o, str)]
        target = correct.strip()

        # 1. Exact stripped match.
        for o in opts:
            if o.strip() == target:
                return o

        # 2. Bare letter → positional option.
        if len(target) == 1 and target.upper() in "ABCD":
            idx = "ABCD".index(target.upper())
            if idx < len(opts):
                return opts[idx]

        # 3. Letter prefix like "B) ...", "B. ...", "B: ...", "B - ...".
        import re
        m = re.match(r"^\s*([A-Da-d])\s*[\).:\-]\s*(.+)$", correct)
        if m:
            idx = "ABCD".index(m.group(1).upper())
            remainder = m.group(2).strip()
            for o in opts:
                if o.strip() == remainder:
                    return o
            if idx < len(opts):
                return opts[idx]

        # 4. Case-insensitive stripped match.
        low = target.lower()
        for o in opts:
            if o.strip().lower() == low:
                return o

        return None
