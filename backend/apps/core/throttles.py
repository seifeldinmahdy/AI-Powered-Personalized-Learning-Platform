"""Custom DRF throttles for admin operations."""

from rest_framework.throttling import UserRateThrottle


class AdminWriteThrottle(UserRateThrottle):
    """
    Conservative throttle for destructive admin actions.

    Applied to retraining triggers, enrollment resets, user role changes,
    and other high-impact operations.  The rate is configured in
    ``settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['admin_write']``.
    """

    scope = "admin_write"
