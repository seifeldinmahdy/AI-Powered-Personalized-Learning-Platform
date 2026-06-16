"""
Internal service-to-service authentication for AI service → Django calls.

When the AI service (FastAPI) needs to read/write student data on Django,
it cannot use the student's JWT.  Instead it sends:

    X-Service-Key: <shared secret from INTERNAL_SERVICE_KEY env var>
    X-Student-ID:  <student user id>

This authentication backend validates the key and resolves the user.
"""

import os
import logging

from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)

User = get_user_model()

# Shared secret — must match the value in the AI service's .env
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

# Lazily-created user for service-to-service calls that do not impersonate a
# specific student (e.g., reading course-level CLOs and concepts).
_service_user = None


def _get_service_user():
    global _service_user
    if _service_user is None:
        _service_user, _ = User.objects.get_or_create(
            username="internal-service",
            defaults={
                "role": "student",
                "is_active": True,
                "email": "internal@service.local",
            },
        )
    return _service_user


class InternalServiceAuthentication(BaseAuthentication):
    """
    Authenticates requests from trusted internal services.

    Requires two headers:
        X-Service-Key   — must match INTERNAL_SERVICE_KEY env var
        X-Student-ID    — the numeric user id to impersonate

    If INTERNAL_SERVICE_KEY is empty/unset, this backend is disabled
    and all requests fall through to the next authentication class.
    """

    def authenticate(self, request):
        service_key = request.META.get("HTTP_X_SERVICE_KEY", "")
        student_id = request.META.get("HTTP_X_STUDENT_ID", "")

        # If no service key header, skip (let other auth handle it)
        if not service_key:
            return None

        # If the env var is empty, disable this backend entirely
        if not INTERNAL_SERVICE_KEY:
            logger.warning(
                "InternalServiceAuthentication: X-Service-Key header present "
                "but INTERNAL_SERVICE_KEY env var is not set — rejecting"
            )
            return None

        if service_key != INTERNAL_SERVICE_KEY:
            raise AuthenticationFailed("Invalid service key")

        if not student_id:
            # Service-only request (no student impersonation); return the shared
            # service user so course-level reads can satisfy IsAuthenticated.
            return (_get_service_user(), "internal-service")

        try:
            user = User.objects.get(pk=int(student_id))
        except (User.DoesNotExist, ValueError, TypeError):
            raise AuthenticationFailed(f"Student with id={student_id} not found")

        return (user, "internal-service")
