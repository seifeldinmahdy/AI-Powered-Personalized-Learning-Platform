import requests
from django.db.models import Avg
from django.core.cache import cache
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.core.authentication import InternalServiceAuthentication
from .models import (
    Course, Enrollment, CourseRating,
    Concept, CourseLearningOutcome, CourseCorpus, CorpusSource,
    PlacementQuestion,
)
from .serializers import (
    CourseSerializer, EnrollmentSerializer, CourseRatingSerializer,
    ConceptSerializer, CourseLearningOutcomeSerializer,
    CourseCorpusSerializer, CorpusSourceSerializer,
    PlacementQuestionSerializer, PlacementQuestionWriteSerializer
)
from django.conf import settings

CACHE_TTL = 60 * 15  # 15 minutes


def _is_admin(user):
    return getattr(user, "role", None) == "admin"


def _ai_url():
    import os
    return getattr(settings, "AI_SERVICE_URL", None) or os.getenv("AI_SERVICE_URL", "http://localhost:8001")


def _svc_headers():
    import os
    return {"X-Service-Key": os.getenv("INTERNAL_SERVICE_KEY", "")}


class IsAdminOrReadOnly(permissions.BasePermission):
    """Allow full access to admins; read-only to everyone else."""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin'


class CourseViewSet(viewsets.ModelViewSet):
    """CRUD operations for courses. Supports search and filtering.
    Read access is public so the course catalog works; writes are admin-only."""

    serializer_class = CourseSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description", "tags"]
    ordering_fields = ["created_at", "title", "price", "avg_rating"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Course.objects.all()

        # Filter by difficulty
        difficulty = self.request.query_params.get("difficulty")
        if difficulty:
            qs = qs.filter(difficulty__iexact=difficulty)

        # Filter by status
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        return qs

    def list(self, request, *args, **kwargs):
        cache_key = f"course_list_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL)
        return response

    def retrieve(self, request, *args, **kwargs):
        cache_key = f"course_detail_{kwargs['pk']}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().retrieve(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL)
        return response

    def perform_create(self, serializer):
        serializer.save()
        cache.delete_pattern("course_list_*") if hasattr(cache, 'delete_pattern') else cache.clear()

    def perform_update(self, serializer):
        instance = serializer.save()
        cache.delete(f"course_detail_{instance.pk}")
        cache.delete_pattern("course_list_*") if hasattr(cache, 'delete_pattern') else None

    def perform_destroy(self, instance):
        cache.delete(f"course_detail_{instance.pk}")
        if hasattr(cache, 'delete_pattern'):
            cache.delete_pattern("course_list_*")
        instance.delete()

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def draft_description(self, request, pk=None):
        """POST /api/courses/courses/<id>/draft-description/ — ADMIN. AI-drafts a
        course description (admin reviews/edits before saving). Proxies the AI
        authoring endpoint; passes corpus topics when available."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        course = self.get_object()
        try:
            resp = requests.post(
                f"{_ai_url().rstrip('/')}/authoring/course-description",
                json={
                    "title": course.title,
                    "current_description": request.data.get("current_description", course.description or ""),
                    "topics": request.data.get("topics", []),
                },
                headers=_svc_headers(), timeout=60,
            )
            return Response(resp.json(), status=resp.status_code)
        except requests.exceptions.ConnectionError:
            return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def rate(self, request, pk=None):
        course = self.get_object()
        rating_value = request.data.get("rating")
        if not rating_value or not (1 <= int(rating_value) <= 5):
            return Response({"error": "rating must be an integer between 1 and 5"}, status=status.HTTP_400_BAD_REQUEST)

        obj, _ = CourseRating.objects.update_or_create(
            course=course,
            student=request.user,
            defaults={"rating": int(rating_value)},
        )

        avg = CourseRating.objects.filter(course=course).aggregate(Avg("rating"))["rating__avg"] or 0
        Course.objects.filter(pk=course.pk).update(avg_rating=round(avg, 2))

        return Response({"avg_rating": round(avg, 2), "your_rating": obj.rating})



class EnrollmentViewSet(viewsets.ModelViewSet):
    """CRUD operations for enrollments. Admins see all; students see their own."""

    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == "admin":
            return Enrollment.objects.select_related("student", "course").all()
        return Enrollment.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user, current_session_number=1)

    # save_pathway was RETIRED: the authoritative plan lives in the AI-service
    # versioned store, not Django. The plan is generated once server-side after
    # placement (which also sets is_pathway_ready — the single runtime writer of
    # that flag). The frontend no longer pushes the plan here.


def _fetch_current_plan(student_id, course_id):
    """Read-only fetch of the CURRENT authoritative plan from the AI service
    (plan_version + total_sessions + sessions). Returns None on any failure —
    resume then degrades to the index-only view."""
    import os
    ai_url = os.getenv("AI_SERVICE_URL", "http://localhost:8001").rstrip("/")
    try:
        headers = {
            "X-Service-Key": os.getenv("INTERNAL_SERVICE_KEY", ""),
            "X-Student-ID": str(student_id),
        }
        resp = requests.get(
            f"{ai_url}/pathway/current",
            params={"course_id": str(course_id)},
            headers=headers,
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "resume: could not fetch current plan (student=%s course=%s)", student_id, course_id)
    return None


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def course_resume(request, course_id):
    """Resume summary for a course — computed entirely from the index + the
    current plan, never by scanning artifact content.

    Returns total/completed/remaining session counts, the continue pointer, and a
    timeline of this enrollment's artifacts (slides, labs, problem sets) at the
    CURRENT plan_version — so orphaned old-version artifacts never show as current.
    """
    from apps.progress.models import SessionCompletion
    from apps.artifacts.models import StudentArtifact, ProblemSet

    enrollment = Enrollment.objects.filter(
        student=request.user, course_id=course_id
    ).first()
    if not enrollment:
        return Response({"error": "Not enrolled in this course."}, status=status.HTTP_404_NOT_FOUND)

    plan = _fetch_current_plan(request.user.id, course_id)
    plan_version = plan.get("plan_version") if plan else None
    total_sessions = int(plan.get("total_sessions", 0)) if plan else 0


    if not enrollment.current_session_number:
        enrollment.current_session_number = 1
        enrollment.save(update_fields=["current_session_number"])

    completed = SessionCompletion.objects.filter(
        enrollment=enrollment, status="Completed"
    ).count()
    sessions_left = max(0, total_sessions - completed)



    timeline = []
    if plan_version is not None:
        # Slides + labs — content_json deferred (no content scan).
        for a in (StudentArtifact.objects
                  .filter(enrollment=enrollment, plan_version=plan_version)
                  .defer("content_json").order_by("session_number")):
            timeline.append({
                "kind": "artifact", "id": a.id, "type": a.artifact_type,
                "session_number": a.session_number, "lesson": a.session_number,
                "status": a.status,
                "sort_key": a.session_number or 9999,
            })
        # Problem sets — content/hint deferred; best score is content-free.
        from apps.artifacts.scoring import best_session_score
        for ps in (ProblemSet.objects
                   .filter(enrollment=enrollment, plan_version=plan_version)
                   .defer("content_json", "hint_tracking").prefetch_related("attempts")):
            timeline.append({
                "kind": "problem_set", "ps_uid": ps.ps_uid, "type": "problem_set",
                "lesson": ps.session_number, "session_number": ps.session_number, "generation_index": ps.generation_index,
                "superseded": ps.superseded,
                "status": "completed" if ps.attempts.all() else "generated",
                "best_score": best_session_score(enrollment.id, ps.session_number, plan_version),
                "sort_key": ps.session_number or 9999,
            })
        # Remediation overlay (Batch 11a) — pending review steps, positioned just
        # after the session that teaches the weak concept. Index-light (.values(),
        # no content), consistent with the rest of the timeline.
        from apps.progress.remediation_service import pending_for_enrollment
        concept_session = {}
        for s in (plan.get("sessions", []) if plan else []):
            for cid in s.get("concept_ids", []) or []:
                concept_session.setdefault(str(cid), s.get("session_number"))
        for r in pending_for_enrollment(enrollment, plan_version):
            sess = concept_session.get(str(r["concept_id"]))
            timeline.append({
                "kind": "remediation", "type": "remediation", "id": r["id"],
                "concept": r["concept_id"], "status": r["status"],
                "score_at_trigger": r["score_at_trigger"],
                "sort_key": (sess + 0.5) if sess else 9999,
            })
        timeline.sort(key=lambda e: e["sort_key"])

    return Response({
        "course_id": int(course_id),
        "enrollment_id": enrollment.id,
        "progress_percentage": float(enrollment.progress_percentage or 0),
        "plan_version": plan_version,
        "total_sessions": total_sessions,
        "completed": completed,
        "sessions_left": sessions_left,
        "current_session_number": enrollment.current_session_number,
        "timeline": timeline,
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def admin_stats(request):
    """Summary stats for the admin dashboard."""
    from apps.core.permissions import IsVerifiedAdmin
    if not IsVerifiedAdmin().has_permission(request, None):
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    from apps.users.models import User
    from apps.progress.models import SessionCompletion

    total_students = User.objects.filter(role="student").count()
    total_courses = Course.objects.count()
    active_courses = Course.objects.filter(status="Published").count()
    total_enrollments = Enrollment.objects.count()
    completed_lessons = SessionCompletion.objects.filter(status="Completed").count()

    # Avg completion % across all enrollments
    enrollments = Enrollment.objects.all()
    avg_completion = (
        sum(e.progress_percentage or 0 for e in enrollments) / enrollments.count()
        if enrollments.count() > 0 else 0
    )

    # Recent enrollments (last 5)
    recent_enrollments = (
        Enrollment.objects.select_related("student", "course")
        .order_by("-enrolled_at")[:5]
    )
    recent = [
        {
            "student": e.student.username,
            "course": e.course.title,
            "enrolled_at": e.enrolled_at,
        }
        for e in recent_enrollments
    ]

    return Response({
        "total_students": total_students,
        "total_courses": total_courses,
        "active_courses": active_courses,
        "total_enrollments": total_enrollments,
        "completed_lessons": completed_lessons,
        "avg_completion": round(avg_completion, 1),
        "recent_enrollments": recent,
    })





@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def regenerate_pathway(request, course_id):
    """POST /api/courses/courses/<course_id>/pathway/regenerate/  — ADMIN ONLY.

    A STUDENT CANNOT regenerate their pathway. This is the only human-initiated
    regeneration path and it is admin-gated server-side; it proxies to the
    internal AI endpoint with the service key (which itself rejects keyless
    callers). Body: {"student_id": <id>}.

    TODO(instructor-role): when an 'instructor' role is added, allow it here too.
    """
    import os
    if getattr(request.user, "role", None) != "admin":
        return Response(
            {"error": "Only an admin can regenerate a pathway."},
            status=status.HTTP_403_FORBIDDEN,
        )

    student_id = request.data.get("student_id")
    if not student_id:
        return Response({"error": "student_id is required."}, status=status.HTTP_400_BAD_REQUEST)

    ai_url = getattr(settings, "AI_SERVICE_URL", "http://localhost:8001")
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        ai_resp = requests.post(
            f"{ai_url}/pathway-admin/regenerate",
            json={"student_id": str(student_id), "course_id": str(course_id)},
            headers={"X-Service-Key": service_key},
            timeout=600,
        )
        return Response(ai_resp.json(), status=ai_resp.status_code)
    except requests.exceptions.ConnectionError:
        return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def pathway_versions(request, course_id):
    """GET /api/courses/courses/<course_id>/pathway/versions/?student_id= — ADMIN.

    Lists a student's plan versions (metadata only) so an admin/instructor can
    inspect them. Students never see this. Proxies the AI pathway store.
    """
    if not _is_admin(request.user):
        return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
    student_id = request.query_params.get("student_id")
    if not student_id:
        return Response({"error": "student_id is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        # The AI /pathway/versions endpoint now takes identity from the verified
        # X-Student-ID header. This is the one admin exception: the admin chose
        # the target (authorized by the admin gate above), so we set the header
        # to that target — not request.user.
        headers = {**_svc_headers(), "X-Student-ID": str(student_id)}
        resp = requests.get(
            f"{_ai_url().rstrip('/')}/pathway/versions",
            params={"course_id": str(course_id)},
            headers=headers, timeout=30,
        )
        return Response(resp.json(), status=resp.status_code)
    except requests.exceptions.ConnectionError:
        return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def evaluate_student_code(request):
    """Bridge to forward student code to the FastAPI Llama microservice."""

    question = request.data.get('question')
    user_code = request.data.get('code')

    if not question or not user_code:
        return Response(
            {"error": "Missing 'question' or 'code' in request payload"},
            status=status.HTTP_400_BAD_REQUEST
        )

    fastapi_url = f"{settings.AI_SERVICE_URL}/api/coding/evaluate"
    payload = {"question": question, "code": user_code}

    try:
        ai_response = requests.post(fastapi_url, json=payload)
        ai_data = ai_response.json()
        return Response(ai_data, status=status.HTTP_200_OK)

    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline. Is port 8001 running?"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def evaluate_student_code_graded(request):
    """Bridge to AI service graded evaluation endpoint (returns 0–100 score + breakdown)."""
    question = request.data.get('question')
    user_code = request.data.get('code')
    rubric = request.data.get('rubric')  # optional

    if not question or not user_code:
        return Response(
            {"error": "Missing 'question' or 'code' in request payload"},
            status=status.HTTP_400_BAD_REQUEST
        )

    payload = {"question": question, "code": user_code}
    if rubric:
        payload["rubric"] = rubric

    try:
        ai_response = requests.post(f"{settings.AI_SERVICE_URL}/api/coding/evaluate-graded", json=payload)
        return Response(ai_response.json(), status=status.HTTP_200_OK)
    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def get_coding_rubric(request):
    """Bridge to AI service rubric generation endpoint."""
    question = request.data.get('question')
    if not question:
        return Response({"error": "Missing 'question'"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        rubric_url = f"{settings.AI_SERVICE_URL}/api/coding/rubric"
        ai_response = requests.post(rubric_url, json={"question": question})
        return Response(ai_response.json(), status=status.HTTP_200_OK)
    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def get_coding_hint(request):
    """Bridge to AI service hint endpoint."""
    question = request.data.get('question')
    code = request.data.get('code', '')
    hint_level = request.data.get('hint_level', 1)

    if not question:
        return Response({"error": "Missing 'question'"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        ai_response = requests.post(
            f"{settings.AI_SERVICE_URL}/api/coding/hint",
            json={"question": question, "code": code, "hint_level": hint_level}
        )
        return Response(ai_response.json(), status=status.HTTP_200_OK)
    except requests.exceptions.ConnectionError:
        return Response(
            {"error": "AI Grading Service is currently offline."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


# ------------------------------------------------------------------
# Concept ViewSet — read-only; nested under /api/courses/courses/<course_pk>/concepts/
# ------------------------------------------------------------------
class ConceptViewSet(viewsets.ModelViewSet):
    serializer_class = ConceptSerializer
    authentication_classes = [JWTAuthentication, InternalServiceAuthentication]
    permission_classes = [IsAdminOrReadOnly]

    def perform_create(self, serializer):
        course_pk = self.kwargs.get("course_pk")
        from django.utils.text import slugify
        label = serializer.validated_data.get("label", "")
        slug = serializer.validated_data.get("slug") or slugify(label)[:60]
        serializer.save(course_id=course_pk, slug=slug)

    def get_queryset(self):
        course_pk = self.kwargs.get("course_pk")
        qs = Concept.objects.select_related("parent").prefetch_related("children")
        if course_pk:
            qs = qs.filter(course_id=course_pk)
        return qs


# ------------------------------------------------------------------
# CourseLearningOutcome ViewSet — CRUD (admin writes); nested under /api/courses/courses/<course_pk>/clos/
# ------------------------------------------------------------------
class CourseLearningOutcomeViewSet(viewsets.ModelViewSet):
    serializer_class = CourseLearningOutcomeSerializer
    authentication_classes = [JWTAuthentication, InternalServiceAuthentication]
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        course_pk = self.kwargs.get("course_pk")
        qs = CourseLearningOutcome.objects.prefetch_related("concepts")
        if course_pk:
            qs = qs.filter(course_id=course_pk)
        return qs

    def perform_create(self, serializer):
        course_pk = self.kwargs.get("course_pk")
        code = serializer.validated_data.get("code", "")
        concepts = serializer.validated_data.pop("concepts", None)
        obj, created = CourseLearningOutcome.objects.update_or_create(
            course_id=course_pk, code=code,
            defaults={
                "text": serializer.validated_data.get("text", ""),
                "bloom_level": serializer.validated_data.get("bloom_level", ""),
                "order": serializer.validated_data.get("order", 0),
            },
        )
        if concepts is not None:
            obj.concepts.set(concepts)
        serializer.instance = obj

    @action(detail=False, methods=["post"], url_path="suggest",
            permission_classes=[permissions.IsAuthenticated])
    def suggest(self, request, course_pk=None):
        """POST /api/courses/courses/<course_pk>/clos/suggest/ — admin only.
        Proxies to the AI service to generate draft CLOs.

        When the course has no Concept objects yet, seeds one Concept per lesson
        from the outline so the LLM can reference real concept IDs. This ensures
        CLO drafts come back with concept_ids populated and the backward-designed
        assessment plan works.
        """
        if getattr(request.user, "role", None) != "admin":
            return Response({"error": "Admin only"}, status=status.HTTP_403_FORBIDDEN)

        try:
            course = Course.objects.get(pk=course_pk)
        except Course.DoesNotExist:
            return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

        # Fetch existing Concepts to pass to AI for mapping.
        existing_concepts = list(
            Concept.objects.filter(course=course).values("id", "label")
        )

        ai_url = getattr(settings, "AI_SERVICE_URL", "http://localhost:8001")
        try:
            ai_resp = requests.post(
                f"{ai_url}/clos/suggest",
                json={
                    "course_title": course.title,
                    "course_description": course.description or "",
                    "existing_concepts": [
                        {"id": str(c["id"]), "label": c["label"]} for c in existing_concepts
                    ],
                },
                timeout=120,
            )
            ai_resp.raise_for_status()
            data = ai_resp.json()
            
            # If the AI generated new concepts, create them and remap the draft IDs
            if data.get("suggested_concepts"):
                from django.utils.text import slugify
                label_to_id = {}
                for order, label in enumerate(data["suggested_concepts"], start=1):
                    slug = slugify(label)[:60]
                    obj, _ = Concept.objects.get_or_create(
                        course=course, slug=slug,
                        defaults={"label": label, "order": order},
                    )
                    label_to_id[label] = str(obj.id)
                
                # Remap the draft concept_ids (which contain labels) to the newly created IDs
                for draft in data.get("drafts", []):
                    new_ids = []
                    for raw_label in draft.get("concept_ids", []):
                        if raw_label in label_to_id:
                            new_ids.append(label_to_id[raw_label])
                        else:
                            # Fuzzy matching fallback
                            from difflib import SequenceMatcher
                            best_match = None
                            best_ratio = 0
                            for label, cid in label_to_id.items():
                                ratio = SequenceMatcher(None, raw_label.lower(), label.lower()).ratio()
                                if ratio > best_ratio:
                                    best_ratio = ratio
                                    best_match = cid
                            if best_match and best_ratio > 0.5:
                                new_ids.append(best_match)

                    # If no concepts were mapped by the LLM, use text similarity between CLO text and concept labels
                    if not new_ids and draft.get("text"):
                        from difflib import SequenceMatcher
                        import re

                        def _norm(s):
                            return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()
                            
                        clo_text = _norm(draft["text"])
                        scores = []
                        for label, cid in label_to_id.items():
                            norm_label = _norm(label)
                            ratio = SequenceMatcher(None, clo_text, norm_label).ratio()
                            clo_words = set(clo_text.split())
                            label_words = set(norm_label.split())
                            overlap = len(clo_words & label_words) / max(len(label_words), 1)
                            score = 0.5 * ratio + 0.5 * overlap
                            scores.append((cid, score))
                            
                        scores.sort(key=lambda x: -x[1])
                        new_ids = [cid for cid, s in scores[:3] if s > 0.15]
                        if not new_ids and scores:
                            new_ids = [scores[0][0]]

                    # deduplicate new_ids and update draft
                    draft["concept_ids"] = list(dict.fromkeys(new_ids))

            return Response(data)
        except requests.exceptions.ConnectionError:
            return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=False, methods=["get"], url_path="attainment",
            permission_classes=[permissions.IsAuthenticated])
    def attainment(self, request, course_pk=None):
        """GET /api/courses/courses/<course_pk>/clos/attainment/?student=<id>
        Returns per-CLO attainment derived from concept_mastery scores.
        """
        from apps.progress.models import StudentLearningProfile

        student_id = request.query_params.get("student") or request.user.id
        profile = StudentLearningProfile.objects.filter(student_id=student_id).first()
        cm = (profile.concept_mastery or {}) if profile else {}

        clos = (
            CourseLearningOutcome.objects
            .filter(course_id=course_pk)
            .prefetch_related("concepts")
        )
        result = []
        for clo in clos:
            scores = [
                cm[str(c.id)]["score"]
                for c in clo.concepts.all()
                if str(c.id) in cm
            ]
            evidence = sum(
                cm.get(str(c.id), {}).get("evidence", 0)
                for c in clo.concepts.all()
            )
            result.append({
                "id": clo.id,
                "code": clo.code,
                "text": clo.text,
                "bloom_level": clo.bloom_level,
                "attainment": round(sum(scores) / len(scores), 3) if scores else None,
                "evidence_count": evidence,
            })
        return Response(result)


# ------------------------------------------------------------------
# CourseCorpus ViewSet — admin-defined source material per course
# Nested under /api/courses/courses/<course_pk>/corpus/
# ------------------------------------------------------------------
class CourseCorpusViewSet(viewsets.ViewSet):
    """Manage a course's corpus and its sources.

    Reads (GET corpus) are open so the AI service can resolve the scope; writes
    (add/remove sources) require admin. The corpus itself is auto-created per
    course, so GET always returns one for an existing course.
    """

    permission_classes = [IsAdminOrReadOnly]

    @staticmethod
    def _get_or_create_corpus(course_pk):
        course = Course.objects.get(pk=course_pk)
        corpus, _ = CourseCorpus.objects.get_or_create(
            course=course, defaults={"name": course.title},
        )
        return corpus

    def retrieve_corpus(self, request, course_pk=None):
        """GET /api/courses/courses/<course_pk>/corpus/ — corpus + sources."""
        try:
            corpus = self._get_or_create_corpus(course_pk)
        except Course.DoesNotExist:
            return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CourseCorpusSerializer(corpus).data)

    def add_source(self, request, course_pk=None):
        """POST /api/courses/courses/<course_pk>/corpus/sources/ — admin only."""
        try:
            corpus = self._get_or_create_corpus(course_pk)
        except Course.DoesNotExist:
            return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = CorpusSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            source = serializer.save(corpus=corpus)
        except Exception as exc:
            # Most likely the (corpus, book_stem) uniqueness constraint.
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Auto-index the selected book into this course's corpus (background on AI).
        self._trigger_index(corpus, course_pk, source)
        return Response(CorpusSourceSerializer(source).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _trigger_index(corpus, course_pk, source):
        """Fire the AI corpus indexer for a source; record the initial status."""
        try:
            resp = requests.post(
                f"{_ai_url().rstrip('/')}/corpus/index",
                json={"book_stem": source.book_stem,
                      "corpus_id": corpus.corpus_id, "course_id": str(course_pk)},
                headers=_svc_headers(), timeout=30,
            )
            if resp.status_code == 200:
                source.index_status = resp.json().get("status", "indexing")
            else:
                source.index_status = "failed"
        except Exception:
            source.index_status = "failed"
        source.save(update_fields=["index_status"])

    def available_books(self, request, course_pk=None):
        """GET /api/courses/courses/<course_pk>/corpus/available-books/ — ADMIN.
        Lists uploaded/indexed books to choose from (proxies the AI service)."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        try:
            corpus = self._get_or_create_corpus(course_pk)
        except Course.DoesNotExist:
            return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            resp = requests.get(
                f"{_ai_url().rstrip('/')}/corpus/available-books",
                params={"corpus_id": corpus.corpus_id}, headers=_svc_headers(), timeout=30,
            )
            return Response(resp.json(), status=resp.status_code)
        except requests.exceptions.ConnectionError:
            return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def upload_book(self, request, course_pk=None):
        """POST /api/courses/courses/<course_pk>/corpus/upload/ — ADMIN.
        Forwards a PDF upload to the AI service so it can be selected/indexed."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "file is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            resp = requests.post(
                f"{_ai_url().rstrip('/')}/corpus/upload",
                files={"file": (upload.name, upload.read(), upload.content_type or "application/pdf")},
                headers=_svc_headers(), timeout=120,
            )
            return Response(resp.json(), status=resp.status_code)
        except requests.exceptions.ConnectionError:
            return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def index_status(self, request, course_pk=None):
        """GET /api/courses/courses/<course_pk>/corpus/index-status/?book_stem= —
        ADMIN. Live indexing status; also syncs it onto the CorpusSource row."""
        if not _is_admin(request.user):
            return Response({"error": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
        try:
            corpus = self._get_or_create_corpus(course_pk)
        except Course.DoesNotExist:
            return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)
        book_stem = request.query_params.get("book_stem", "")
        try:
            resp = requests.get(
                f"{_ai_url().rstrip('/')}/corpus/index-status",
                params={"corpus_id": corpus.corpus_id, "book_stem": book_stem},
                headers=_svc_headers(), timeout=30,
            )
            data = resp.json()
            # Sync the durable status onto the source row for the UI list.
            src = CorpusSource.objects.filter(corpus=corpus, book_stem=book_stem).first()
            if src and data.get("status") in dict(CorpusSource.INDEX_STATUS):
                src.index_status = data["status"]
                src.chunk_count = int(data.get("chunks", src.chunk_count) or src.chunk_count)
                src.save(update_fields=["index_status", "chunk_count"])
            return Response(data, status=resp.status_code)
        except requests.exceptions.ConnectionError:
            return Response({"error": "AI service offline"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def remove_source(self, request, course_pk=None, pk=None):
        """DELETE /api/courses/courses/<course_pk>/corpus/sources/<pk>/ — admin."""
        deleted, _ = CorpusSource.objects.filter(
            corpus__course_id=course_pk, pk=pk,
        ).delete()
        if not deleted:
            return Response({"error": "Source not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

from rest_framework import generics
from django.db import transaction
from apps.core.permissions import IsVerifiedAdmin

class PlacementQuestionViewSet(viewsets.ModelViewSet):
    """CRUD for per-course placement questions (admin only for write)."""
    serializer_class = PlacementQuestionSerializer
    pagination_class = None

    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        if not course_id:
            return PlacementQuestion.objects.none()
        return PlacementQuestion.objects.filter(course_id=course_id)

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.IsAuthenticated()]
        return [IsVerifiedAdmin()]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return PlacementQuestionWriteSerializer
        return PlacementQuestionSerializer

    def perform_create(self, serializer):
        course_id = self.kwargs['course_pk']
        from django.db.models import Max
        max_order = PlacementQuestion.objects.filter(
            course_id=course_id
        ).aggregate(m=Max('order'))['m'] or 0
        
        from apps.core.audit import log_admin_action
        pq = serializer.save(course_id=course_id, order=max_order + 1)
        log_admin_action(self.request, action="create_placement_question", target_type="PlacementQuestion", target_id=str(pq.id))

    def perform_update(self, serializer):
        from apps.core.audit import log_admin_action
        pq = serializer.save()
        log_admin_action(self.request, action="update_placement_question", target_type="PlacementQuestion", target_id=str(pq.id))

    def perform_destroy(self, instance):
        from apps.core.audit import log_admin_action
        log_admin_action(self.request, action="delete_placement_question", target_type="PlacementQuestion", target_id=str(instance.id))
        instance.delete()

    @action(detail=False, methods=['post'], url_path='bulk-save')
    def bulk_save(self, request, course_pk=None):
        """Save AI-generated questions into the course.

        Accepts either a bare JSON array of questions, or the
        ``{"questions": [...]}`` envelope the frontend sends.
        """
        questions_data = request.data
        if isinstance(questions_data, dict):
            questions_data = questions_data.get("questions", questions_data.get("results"))
        if not isinstance(questions_data, list):
            return Response(
                {"error": "Expected a list of questions (or {\"questions\": [...]})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.db.models import Max
        from rest_framework.exceptions import ValidationError
        with transaction.atomic():
            # Append after the current max order (0-based ``i`` would collide with
            # existing rows). This is additive — existing questions are kept.
            base_order = PlacementQuestion.objects.filter(
                course_id=course_pk
            ).aggregate(m=Max('order'))['m'] or 0
            for i, q_data in enumerate(questions_data):
                order = base_order + 1 + i
                serializer = PlacementQuestionWriteSerializer(data={**q_data, 'order': order})
                if not serializer.is_valid():
                    # Identify the offending draft so the editor can surface it,
                    # instead of an opaque non_field_errors. Raised inside the
                    # atomic block, so nothing is partially saved.
                    raise ValidationError({
                        "error": f"Question {i + 1} of {len(questions_data)} is invalid.",
                        "question": str(q_data.get("question", ""))[:120],
                        "detail": serializer.errors,
                    })
                serializer.save(course_id=course_pk, order=order)

        # Return the FULL set for the course so the editor reflects every question
        # (not just the newly-added drafts, which would hide the existing ones).
        full = PlacementQuestion.objects.filter(course_id=course_pk).order_by('order')
        return Response(
            PlacementQuestionSerializer(full, many=True).data,
            status=status.HTTP_200_OK,
        )

class StudentPlacementTestView(generics.ListAPIView):
    """Return the pre-authored placement questions for a course."""
    serializer_class = PlacementQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        course_id = self.kwargs['course_pk']
        return PlacementQuestion.objects.filter(course_id=course_id)

    def list(self, request, *args, **kwargs):
        import random
        queryset = list(self.get_queryset())
        random.shuffle(queryset)
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        for q in data:
            q.pop('correct_answer', None)
        return Response(data)

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def score_placement_submission(request, course_pk):
    """Score student answers against DB-stored correct answers."""
    answers = request.data.get("answers", {})
    questions = PlacementQuestion.objects.filter(
        course_id=course_pk,
        id__in=answers.keys(),
    ).values('id', 'correct_answer', 'topic', 'concept_id')
    
    results = {}
    for q in questions:
        student_ans = answers.get(str(q['id']), answers.get(q['id'], ''))
        results[str(q['id'])] = {
            'correct': student_ans.strip() == q['correct_answer'].strip(),
            'correct_answer': q['correct_answer'],
            'topic': q['topic'],
            'concept_id': q['concept_id'],
        }
    return Response(results)
