"""Core views — health checks and admin proxies."""

import logging

import requests as http_requests
from django.conf import settings
from rest_framework import viewsets, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import AdminAuditLog
from .permissions import IsVerifiedAdmin

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """Simple health check endpoint."""
    return Response({"status": "ok", "service": "django-backend"})


# ---------- Admin Health Proxies (distributed, per-service) ----------

def _proxy_ai_health(endpoint: str) -> dict:
    """Call a single AI service health endpoint and return status dict."""
    url = f"{settings.AI_SERVICE_URL}/{endpoint}"
    try:
        resp = http_requests.get(url, timeout=5)
        data = resp.json()
        return {"status": data.get("status", "unknown"), **data}
    except http_requests.exceptions.ConnectionError:
        return {"status": "down", "error": "Connection refused"}
    except http_requests.exceptions.Timeout:
        return {"status": "down", "error": "Timeout"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_intent(request):
    """Proxy: Intent classifier health."""
    return Response(_proxy_ai_health("intent/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_tutor(request):
    """Proxy: Tutor service health."""
    return Response(_proxy_ai_health("tutor/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_rag(request):
    """Proxy: RAG service health."""
    return Response(_proxy_ai_health("rag/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_slides(request):
    """Proxy: Slide generation health."""
    return Response(_proxy_ai_health("slides/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_asr(request):
    """Proxy: ASR service health."""
    return Response(_proxy_ai_health("asr/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_tts(request):
    """Proxy: TTS service health."""
    return Response(_proxy_ai_health("tts/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_fer(request):
    """Proxy: Facial emotion recognition health."""
    return Response(_proxy_ai_health("fer/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_ser(request):
    """Proxy: Speech emotion recognition health."""
    return Response(_proxy_ai_health("ser/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_pathway(request):
    """Proxy: Course pathway generation health."""
    return Response(_proxy_ai_health("pathway/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_assessments(request):
    """Proxy: MCQ assessment health."""
    return Response(_proxy_ai_health("assessments/health"))


@api_view(["GET"])
@permission_classes([IsVerifiedAdmin])
def admin_health_a2f(request):
    """Proxy: Audio2Face health."""
    return Response(_proxy_ai_health("a2f/health"))


# ---------- Admin Audit Log ----------

class AdminAuditLogSerializer(serializers.ModelSerializer):
    admin_username = serializers.CharField(
        source="admin.username", read_only=True, default="system"
    )

    class Meta:
        model = AdminAuditLog
        fields = [
            "id", "admin", "admin_username", "action", "target_type",
            "target_id", "snapshot_before", "snapshot_after",
            "ip_address", "created_at",
        ]
        read_only_fields = fields


class AdminAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only view of admin audit logs. Admin access only."""
    serializer_class = AdminAuditLogSerializer
    permission_classes = [IsVerifiedAdmin]

    def get_queryset(self):
        qs = AdminAuditLog.objects.select_related("admin").all()
        # Filter by action type
        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        # Filter by admin ID
        admin_id = self.request.query_params.get("admin_id")
        if admin_id:
            qs = qs.filter(admin_id=admin_id)
        return qs
