"""
Admin audit logging utilities.

Provides both a decorator for function-based views and a utility
function for class-based views / ViewSet actions.
"""

import functools
import logging
from typing import Optional

from .models import AdminAuditLog

logger = logging.getLogger(__name__)


def _get_client_ip(request) -> Optional[str]:
    """Extract the client IP from the request (respects X-Forwarded-For)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_admin_action(
    request,
    action: str,
    target_type: str = "",
    target_id: str = "",
    snapshot_before=None,
    snapshot_after=None,
) -> AdminAuditLog:
    """
    Create an AdminAuditLog entry.

    Use this in ViewSet actions or anywhere you have access to the
    DRF ``request`` object::

        log_admin_action(
            request,
            action="reset_enrollment",
            target_type="Enrollment",
            target_id=str(enrollment.pk),
            snapshot_before={"progress": old_progress},
        )
    """
    try:
        entry = AdminAuditLog.objects.create(
            admin=request.user if request.user.is_authenticated else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else "",
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            ip_address=_get_client_ip(request),
        )
        logger.info(
            "Audit: %s performed '%s' on %s#%s",
            request.user,
            action,
            target_type,
            target_id,
        )
        return entry
    except Exception:
        logger.exception("Failed to write audit log entry")
        return None


def audit_action(action_name: str, target_type: str = ""):
    """
    Decorator for function-based views that auto-creates an audit log
    entry when the view returns a successful response (status < 400).

    Usage::

        @api_view(["POST"])
        @permission_classes([IsVerifiedAdmin])
        @audit_action("trigger_retraining", target_type="IntentModel")
        def trigger_retraining(request):
            ...
    """

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)
            if hasattr(response, "status_code") and response.status_code < 400:
                log_admin_action(
                    request,
                    action=action_name,
                    target_type=target_type,
                    ip_address=_get_client_ip(request),
                )
            return response

        return wrapper

    return decorator
