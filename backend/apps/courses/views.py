from rest_framework import viewsets, permissions, filters
from rest_framework.permissions import AllowAny
from .models import Course, Enrollment
from .serializers import CourseSerializer, EnrollmentSerializer


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
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status__iexact=status)

        return qs

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(instructor=self.request.user)
        else:
            serializer.save()


class EnrollmentViewSet(viewsets.ModelViewSet):
    """CRUD operations for enrollments."""

    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Enrollment.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)
