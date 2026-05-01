import requests
from django.db.models import Avg
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Course, Module, Lesson, Slide, CodeChallenge, Enrollment, CourseRating
from .serializers import (
    CourseSerializer, ModuleSerializer, LessonSerializer, LessonDetailSerializer,
    SlideSerializer, CodeChallengeStudentSerializer, EnrollmentSerializer, CourseRatingSerializer,
)


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

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(instructor=self.request.user)
        else:
            serializer.save()

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


class ModuleViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve modules. Filter by ?course_id=<id>."""
    serializer_class = ModuleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = Module.objects.all()
        course_id = self.request.query_params.get("course_id")
        if course_id:
            qs = qs.filter(course_id=course_id)
        return qs


class LessonViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve lessons. Filter by ?module_id=<id>. Detail includes slides + challenges."""
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return LessonDetailSerializer
        return LessonSerializer

    def get_queryset(self):
        qs = Lesson.objects.all()
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
