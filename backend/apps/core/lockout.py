"""
Custom lockout response for django-axes.

Returns a JSON 403 instead of the default HTML page so the React
frontend can display a proper error message.
"""

from django.http import JsonResponse


def axes_lockout_handler(request, credentials, *args, **kwargs):
    """
    Called by django-axes when a login attempt is blocked.

    Returns a JSON 403 with a user-friendly message and a machine-readable
    ``lockout`` flag that the frontend can use to show a lockout UI.
    """
    return JsonResponse(
        {
            "error": "Too many failed login attempts. Please try again later.",
            "lockout": True,
        },
        status=403,
    )
