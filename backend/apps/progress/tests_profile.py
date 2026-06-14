"""Tests for the single, additive learning-profile writer (Batch 7)."""

import threading

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.progress.models import StudentLearningProfile
from apps.progress import profile_service


def _claim(field, value, source="session", conf=0.6):
    return {"field": field, "value": value, "source": source, "confidence": conf,
            "evidence": "t", "created_at": "2026-06-14T00:00:00+00:00"}


def _live(pd, field=None):
    cs = [c for c in pd["claims"] if not c.get("superseded")]
    return [c for c in cs if field is None or c["field"] == field]


class ApplyClaimsTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="p1", email="p1@x.com", password="pw")

    def test_additive_no_clobber_between_sources(self):
        profile_service.apply_claims(self.u.id, [_claim("pace", "needs slower pace", "session")])
        pd = profile_service.apply_claims(self.u.id, [_claim("recommended_approach", "use analogies", "lab", 0.3)])
        fields = {c["field"] for c in _live(pd)}
        assert {"pace", "recommended_approach"} <= fields  # neither lost the other's field

    def test_competence_field_is_rejected(self):
        pd = profile_service.apply_claims(self.u.id, [
            _claim("topics_of_difficulty", "loops"),       # competence — must be dropped
            _claim("preferred_modality", "visual"),
        ])
        fields = {c["field"] for c in pd["claims"]}
        assert "topics_of_difficulty" not in fields
        assert "preferred_modality" in fields

    def test_higher_authority_supersedes_lower(self):
        # Lab low-confidence process mistake, then problem_set about the same thing.
        profile_service.apply_claims(self.u.id, [
            _claim("recurrent_process_mistake", "off by one in loops", "lab", 0.3)])
        pd = profile_service.apply_claims(self.u.id, [
            _claim("recurrent_process_mistake", "off-by-one in loop bounds", "problem_set", 0.7)])
        live = _live(pd, "recurrent_process_mistake")
        assert len(live) == 1 and live[0]["source"] == "problem_set"
        # the lab claim is retained but superseded (audit), not lost
        all_lab = [c for c in pd["claims"] if c["source"] == "lab" and c["field"] == "recurrent_process_mistake"]
        assert all_lab and all_lab[0]["superseded"] is True

    def test_singleton_field_keeps_one_live_claim(self):
        profile_service.apply_claims(self.u.id, [_claim("pace", "slow", "session", 0.5)])
        pd = profile_service.apply_claims(self.u.id, [_claim("pace", "fast", "problem_set", 0.7)])
        live = _live(pd, "pace")
        assert len(live) == 1 and live[0]["value"] == "fast"

    def test_summary_is_session_authored_only(self):
        profile_service.apply_claims(self.u.id, [_claim("pace", "slow")], summary="from lab", summary_source="lab")
        p = StudentLearningProfile.objects.get(student=self.u)
        assert p.profile_summary == ""  # lab cannot author the summary
        profile_service.apply_claims(self.u.id, [], summary="from session", summary_source="session")
        p.refresh_from_db()
        assert p.profile_summary == "from session"


class ProfileApplyEndpointTests(TestCase):
    def test_endpoint_applies_claims(self):
        u = User.objects.create_user(username="pe", email="pe@x.com", password="pw")
        client = APIClient()
        client.force_authenticate(user=u)
        resp = client.post("/api/progress/profile/apply/", {
            "claims": [_claim("engagement", "high on code examples", "session")],
        }, format="json")
        assert resp.status_code == 200, resp.content
        fields = {c["field"] for c in resp.json()["profile_data"]["claims"]}
        assert "engagement" in fields


class ProfileConcurrencyTests(TransactionTestCase):
    def test_concurrent_profilers_do_not_lose_fields(self):
        u = User.objects.create_user(username="pc", email="pc@x.com", password="pw")
        StudentLearningProfile.objects.create(student=u)

        def worker(claim):
            try:
                profile_service.apply_claims(u.id, [claim])
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=(_claim("pace", "slow", "session"),))
        t2 = threading.Thread(target=worker, args=(_claim("recommended_approach", "use diagrams", "lab", 0.3),))
        t1.start(); t2.start(); t1.join(); t2.join()

        pd = StudentLearningProfile.objects.get(student=u).profile_data
        fields = {c["field"] for c in pd["claims"]}
        assert {"pace", "recommended_approach"} <= fields  # both writers' fields survived
