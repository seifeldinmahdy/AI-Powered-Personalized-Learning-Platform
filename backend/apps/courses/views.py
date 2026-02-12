from rest_framework import viewsets, permissions
from .models import Course, Enrollment
from .serializers import CourseSerializer, EnrollmentSerializer


class CourseViewSet(viewsets.ModelViewSet):
    """CRUD operations for courses."""

    queryset = Course.objects.filter(is_published=True)
    serializer_class = CourseSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(instructor=self.request.user)


class EnrollmentViewSet(viewsets.ModelViewSet):
    """CRUD operations for enrollments."""

    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Enrollment.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)
