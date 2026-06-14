"""Custom DRF throttles for the progress app."""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class FeedbackThrottle(UserRateThrottle):
    """Throttle for the chat-log feedback endpoint to prevent review spam."""

    scope = "feedback"
    rate = "30/hour"


class AnonFeedbackThrottle(AnonRateThrottle):
    """Anonymous users cannot submit feedback (they must be authenticated anyway)."""

    scope = "anon_feedback"
    rate = "0/minute"
