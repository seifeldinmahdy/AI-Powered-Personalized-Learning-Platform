"""Tests for the single, event-sourced concept-mastery writer (Batch 6)."""

import threading

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.courses.models import Course, Concept
from apps.progress.models import StudentLearningProfile, ConceptMasteryEvent
from apps.progress import mastery_service


class FoldTests(TestCase):
    def test_record_stores_source_and_alpha(self):
        u = User.objects.create_user(username="s1", email="s1@x.com", password="pw")
        mastery_service.record_events(u.id, [
            {"concept_id": "10", "outcome": 1.0, "source": "problem_set", "alpha": 0.3},
        ])
        ev = ConceptMasteryEvent.objects.get(student=u, concept_id="10")
        assert ev.source == "problem_set" and ev.alpha == 0.3
        cm = StudentLearningProfile.objects.get(student=u).concept_mastery
        assert "10" in cm and cm["10"]["score"] > 0.5  # 0.5 prior + pass

    def test_projection_reproducible_from_event_log(self):
        u = User.objects.create_user(username="s2", email="s2@x.com", password="pw")
        for o in (1.0, 0.0, 1.0):
            mastery_service.record_events(u.id, [
                {"concept_id": "7", "outcome": o, "source": "problem_set", "alpha": 0.3},
            ])
        stored = StudentLearningProfile.objects.get(student=u).concept_mastery["7"]
        rows = list(ConceptMasteryEvent.objects.filter(student=u, concept_id="7").order_by("created_at", "id"))
        refolded = mastery_service.fold_events(rows)
        assert refolded["score"] == stored["score"]
        assert refolded["evidence"] == stored["evidence"] == 3

    def test_lower_alpha_moves_score_less(self):
        u = User.objects.create_user(username="s3", email="s3@x.com", password="pw")
        mastery_service.record_events(u.id, [{"concept_id": "1", "outcome": 1.0, "source": "problem_set", "alpha": 0.1}])
        mastery_service.record_events(u.id, [{"concept_id": "2", "outcome": 1.0, "source": "problem_set", "alpha": 0.9}])
        cm = StudentLearningProfile.objects.get(student=u).concept_mastery
        assert cm["1"]["score"] < cm["2"]["score"]  # down-weighted update moved less

    def test_assist_only_is_not_no_data(self):
        u = User.objects.create_user(username="s4", email="s4@x.com", password="pw")
        mastery_service.record_events(u.id, [
            {"concept_id": "5", "outcome": 0.3, "source": "capstone_assist", "alpha": 0.1, "evidence_delta": 0},
        ])
        cm = StudentLearningProfile.objects.get(student=u).concept_mastery
        assert "5" in cm                       # the concept HAS an entry (data exists)
        assert cm["5"]["evidence"] == 0        # but no independent evidence
        assert cm["5"]["score"] < 0.5          # score moved down

    def test_backfill_seed_roundtrips_exact_entry(self):
        # An alpha=1.0 backfill seed must fold back to the exact prior entry.
        from types import SimpleNamespace
        prior = {"score": 0.83, "evidence": 4, "trend": "up", "linked_mistakes": ["off_by_one"]}
        seed = SimpleNamespace(
            outcome=0.83, alpha=1.0, evidence_delta=4, source="backfill", mistake_tag="",
            seed_meta={"linked_mistakes": ["off_by_one"], "trend": "up"}, created_at=None,
        )
        folded = mastery_service.fold_events([seed])
        assert folded["score"] == prior["score"]
        assert folded["evidence"] == prior["evidence"]
        assert folded["trend"] == prior["trend"]
        assert folded["linked_mistakes"] == prior["linked_mistakes"]


class MasteryEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.student = User.objects.create_user(username="st", email="st@x.com", password="pw", role="student")
        self.course = Course.objects.create(title="Py")
        self.loops = Concept.objects.create(course=self.course, label="Loops", slug="loops")

    def test_topic_mapping_records_above_floor_and_drops_below(self):
        self.client.force_authenticate(user=self.student)
        resp = self.client.post("/api/progress/mastery/record/", {
            "events": [
                {"topic": "Loops", "course_id": str(self.course.id), "outcome": 1.0, "source": "checkpoint"},
                {"topic": "Quantum chromodynamics", "course_id": str(self.course.id), "outcome": 1.0, "source": "checkpoint"},
            ],
        }, format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        # "Loops" maps to the concept; the unrelated topic is dropped (below floor).
        assert str(self.loops.id) in body["updated"]
        assert body["dropped"] >= 1

    def test_history_explains_movement(self):
        mastery_service.record_events(self.student.id, [
            {"concept_id": str(self.loops.id), "outcome": 1.0, "source": "assessment", "alpha": 1.0},
            {"concept_id": str(self.loops.id), "outcome": 0.0, "source": "problem_set", "alpha": 0.3},
        ])
        self.client.force_authenticate(user=self.student)
        resp = self.client.get(f"/api/progress/concept-mastery/{self.loops.id}/history/")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert [e["source"] for e in events] == ["assessment", "problem_set"]
        assert all("resulting_score" in e for e in events)


class MasteryConcurrencyTests(TransactionTestCase):
    """Two concurrent updates to the same concept must BOTH be reflected."""

    def test_concurrent_updates_do_not_lose_writes(self):
        student = User.objects.create_user(username="cc", email="cc@x.com", password="pw")
        StudentLearningProfile.objects.create(student=student)  # pre-create to avoid get_or_create race

        def worker(outcome):
            try:
                mastery_service.record_events(student.id, [
                    {"concept_id": "99", "outcome": outcome, "source": "problem_set", "alpha": 0.3},
                ])
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=(1.0,))
        t2 = threading.Thread(target=worker, args=(0.0,))
        t1.start(); t2.start(); t1.join(); t2.join()

        # Both appends survived (no lost update), and the projection reflects both.
        assert ConceptMasteryEvent.objects.filter(student=student, concept_id="99").count() == 2
        cm = StudentLearningProfile.objects.get(student=student).concept_mastery
        assert cm["99"]["evidence"] == 2
