"""
Team role advisor — builds the payload for and caches the advisory "suggested
division of labor" on a Team.

Advisory only: the result is text guidance the team may ignore. It is NEVER read
by any scoring, verdict, or contribution-check path. Generation failure is
non-fatal — the team still forms; we just log it.
"""

from __future__ import annotations

import logging
import os
import threading

import requests
from django.conf import settings
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")


def _build_payload(team) -> dict:
    """Assemble rubric + per-member course-restricted concept_mastery."""
    from apps.courses.models import Concept
    from apps.progress.models import StudentLearningProfile

    capstone = team.capstone
    course_concepts = {
        str(c.id): c.label for c in Concept.objects.filter(course=capstone.course)
    }

    rubric_items = [
        {
            "text": item.text,
            "category": item.category,
            "concept_id": str(item.concept_id) if item.concept_id else None,
        }
        for item in capstone.rubric_items.all()
    ]

    members = []
    for user in team.members.all():
        profile = StudentLearningProfile.objects.filter(student=user).first()
        cm = (profile.concept_mastery or {}) if profile else {}
        restricted = {}
        for cid, label in course_concepts.items():
            entry = cm.get(cid)
            if isinstance(entry, dict):
                restricted[cid] = {
                    "label": label,
                    "score": entry.get("score"),
                    "evidence": entry.get("evidence", 0),
                }
        members.append({"handle": user.username, "mastery": restricted})

    return {
        "capstone_title": capstone.title,
        "brief": capstone.brief_text,
        "rubric_items": rubric_items,
        "members": members,
    }


def generate_for_team(team_id: int) -> dict | None:
    """
    (Re)generate and cache the advisory for a team. Returns the advice dict, or
    None when skipped/failed. Safe to call synchronously (refresh) or in a thread.
    """
    from .models import Team

    try:
        team = Team.objects.select_related("capstone").get(pk=team_id)
    except Team.DoesNotExist:
        return None

    if team.members.count() < 2:
        return None  # solo team — nothing to divide

    payload = _build_payload(team)
    try:
        resp = requests.post(
            f"{AI_SERVICE_URL}/capstone/team-roles",
            json=payload,
            headers={"X-Service-Key": settings.INTERNAL_SERVICE_KEY},
            timeout=90,
        )
        resp.raise_for_status()
        advice = resp.json()
    except Exception:
        logger.exception("team role advice generation failed for team %s", team_id)
        return None

    team.role_advice = advice
    team.role_advice_generated_at = dj_timezone.now()
    team.save(update_fields=["role_advice", "role_advice_generated_at"])
    return advice


def trigger_async(team) -> None:
    """Fire-and-forget generation (used at team formation). Non-fatal."""
    try:
        threading.Thread(target=generate_for_team, args=(team.id,), daemon=True).start()
    except Exception:
        logger.exception("could not start team role advice thread for team %s", team.id)
