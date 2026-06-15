"""Batch 11b — emotion governance: consent, withdrawal+purge, and the
grade-adjacency guarantee (behavioral + a structural source-scan guard)."""

import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.courses.models import Course, Module, Lesson, Enrollment, Concept
from apps.progress.models import EmotionConsent, StudentLearningProfile
from apps.progress import mastery_service, profile_service


class ConsentEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="e1", email="e1@x.com", password="pw")
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_off_by_default(self):
        d = self.client.get("/api/progress/emotion-consent/").json()
        self.assertFalse(d["granted"])
        self.assertTrue(d["required"])

    def test_grant_then_state_granted(self):
        r = self.client.post("/api/progress/emotion-consent/grant/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["granted"])
        c = EmotionConsent.objects.get(student=self.user)
        self.assertTrue(c.granted and c.granted_at and c.policy_version)

    def test_withdraw_sets_state_and_calls_ai_purge(self):
        self.client.post("/api/progress/emotion-consent/grant/", {}, format="json")
        with mock.patch("requests.post") as m_post:
            m_post.return_value.status_code = 200
            m_post.return_value.json.return_value = {"purged": 5}
            r = self.client.post("/api/progress/emotion-consent/withdraw/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["granted"])
        self.assertEqual(r.json()["purged"], 5)
        c = EmotionConsent.objects.get(student=self.user)
        self.assertFalse(c.granted)
        self.assertIsNotNone(c.withdrawn_at)
        # The AI raw-emotion purge was invoked with this student.
        self.assertTrue(m_post.called)
        self.assertIn("/emotion/purge", m_post.call_args.args[0])

    def test_withdraw_survives_ai_purge_failure(self):
        self.client.post("/api/progress/emotion-consent/grant/", {}, format="json")
        with mock.patch("requests.post", side_effect=Exception("AI down")):
            r = self.client.post("/api/progress/emotion-consent/withdraw/", {}, format="json")
        self.assertEqual(r.status_code, 200)  # consent still withdrawn server-side
        self.assertFalse(r.json()["granted"])


class GradeAdjacencyTests(TestCase):
    """Emotion must never change grade-adjacent output. Behavioral lock."""

    def setUp(self):
        self.user = User.objects.create_user(username="g1", email="g1@x.com", password="pw")
        self.course = Course.objects.create(title="C", total_lessons_count=1)
        self.concept = Concept.objects.create(course=self.course, label="Loops", slug="loops")
        StudentLearningProfile.objects.create(student=self.user)

    def test_emotion_profile_claim_does_not_move_concept_mastery(self):
        # Grade signal: a problem-set outcome folds into concept_mastery.
        mastery_service.record_events(self.user.id, [
            {"concept_id": str(self.concept.id), "outcome": 0.0, "source": "problem_set", "alpha": 1.0},
        ])
        before = dict(StudentLearningProfile.objects.get(student=self.user).concept_mastery)

        # Emotion enters ONLY as a low-confidence, qualitative profile claim
        # (Batch 7). It must not touch concept_mastery (the grade signal).
        profile_service.apply_claims(self.user.id, [{
            "field": "emotional_tendencies", "value": "appeared disengaged on loops",
            "source": "session", "confidence": 0.3, "evidence": "fer", "created_at": "2026-06-15T00:00:00+00:00",
        }])
        after = dict(StudentLearningProfile.objects.get(student=self.user).concept_mastery)
        self.assertEqual(before, after)  # identical grade output regardless of emotion

    def test_emotion_competence_claim_is_rejected(self):
        # Even if an emotion-derived claim tried to assert competence, Batch 7
        # rejects it — so it can never become a grade signal.
        pd = profile_service.apply_claims(self.user.id, [{
            "field": "topics_of_difficulty", "value": "loops", "source": "session",
            "confidence": 0.3, "evidence": "fer", "created_at": "2026-06-15T00:00:00+00:00",
        }])
        fields = {c["field"] for c in pd["claims"]}
        self.assertNotIn("topics_of_difficulty", fields)


class StructuralGuardTests(TestCase):
    """No grade-path module may read emotion. Fails if someone wires it in."""

    # The COMPLETE current grade-path module list.
    GRADE_PATH_MODULES = [
        "backend/apps/progress/mastery_service.py",
        "backend/apps/progress/completion_service.py",
        "backend/apps/artifacts/scoring.py",
        "backend/apps/capstone/grading.py",
        "backend/apps/courses/certificate.py",
        "backend/apps/gamification/signals.py",
        "ai_service/services/problem_set_service.py",
    ]
    # capstone/views.py and courses/views.py contain grade logic among other
    # views; scan their grade functions' file too (whole-file scan is a strict
    # superset — if 'emotion' is absent from the whole file, it's absent from the
    # grade functions). They're included below.
    GRADE_PATH_MODULES += [
        "backend/apps/capstone/views.py",
        "backend/apps/courses/views.py",
    ]

    # Matches 'emotion', 'fused_emotion', 'student_emotion' (underscore is fine)
    # but NOT 'demotion'/'remotion' (preceded by a letter). \b would wrongly MISS
    # 'fused_emotion' (underscore is a word char), so we use a letter lookbehind.
    EMOTION_PAT = re.compile(r"(?<![a-zA-Z])emotion", re.IGNORECASE)

    def test_grade_paths_contain_no_emotion_reference(self):
        repo_root = Path(settings.BASE_DIR).parent
        pat = self.EMOTION_PAT
        offenders = []
        for rel in self.GRADE_PATH_MODULES:
            p = repo_root / rel
            self.assertTrue(p.exists(), f"grade-path module missing from scan list: {rel}")
            if pat.search(p.read_text(encoding="utf-8")):
                offenders.append(rel)
        self.assertEqual(offenders, [], f"emotion referenced in grade path(s): {offenders}")

    def test_guard_pattern_matches_real_refs_not_substrings(self):
        pat = self.EMOTION_PAT
        # Must NOT match letter-prefixed look-alikes…
        self.assertIsNone(pat.search("demotion remotion locomotion"))
        # …but MUST catch the real ways emotion is referenced in code.
        self.assertIsNotNone(pat.search("the fused_emotion value"))
        self.assertIsNotNone(pat.search("student_emotion=x"))
        self.assertIsNotNone(pat.search("Emotion label"))
