"""
Admin permission classes for the PersonifAI platform.

Provides reusable DRF permission classes that enforce admin-level access.
All admin-only ViewSets and APIViews should use ``IsVerifiedAdmin`` instead
of inline ``request.user.role`` checks.
"""

from rest_framework.permissions import BasePermission


class IsVerifiedAdmin(BasePermission):
    """
    Grants access only to active users with ``role='admin'``.

    Combines three checks:
    - ``is_authenticated`` — rejects anonymous requests.
    - ``is_active``        — rejects disabled accounts.
    - ``role == 'admin'``  — rejects students and any other role.

    Usage::

        class SomeAdminView(APIView):
            permission_classes = [IsVerifiedAdmin]
    """

    message = "Admin access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and getattr(request.user, "role", None) == "admin"
        )
