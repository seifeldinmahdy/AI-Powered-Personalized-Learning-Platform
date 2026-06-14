"""Core app URLs — health check, admin health proxies, and audit logs."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"audit-logs", views.AdminAuditLogViewSet, basename="audit-log")

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    # Admin health proxies — one endpoint per AI service (distributed)
    path("admin/health/intent/", views.admin_health_intent, name="admin-health-intent"),
    path("admin/health/tutor/", views.admin_health_tutor, name="admin-health-tutor"),
    path("admin/health/rag/", views.admin_health_rag, name="admin-health-rag"),
    path("admin/health/slides/", views.admin_health_slides, name="admin-health-slides"),
    path("admin/health/asr/", views.admin_health_asr, name="admin-health-asr"),
    path("admin/health/tts/", views.admin_health_tts, name="admin-health-tts"),
    path("admin/health/fer/", views.admin_health_fer, name="admin-health-fer"),
    path("admin/health/ser/", views.admin_health_ser, name="admin-health-ser"),
    path("admin/health/pathway/", views.admin_health_pathway, name="admin-health-pathway"),
    path("admin/health/assessments/", views.admin_health_assessments, name="admin-health-assessments"),
    path("admin/health/a2f/", views.admin_health_a2f, name="admin-health-a2f"),
    # Audit logs
    path("", include(router.urls)),
]
