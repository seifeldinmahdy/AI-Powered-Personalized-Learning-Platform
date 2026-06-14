import logging

from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from .models import (
    LessonCompletion, SystemActivityLog, AIChatLog,
    StudentLearningProfile, Bookmark, ConceptMasteryEvent,
)

logger = logging.getLogger(__name__)

# Below this topic→concept match confidence, a checkpoint update is DROPPED
# rather than written — the same conservative stance as a no-match. The mapping
# is on the live mastery write path with no human review, so each one is logged.
MASTERY_TOPIC_MATCH_FLOOR = 0.55
from .serializers import (
    LessonCompletionSerializer,
    SystemActivityLogSerializer,
    AIChatLogSerializer,
    StudentLearningProfileSerializer,
    BookmarkSerializer,
)


class LessonCompletionViewSet(viewsets.ModelViewSet):
    """CRUD for lesson completions. Scoped to the authenticated user's enrollments."""
    serializer_class = LessonCompletionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = LessonCompletion.objects.filter(enrollment__student=self.request.user)
        enrollment_id = self.request.query_params.get("enrollment_id")
        if enrollment_id:
            qs = qs.filter(enrollment_id=enrollment_id)
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Mark a lesson completion as Completed and set completed_at."""
        from apps.gamification.models import UserAchievement

        completion = self.get_object()
        user = request.user

        # Snapshot achievements before save so we can detect newly earned ones
        before_ids = set(
            UserAchievement.objects.filter(user=user).values_list("achievement_id", flat=True)
        )

        completion.status = "Completed"
        completion.completed_at = timezone.now()
        if "score" in request.data:
            completion.score = request.data["score"]
        time_spent = request.data.get("time_spent_minutes")
        if time_spent is not None:
            try:
                completion.time_spent_minutes = max(0, int(time_spent))
            except (TypeError, ValueError):
                pass
        else:
            completion.time_spent_minutes = 30  # backward-compat default
        completion.save()  # triggers gamification signal

        # Detect newly awarded achievements
        after = UserAchievement.objects.filter(user=user).select_related("achievement")
        newly_earned = [
            {"name": ua.achievement.name, "icon_url": ua.achievement.icon_url, "xp_reward": ua.achievement.xp_reward}
            for ua in after if ua.achievement_id not in before_ids
        ]

        data = LessonCompletionSerializer(completion).data
        data["newly_earned_achievements"] = newly_earned
        return Response(data)


class SystemActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only activity logs for the authenticated user."""
    serializer_class = SystemActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SystemActivityLog.objects.filter(user=self.request.user)


class AIChatLogViewSet(viewsets.ModelViewSet):
    """AI chat logs for the authenticated user. Filter by ?lesson_id=<id>. Supports GET + POST."""
    serializer_class = AIChatLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = AIChatLog.objects.filter(user=self.request.user).order_by("created_at")
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)





class BookmarkViewSet(viewsets.ModelViewSet):
    """Bookmark CRUD for the authenticated user."""
    serializer_class = BookmarkSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return Bookmark.objects.filter(user=self.request.user).select_related("lesson__module__course")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StudentLearningProfileViewSet(viewsets.ModelViewSet):
    """
    Persistent per-student learning profile.
    GET returns the single profile. POST creates or overwrites it.
    PATCH partially updates profile_data fields (e.g. recurrent_mistakes).
    """
    serializer_class = StudentLearningProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return StudentLearningProfile.objects.filter(student=self.request.user)

    def list(self, request, *args, **kwargs):
        """Return the single profile directly, not as a list."""
        profile = StudentLearningProfile.objects.filter(student=request.user).first()
        if not profile:
            return Response(
                {"detail": "No learning profile yet. Complete a session first."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(StudentLearningProfileSerializer(profile).data)

    def create(self, request, *args, **kwargs):
        """
        Create or overwrite the student's learning profile.
        Uses get_or_create to ensure one row per student, then overwrites fields.
        """
        profile, created = StudentLearningProfile.objects.get_or_create(
            student=request.user,
            defaults={
                "sessions_count": request.data.get("sessions_count", 0),
                "profile_summary": request.data.get("profile_summary", ""),
                "profile_data": request.data.get("profile_data", {}),
            },
        )

        if not created:
            # Overwrite existing profile with new data
            profile.sessions_count = request.data.get("sessions_count", profile.sessions_count)
            profile.profile_summary = request.data.get("profile_summary", profile.profile_summary)
            profile.profile_data = request.data.get("profile_data", profile.profile_data)
            profile.save()

        serializer = StudentLearningProfileSerializer(profile)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH — merge incoming profile_data fields into existing profile_data.
        Works both at /learning-profile/<pk>/ and /learning-profile/ (list level).
        Useful for updating recurrent_mistakes without overwriting the full profile.
        """
        pk = kwargs.get("pk")
        if pk:
            profile = StudentLearningProfile.objects.filter(student=request.user, pk=pk).first()
        else:
            profile = StudentLearningProfile.objects.filter(student=request.user).first()

        if not profile:
            return Response(
                {"detail": "No learning profile yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        incoming_data = request.data.get("profile_data")
        if incoming_data and isinstance(incoming_data, dict):
            existing = profile.profile_data or {}
            existing.update(incoming_data)
            profile.profile_data = existing
            profile.save(update_fields=["profile_data"])

        if "profile_summary" in request.data:
            profile.profile_summary = request.data["profile_summary"]
            profile.save(update_fields=["profile_summary"])

        # concept_mastery is NO LONGER writable here. It is an event-sourced
        # read-model with exactly one mutator: mastery_service.record_events
        # (via POST /progress/mastery/record/). A concept_mastery payload here is
        # ignored on purpose — see Batch 6.
        if "concept_mastery" in request.data:
            logger.warning(
                "learning-profile PATCH included concept_mastery — IGNORED "
                "(use /progress/mastery/record/). student=%s", request.user.id,
            )

        return Response(StudentLearningProfileSerializer(profile).data)

    @action(detail=False, methods=["patch"], url_path="update")
    def patch_profile(self, request):
        """PATCH /learning-profile/update/ — list-level patch alias."""
        return self.partial_update(request)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def concept_mastery_view(request):
    """GET /api/progress/concept-mastery/?course=<id>
    Returns the student's concept_mastery vector, optionally filtered by course.
    Each entry is enriched with the concept label.
    """
    from apps.courses.models import Concept

    course_id = request.query_params.get("course")
    profile = StudentLearningProfile.objects.filter(student=request.user).first()
    if not profile:
        return Response([])

    cm = profile.concept_mastery or {}

    if course_id:
        concept_ids_in_course = set(
            str(c_id) for c_id in
            Concept.objects.filter(course_id=course_id).values_list("id", flat=True)
        )
        cm = {k: v for k, v in cm.items() if k in concept_ids_in_course}

    # Resolve labels for the remaining concept IDs
    try:
        numeric_ids = [int(k) for k in cm if k.isdigit()]
        label_map = {
            str(c.id): c.label
            for c in Concept.objects.filter(id__in=numeric_ids)
        }
    except Exception:
        label_map = {}

    result = [
        {"concept_id": k, "label": label_map.get(k, k), **v}
        for k, v in cm.items()
    ]
    return Response(result)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def mastery_record(request):
    """THE single concept-mastery write endpoint (cross-process callers).

    Body: ``{"events": [{outcome, source, alpha?, evidence_delta?, mistake_tag?,
    concept_id? | (topic + course_id)}]}``. The student is the authenticated
    user (service callers impersonate via X-Student-ID). Topic-only events are
    mapped to a Concept here (logged, with a confidence floor below which they
    are DROPPED). All events funnel into the one mutator, mastery_service.record_events.

    TODO(loud): the in-session checkpoint generator should tag its MCQs with
    concept_id end-to-end so we stop fuzzy-mapping topics on the live write path.
    Until then, low-confidence/no-match topics are dropped, not written.
    """
    from apps.courses.models import Concept
    from apps.courses.concept_match import build_matcher
    from .mastery_service import record_events

    student_id = request.user.id
    raw_events = request.data.get("events", [])
    if not isinstance(raw_events, list) or not raw_events:
        return Response({"error": "events (non-empty list) required."}, status=status.HTTP_400_BAD_REQUEST)

    resolved: list[dict] = []
    dropped = 0
    _matchers: dict[str, object] = {}
    for e in raw_events:
        cid = e.get("concept_id")
        if not cid:
            topic = e.get("topic")
            course_id = e.get("course_id")
            if not topic or not course_id:
                dropped += 1
                logger.warning("mastery_record: event lacks concept_id and topic/course_id — DROPPED: %s", e)
                continue
            course_id = str(course_id)
            if course_id not in _matchers:
                _matchers[course_id] = build_matcher(list(Concept.objects.filter(course_id=course_id)))
            concept, conf = _matchers[course_id].match(topic)
            if concept is None or conf < MASTERY_TOPIC_MATCH_FLOOR:
                dropped += 1
                logger.warning(
                    "mastery_record: topic→concept DROP topic=%r course=%s "
                    "match=%s conf=%.2f floor=%.2f source=%s",
                    topic, course_id, getattr(concept, "label", None),
                    conf, MASTERY_TOPIC_MATCH_FLOOR, e.get("source"),
                )
                continue
            logger.info(
                "mastery_record: topic→concept MAP topic=%r -> %s(id=%s) conf=%.2f source=%s",
                topic, concept.label, concept.id, conf, e.get("source"),
            )
            cid = str(concept.id)
        resolved.append({
            "concept_id": str(cid),
            "outcome": e.get("outcome"),
            "source": e.get("source", "checkpoint"),
            "alpha": e.get("alpha", 0.3),
            "evidence_delta": e.get("evidence_delta", 1),
            "mistake_tag": e.get("mistake_tag", ""),
        })

    updated = record_events(student_id, resolved) if resolved else {}
    return Response({"updated": updated, "dropped": dropped})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def concept_mastery_history(request, concept_id):
    """GET /progress/concept-mastery/<concept_id>/history/ — explainability.

    Returns the ordered events for this student+concept and the running score
    after each, so you can say WHY a concept moved (which source, when, how much).
    """
    from .mastery_service import fold_events

    events = list(
        ConceptMasteryEvent.objects
        .filter(student=request.user, concept_id=str(concept_id))
        .order_by("created_at", "id")
    )
    history = []
    for i, ev in enumerate(events, 1):
        folded = fold_events(events[:i])
        history.append({
            "source": ev.source,
            "outcome": ev.outcome,
            "alpha": ev.alpha,
            "evidence_delta": ev.evidence_delta,
            "mistake_tag": ev.mistake_tag,
            "resulting_score": folded["score"],
            "created_at": ev.created_at.isoformat(),
        })
    return Response({
        "concept_id": str(concept_id),
        "events": history,
        "current": fold_events(events) if events else None,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def practice_completion(request):
    """Award bonus XP when a student passes a lesson-end practice problem.

    Body: { lesson_id: int, score: int }
    Returns: { xp_awarded: int, new_total: int, new_level: int }
    """
    from apps.users.models import StudentProfile

    try:
        score = int(request.data.get('score', 0))
        lesson_id = int(request.data.get('lesson_id', 0))
    except (TypeError, ValueError):
        return Response({"error": "Invalid score or lesson_id"}, status=status.HTTP_400_BAD_REQUEST)

    if score < 60:
        return Response({"xp_awarded": 0, "new_total": 0, "new_level": 0})

    xp_awarded = 50 if score >= 90 else 25

    try:
        profile, _ = StudentProfile.objects.get_or_create(user=request.user)
        profile.current_xp = (profile.current_xp or 0) + xp_awarded
        profile.level = min(10, max(1, profile.current_xp // 200 + 1))
        profile.save(update_fields=["current_xp", "level"])
        return Response({
            "xp_awarded": xp_awarded,
            "new_total": profile.current_xp,
            "new_level": profile.level,
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
