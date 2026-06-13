"""
Team matchmaking over concept-mastery vectors (Batch 1 `concept_mastery`).

Pure scoring + greedy grouping. No LLM. The match score blends:

  match = w1*complementarity  (A weak where B strong)
        + w2*interest_similarity
        + w3*cohort_fit        (pace / age band proxy)
        - w4*redundancy        (both weak in the same critical concept)

The queue never deadlocks: when a student's fill window expires (or no one
else is enrolled), the best available team is formed — even a team of one.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# Scoring weights
W_COMPLEMENT = 0.45
W_INTEREST = 0.20
W_COHORT = 0.20
W_REDUNDANCY = 0.30

# A concept score at/below this is "weak"; at/above is "strong".
WEAK_THRESHOLD = 0.45
STRONG_THRESHOLD = 0.65

# How long a student waits before we form the best available team.
DEFAULT_FILL_WINDOW = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Mastery access
# ---------------------------------------------------------------------------

def _get_mastery(student) -> dict:
    """Return {concept_id: score} for a student from their learning profile."""
    from apps.progress.models import StudentLearningProfile
    profile = StudentLearningProfile.objects.filter(student=student).first()
    if not profile:
        return {}
    cm = profile.concept_mastery or {}
    return {k: float(v.get("score", 0.5)) for k, v in cm.items() if isinstance(v, dict)}


def _get_interests(student) -> set[str]:
    """Interest tags from user preferences (best-effort proxy)."""
    prefs = getattr(student, "preferences", None) or {}
    interests = prefs.get("interests") or prefs.get("tags") or []
    if isinstance(interests, str):
        interests = [interests]
    style = prefs.get("learning_style")
    if style:
        interests = list(interests) + [f"style:{style}"]
    return {str(i).lower() for i in interests}


def _get_pace(student, capstone) -> float:
    """
    Pace proxy in [0,1] from placement score on this capstone's course.
    Used for cohort_fit. Neutral 0.5 when unknown.
    """
    from apps.courses.models import Enrollment
    enr = Enrollment.objects.filter(student=student, course=capstone.course).first()
    if enr and enr.placement_score is not None:
        return max(0.0, min(1.0, float(enr.placement_score) / 100.0))
    return 0.5


# ---------------------------------------------------------------------------
# Pairwise scoring
# ---------------------------------------------------------------------------

def _complementarity(ma: dict, mb: dict) -> float:
    """A is weak where B is strong (and vice versa) → high complementarity."""
    concepts = set(ma) | set(mb)
    if not concepts:
        return 0.0
    total = 0.0
    for c in concepts:
        a = ma.get(c, 0.5)
        b = mb.get(c, 0.5)
        # reward one weak + one strong
        if a <= WEAK_THRESHOLD and b >= STRONG_THRESHOLD:
            total += (b - a)
        elif b <= WEAK_THRESHOLD and a >= STRONG_THRESHOLD:
            total += (a - b)
    return total / len(concepts)


def _redundancy(ma: dict, mb: dict) -> float:
    """Both weak in the same concept → redundancy (bad)."""
    concepts = set(ma) | set(mb)
    if not concepts:
        return 0.0
    both_weak = sum(
        1 for c in concepts
        if ma.get(c, 0.5) <= WEAK_THRESHOLD and mb.get(c, 0.5) <= WEAK_THRESHOLD
    )
    return both_weak / len(concepts)


def _interest_similarity(ia: set[str], ib: set[str]) -> float:
    """Jaccard similarity of interest tags."""
    if not ia and not ib:
        return 0.5  # neutral when unknown
    union = ia | ib
    if not union:
        return 0.5
    return len(ia & ib) / len(union)


def _cohort_fit(pa: float, pb: float) -> float:
    """Closer pace → better cohort fit."""
    return 1.0 - abs(pa - pb)


def pair_score(a_ctx: dict, b_ctx: dict) -> float:
    """Compute the blended match score for two student contexts."""
    comp = _complementarity(a_ctx["mastery"], b_ctx["mastery"])
    interest = _interest_similarity(a_ctx["interests"], b_ctx["interests"])
    cohort = _cohort_fit(a_ctx["pace"], b_ctx["pace"])
    redundancy = _redundancy(a_ctx["mastery"], b_ctx["mastery"])
    return round(
        W_COMPLEMENT * comp
        + W_INTEREST * interest
        + W_COHORT * cohort
        - W_REDUNDANCY * redundancy,
        4,
    )


# ---------------------------------------------------------------------------
# Context build
# ---------------------------------------------------------------------------

def build_context(student, capstone) -> dict:
    return {
        "student": student,
        "mastery": _get_mastery(student),
        "interests": _get_interests(student),
        "pace": _get_pace(student, capstone),
    }


def _explain(a_ctx: dict, b_ctx: dict) -> str:
    """One-line 'why' for a recommended teammate."""
    comp = _complementarity(a_ctx["mastery"], b_ctx["mastery"])
    interest = _interest_similarity(a_ctx["interests"], b_ctx["interests"])
    cohort = _cohort_fit(a_ctx["pace"], b_ctx["pace"])
    bits = []
    if comp > 0.05:
        bits.append("complementary strengths")
    if interest > 0.5:
        bits.append("shared interests")
    if cohort > 0.7:
        bits.append("similar pace")
    return ", ".join(bits) or "available teammate"


# ---------------------------------------------------------------------------
# Recommendations + grouping
# ---------------------------------------------------------------------------

def recommend_teammates(student, capstone, candidates, top_n: int = 3) -> list[dict]:
    """
    Rank candidate students for `student`. Returns
    [{student_id, username, score, why}] sorted by score desc.
    """
    a_ctx = build_context(student, capstone)
    scored = []
    for cand in candidates:
        if cand.id == student.id:
            continue
        b_ctx = build_context(cand, capstone)
        scored.append({
            "student_id": cand.id,
            "username": cand.username,
            "score": pair_score(a_ctx, b_ctx),
            "why": _explain(a_ctx, b_ctx),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def greedy_group(contexts: list[dict], team_cap: int) -> list[list[dict]]:
    """
    Greedy grouping: seed a team with the unassigned student, then repeatedly
    add whichever remaining student maximizes average pairwise score with the
    current team, until the team reaches team_cap or no one is left.
    """
    remaining = list(contexts)
    teams: list[list[dict]] = []

    while remaining:
        seed = remaining.pop(0)
        team = [seed]
        while len(team) < team_cap and remaining:
            best_idx, best_score = None, float("-inf")
            for i, cand in enumerate(remaining):
                avg = sum(pair_score(m, cand) for m in team) / len(team)
                if avg > best_score:
                    best_idx, best_score = i, avg
            if best_idx is None:
                break
            team.append(remaining.pop(best_idx))
        teams.append(team)
    return teams


# ---------------------------------------------------------------------------
# Queue processing — never deadlocks
# ---------------------------------------------------------------------------

def process_queue(capstone, force: bool = False) -> list:
    """
    Form teams from the waiting queue for a capstone.

    - If enough students are waiting, group them up to team_cap.
    - If `force` (admin) or any entry's fill window has expired, form the best
      available team from whoever is waiting — even a single-member team.

    Returns the list of Team objects created.
    """
    from .models import MatchmakingQueueEntry, Team

    waiting = list(
        MatchmakingQueueEntry.objects.filter(capstone=capstone, status="waiting")
        .select_related("student")
    )
    if not waiting:
        return []

    now = timezone.now()
    any_expired = force or any(
        e.fill_window_expires_at and e.fill_window_expires_at <= now for e in waiting
    )

    team_cap = max(1, capstone.team_cap)

    # Only form teams when we can fill at least one full team, OR the window has
    # expired (then we form whatever we can, down to a team of one).
    if not any_expired and len(waiting) < team_cap:
        return []

    contexts = [{**build_context(e.student, capstone), "entry": e} for e in waiting]
    groups = greedy_group(contexts, team_cap)

    # Without forcing, drop trailing under-sized groups so students keep waiting
    # for a fuller team rather than being prematurely placed.
    if not any_expired:
        groups = [g for g in groups if len(g) == team_cap]

    created = []
    for group in groups:
        team = Team.objects.create(capstone=capstone, status="active")
        members = [ctx["student"] for ctx in group]
        team.members.set(members)
        if not team.name:
            team.name = f"Team {team.pk}"
            team.save(update_fields=["name"])
        for ctx in group:
            entry = ctx["entry"]
            entry.status = "matched"
            entry.team = team
            entry.save(update_fields=["status", "team"])
        created.append(team)
        logger.info("Formed %s with %s members for capstone %s", team, len(members), capstone.id)

        # Advisory only — generate the suggested division of labor in the
        # background once a real team (>=2) forms. Non-fatal: the team stands
        # regardless of whether this succeeds.
        if len(members) >= 2:
            try:
                from .team_roles import trigger_async
                trigger_async(team)
            except Exception:
                logger.exception("could not trigger role advice for %s", team)

    return created
