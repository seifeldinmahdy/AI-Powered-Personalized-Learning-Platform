"""Core views"""

import requests
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """Simple health check endpoint."""
    return Response({"status": "ok", "service": "django-backend"})
