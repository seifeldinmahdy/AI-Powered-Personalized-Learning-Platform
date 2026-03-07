import requests
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
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



@api_view(['POST'])
@permission_classes([AllowAny]) # Change this to permissions.IsAuthenticated later!
def evaluate_student_code(request):
    """Bridge to forward student code to the FastAPI Llama microservice."""
    
    question = request.data.get('question')
    user_code = request.data.get('code')

    if not question or not user_code:
        return Response(
            {"error": "Missing 'question' or 'code' in request payload"}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    # Forward the payload to FastAPI service running on port 8001
    fastapi_url = "http://127.0.0.1:8001/api/coding/evaluate"
    payload = {
        "question": question,
        "code": user_code
    }

    try:
        # Send the request and wait for the AI to grade it
        ai_response = requests.post(fastapi_url, json=payload)
        ai_data = ai_response.json()

        # TODO: Add database logic here later (e.g., granting XP if they passed)

        # Send the exact AI response back to the React frontend
        return Response(ai_data, status=status.HTTP_200_OK)

    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline. Is port 8001 running?"}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )