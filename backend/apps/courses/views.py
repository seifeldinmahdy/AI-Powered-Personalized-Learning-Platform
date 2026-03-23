import requests
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Course, Module, Lesson, Slide, CodeChallenge, Enrollment
from .serializers import (
    CourseSerializer, ModuleSerializer, LessonSerializer, LessonDetailSerializer,
    SlideSerializer, CodeChallengeStudentSerializer, EnrollmentSerializer,
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
    """CRUD operations for enrollments."""

    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Enrollment.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        course = serializer.validated_data.get("course")
        first_lesson = Lesson.objects.filter(
            module__course=course
        ).order_by("module__module_order", "lesson_order").first()
        serializer.save(student=self.request.user, current_lesson=first_lesson)


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
