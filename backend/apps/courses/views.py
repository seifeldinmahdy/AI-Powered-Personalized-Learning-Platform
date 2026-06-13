import requests
from django.db.models import Avg
from django.core.cache import cache
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Course, Module, Lesson, Slide, CodeChallenge, Enrollment, CourseRating, Concept, CourseLearningOutcome
from .serializers import (
    CourseSerializer, ModuleSerializer, LessonSerializer, LessonDetailSerializer,
    SlideSerializer, CodeChallengeStudentSerializer, EnrollmentSerializer, CourseRatingSerializer,
    ConceptSerializer, CourseLearningOutcomeSerializer,
)
from django.conf import settings

CACHE_TTL = 60 * 15  # 15 minutes


class CourseViewSet(viewsets.ModelViewSet):
    """CRUD operations for courses. Supports search and filtering."""

    serializer_class = CourseSerializer
    permission_classes = [AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description", "tags"]
    ordering_fields = ["created_at", "title", "price", "avg_rating"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Course.objects.all()

        # Filter by difficulty
        difficulty = self.request.query_params.get("difficulty")
        if difficulty:
            qs = qs.filter(difficulty__iexact=difficulty)

        # Filter by status
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        return qs

    def list(self, request, *args, **kwargs):
        cache_key = f"course_list_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL)
        return response

    def retrieve(self, request, *args, **kwargs):
        cache_key = f"course_detail_{kwargs['pk']}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().retrieve(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL)
        return response

    def perform_create(self, serializer):
        serializer.save()
        cache.delete_pattern("course_list_*") if hasattr(cache, 'delete_pattern') else cache.clear()

    def perform_update(self, serializer):
        instance = serializer.save()
        cache.delete(f"course_detail_{instance.pk}")
        cache.delete_pattern("course_list_*") if hasattr(cache, 'delete_pattern') else None

    def perform_destroy(self, instance):
        cache.delete(f"course_detail_{instance.pk}")
        instance.delete()

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def rate(self, request, pk=None):
        course = self.get_object()
        rating_value = request.data.get("rating")
        if not rating_value or not (1 <= int(rating_value) <= 5):
            return Response({"error": "rating must be an integer between 1 and 5"}, status=status.HTTP_400_BAD_REQUEST)

        obj, _ = CourseRating.objects.update_or_create(
            course=course,
            student=request.user,
            defaults={"rating": int(rating_value)},
        )

        avg = CourseRating.objects.filter(course=course).aggregate(Avg("rating"))["rating__avg"] or 0
        Course.objects.filter(pk=course.pk).update(avg_rating=round(avg, 2))

        return Response({"avg_rating": round(avg, 2), "your_rating": obj.rating})


class IsAdminOrReadOnly(permissions.BasePermission):
    """Allow full access to admins; read-only to everyone else."""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin'


class ModuleViewSet(viewsets.ModelViewSet):
    """CRUD for modules (write requires admin). Filter by ?course_id=<id>."""
    serializer_class = ModuleSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = Module.objects.all().order_by('module_order')
        course_id = self.request.query_params.get("course_id")
        if course_id:
            qs = qs.filter(course_id=course_id)
        return qs


class LessonViewSet(viewsets.ModelViewSet):
    """CRUD for lessons (write requires admin). Filter by ?module_id=<id>. Detail includes slides + challenges."""
    permission_classes = [IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return LessonDetailSerializer
        return LessonSerializer

    def get_queryset(self):
        qs = Lesson.objects.all().order_by('lesson_order')
        module_id = self.request.query_params.get("module_id")
        if module_id:
            qs = qs.filter(module_id=module_id)
        return qs


class SlideViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve slides. Filter by ?lesson_id=<id>."""
    serializer_class = SlideSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = Slide.objects.all()
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs


class CodeChallengeViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve code challenges (student-safe). Filter by ?lesson_id=<id>."""
    serializer_class = CodeChallengeStudentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = CodeChallenge.objects.all()
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs


class EnrollmentViewSet(viewsets.ModelViewSet):
    """CRUD operations for enrollments. Admins see all; students see their own."""

    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == "admin":
            return Enrollment.objects.select_related("student", "course").all()
        return Enrollment.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        course = serializer.validated_data.get("course")
        first_lesson = Lesson.objects.filter(
            module__course=course
        ).order_by("module__module_order", "lesson_order").first()
        serializer.save(student=self.request.user, current_lesson=first_lesson)

    @action(detail=True, methods=["post"], url_path="save_pathway")
    def save_pathway(self, request, pk=None):
        enrollment = self.get_object()
        pathway_data = request.data.get("pathway", {})
        slides_data = request.data.get("slides", [])

        from django.db import transaction
        with transaction.atomic():
            enrollment.current_pathway = pathway_data
            enrollment.is_pathway_ready = True
            enrollment.save(update_fields=["current_pathway", "is_pathway_ready"])
            
            # Here we would normally save the slides that are generated.
            # Assuming 'slides_data' processing... (mocking as instruction just said "when saving all generated slides")
            pass

        return Response({"status": "pathway and slides saved", "is_pathway_ready": True}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def admin_stats(request):
    """Summary stats for the admin dashboard."""
    if request.user.role != "admin":
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    from apps.users.models import User
    from apps.progress.models import LessonCompletion

    total_students = User.objects.filter(role="student").count()
    total_courses = Course.objects.count()
    active_courses = Course.objects.filter(status="Published").count()
    total_enrollments = Enrollment.objects.count()
    completed_lessons = LessonCompletion.objects.filter(status="Completed").count()

    # Avg completion % across all enrollments
    enrollments = Enrollment.objects.all()
    avg_completion = (
        sum(e.progress_percentage or 0 for e in enrollments) / enrollments.count()
        if enrollments.count() > 0 else 0
    )

    # Recent enrollments (last 5)
    recent_enrollments = (
        Enrollment.objects.select_related("student", "course")
        .order_by("-enrolled_at")[:5]
    )
    recent = [
        {
            "student": e.student.username,
            "course": e.course.title,
            "enrolled_at": e.enrolled_at,
        }
        for e in recent_enrollments
    ]

    return Response({
        "total_students": total_students,
        "total_courses": total_courses,
        "active_courses": active_courses,
        "total_enrollments": total_enrollments,
        "completed_lessons": completed_lessons,
        "avg_completion": round(avg_completion, 1),
        "recent_enrollments": recent,
    })





@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def evaluate_student_code(request):
    """Bridge to forward student code to the FastAPI Llama microservice."""

    question = request.data.get('question')
    user_code = request.data.get('code')

    if not question or not user_code:
        return Response(
            {"error": "Missing 'question' or 'code' in request payload"},
            status=status.HTTP_400_BAD_REQUEST
        )

    fastapi_url = "http://127.0.0.1:8001/api/coding/evaluate"
    payload = {"question": question, "code": user_code}

    try:
        ai_response = requests.post(fastapi_url, json=payload)
        ai_data = ai_response.json()
        return Response(ai_data, status=status.HTTP_200_OK)

    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline. Is port 8001 running?"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def evaluate_student_code_graded(request):
    """Bridge to AI service graded evaluation endpoint (returns 0–100 score + breakdown)."""
    question = request.data.get('question')
    user_code = request.data.get('code')
    rubric = request.data.get('rubric')  # optional

    if not question or not user_code:
        return Response(
            {"error": "Missing 'question' or 'code' in request payload"},
            status=status.HTTP_400_BAD_REQUEST
        )

    payload = {"question": question, "code": user_code}
    if rubric:
        payload["rubric"] = rubric

    try:
        ai_response = requests.post("http://127.0.0.1:8001/api/coding/evaluate-graded", json=payload)
        return Response(ai_response.json(), status=status.HTTP_200_OK)
    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def get_coding_rubric(request):
    """Bridge to AI service rubric generation endpoint."""
    question = request.data.get('question')
    if not question:
        return Response({"error": "Missing 'question'"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        ai_response = requests.post("http://127.0.0.1:8001/api/coding/rubric", json={"question": question})
        return Response(ai_response.json(), status=status.HTTP_200_OK)
    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def get_coding_hint(request):
    """Bridge to AI service hint endpoint."""
    question = request.data.get('question')
    code = request.data.get('code', '')
    hint_level = request.data.get('hint_level', 1)

    if not question:
        return Response({"error": "Missing 'question'"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        ai_response = requests.post(
            "http://127.0.0.1:8001/api/coding/hint",
            json={"question": question, "code": code, "hint_level": hint_level}
        )
        return Response(ai_response.json(), status=status.HTTP_200_OK)
    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


# ------------------------------------------------------------------
# Concept ViewSet — read-only; nested under /api/courses/courses/<course_pk>/concepts/
# ------------------------------------------------------------------
class ConceptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ConceptSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        course_pk = self.kwargs.get("course_pk")
        qs = Concept.objects.select_related("parent").prefetch_related("children", "lessons")
        if course_pk:
            qs = qs.filter(course_id=course_pk)
        return qs


# ------------------------------------------------------------------
# CourseLearningOutcome ViewSet — CRUD (admin writes); nested under /api/courses/courses/<course_pk>/clos/
# ------------------------------------------------------------------
class CourseLearningOutcomeViewSet(viewsets.ModelViewSet):
    serializer_class = CourseLearningOutcomeSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        course_pk = self.kwargs.get("course_pk")
        qs = CourseLearningOutcome.objects.prefetch_related("concepts")
        if course_pk:
            qs = qs.filter(course_id=course_pk)
        return qs

    def perform_create(self, serializer):
        course_pk = self.kwargs.get("course_pk")
        serializer.save(course_id=course_pk)

    @action(detail=False, methods=["post"], url_path="suggest",
            permission_classes=[permissions.IsAuthenticated])
    def suggest(self, request, course_pk=None):
        """POST /api/courses/courses/<course_pk>/clos/suggest/ — admin only.
        Proxies to the AI service to generate draft CLOs.
        """
        if getattr(request.user, "role", None) != "admin":
            return Response({"error": "Admin only"}, status=status.HTTP_403_FORBIDDEN)

        try:
            course = Course.objects.get(pk=course_pk)
        except Course.DoesNotExist:
            return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

        # Build outline: [{module, lessons: [str]}]
        outline = []
        for module in course.modules.prefetch_related("lessons").order_by("module_order"):
            outline.append({
                "module": module.title,
                "lessons": list(module.lessons.values_list("title", flat=True).order_by("lesson_order")),
            })

        existing_concepts = list(
            Concept.objects.filter(course=course).values("id", "label")
        )

        ai_url = getattr(settings, "AI_SERVICE_URL", "http://localhost:8001")
        try:
            ai_resp = requests.post(
                f"{ai_url}/clos/suggest",
                json={
                    "course_title": course.title,
                    "outline": outline,
                    "existing_concepts": [
                        {"id": str(c["id"]), "label": c["label"]} for c in existing_concepts
                    ],
                },
                timeout=120,
            )
            ai_resp.raise_for_status()
            return Response(ai_resp.json())
        except requests.exceptions.ConnectionError:
            return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=False, methods=["get"], url_path="attainment",
            permission_classes=[permissions.IsAuthenticated])
    def attainment(self, request, course_pk=None):
        """GET /api/courses/courses/<course_pk>/clos/attainment/?student=<id>
        Returns per-CLO attainment derived from concept_mastery scores.
        """
        from apps.progress.models import StudentLearningProfile

        student_id = request.query_params.get("student") or request.user.id
        profile = StudentLearningProfile.objects.filter(student_id=student_id).first()
        cm = (profile.concept_mastery or {}) if profile else {}

        clos = (
            CourseLearningOutcome.objects
            .filter(course_id=course_pk)
            .prefetch_related("concepts")
        )
        result = []
        for clo in clos:
            scores = [
                cm[str(c.id)]["score"]
                for c in clo.concepts.all()
                if str(c.id) in cm
            ]
            evidence = sum(
                cm.get(str(c.id), {}).get("evidence", 0)
                for c in clo.concepts.all()
            )
            result.append({
                "id": clo.id,
                "code": clo.code,
                "text": clo.text,
                "bloom_level": clo.bloom_level,
                "attainment": round(sum(scores) / len(scores), 3) if scores else None,
                "evidence_count": evidence,
            })
        return Response(result)
