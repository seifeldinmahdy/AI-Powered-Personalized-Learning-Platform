"""Core models — admin audit log and other platform-wide models."""

from django.conf import settings
from django.db import models


class AdminAuditLog(models.Model):
    """
    Records every privileged admin action for accountability.

    Captures the acting admin, action type, target object, optional
    before/after JSON snapshots, and the originating IP address.
    Read-only — entries are created by the ``@audit_action`` decorator
    or the ``log_admin_action()`` utility.
    """

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    action = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Machine-readable action name, e.g. 'retrain_intent', 'reset_enrollment'.",
    )
    target_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Model or resource type affected, e.g. 'Enrollment', 'User'.",
    )
    target_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Primary key or identifier of the affected resource.",
    )
    snapshot_before = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON snapshot of the resource state before the action.",
    )
    snapshot_after = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON snapshot of the resource state after the action.",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["admin", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]
        verbose_name = "Admin Audit Log"
        verbose_name_plural = "Admin Audit Logs"

    def __str__(self):
        admin_name = self.admin.username if self.admin else "system"
        return f"{admin_name} — {self.action} ({self.created_at:%Y-%m-%d %H:%M})"
