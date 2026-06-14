"""Top-down LLM curriculum designer.

Replaces the bottom-up clustering pipeline (SectionBuilder → GraphBuilder →
ordering.py) with a single LLM call that designs the entire curriculum.

The LLM receives every unique topic tag from ChromaDB and returns a
complete pedagogically ordered JSON curriculum with sessions, titles,
topic groupings, and difficulty tiers.

Uses the existing ``OllamaClient`` from ``llm.naming``.
"""

from __future__ import annotations

import math
import re
from difflib import SequenceMatcher

import structlog

from pathway.llm.naming import OllamaClient
from pathway.llm.prompts import CURRICULUM_SYSTEM_PROMPT, CURRICULUM_USER_TEMPLATE
from pathway.models.schemas import LLMCurriculumSession

logger = structlog.get_logger(__name__)

# Fixed seed for the curriculum LLM call. Combined with temperature=0 this asks
# the provider for greedy/reproducible decoding; the generator additionally
# captures and replays the raw proposal so determinism never depends on the
# provider actually being bit-reproducible.
CURRICULUM_SEED = 1234

# ── Topic normalisation (reused from section_builder pattern) ────

_STRIP_RE = re.compile(r"[^a-z0-9\s]")


def _normalise(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    normed = raw.lower().strip()
    normed = _STRIP_RE.sub("", normed)
    return re.sub(r"\s+", " ", normed).strip()


def _fuzzy_match(query: str, candidates: list[str], threshold: float = 0.80) -> str | None:
    """Return the best fuzzy match from *candidates* for *query*, or None."""
    query_n = _normalise(query)
    if not query_n:
        return None

    best_score = 0.0
    best_match: str | None = None

    for candidate in candidates:
        cand_n = _normalise(candidate)
        if query_n == cand_n:
            return candidate  # exact normalised match

        score = SequenceMatcher(None, query_n, cand_n).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate

    return best_match


# ── Boilerplate filter ───────────────────────────────────────────

_BOILERPLATE_TOPICS = {
    "index", "index entries", "glossary", "appendix", "bibliography",
    "references", "table of contents", "contents", "preface",
    "acknowledgments", "creative commons", "creative commons licensing",
}


def _is_boilerplate(topic: str) -> bool:
    """Return True if *topic* is textbook boilerplate, not course content."""
    return _normalise(topic) in _BOILERPLATE_TOPICS


# ── Intent inference ─────────────────────────────────────────────


def _infer_course_intent(
    topics: list[str],
    book_titles: list[str] | None = None,
) -> str:
    """Best-effort inference of course intent from available data."""
    parts: list[str] = []

    if book_titles:
        parts.append("Based on the textbook(s): " + ", ".join(book_titles) + ".")

    sample = topics[:20]
    if sample:
        parts.append(
            "Representative topics include: " + ", ".join(sample) + "."
        )

    return " ".join(parts) if parts else "Introduction to Computer Science"


# ── Prompt builder ───────────────────────────────────────────────


def _build_topic_listing(topics: list[str]) -> str:
    """Format topic list for the LLM prompt."""
    lines: list[str] = []
    for i, topic in enumerate(topics, 1):
        lines.append(f"  {i}. \"{topic}\"")
    return "\n".join(lines)


# ── Alphabetical fallback ───────────────────────────────────────


def _alphabetical_fallback(
    topics: list[str],
    topics_per_session: int | None = None,
    target_sessions: int = 15,
) -> list[LLMCurriculumSession]:
    """Group topics alphabetically into sessions as a safe fallback.

    By default the number of sessions is bounded to ``target_sessions`` by
    putting more topics per session as the topic count grows, so the fallback
    (like the LLM path) does not scale the session count with book size.
    An explicit ``topics_per_session`` overrides this (used by tests).
    """
    sorted_topics = sorted(topics, key=lambda t: t.lower())

    if topics_per_session is None:
        # Spread topics across at most ``target_sessions`` sessions.
        target = max(1, target_sessions)
        topics_per_session = max(1, math.ceil(len(sorted_topics) / target))

    sessions: list[LLMCurriculumSession] = []

    for i in range(0, len(sorted_topics), topics_per_session):
        batch = sorted_topics[i : i + topics_per_session]
        session_num = len(sessions) + 1
        sessions.append(
            LLMCurriculumSession(
                session_number=session_num,
                session_title=f"Topics: {batch[0]} – {batch[-1]}",
                topics=batch,
                difficulty="beginner",
            )
        )

    logger.warning(
        "curriculum_alphabetical_fallback",
        total_sessions=len(sessions),
        total_topics=len(topics),
    )
    return sessions


# ── Missing topic recovery ───────────────────────────────────────


def _assign_missing_topics(
    missing: list[str],
    sessions: list[LLMCurriculumSession],
) -> list[LLMCurriculumSession]:
    """Assign missing topics to the most semantically similar session.

    Uses embedding cosine similarity between the missing topic and
    each session title. Falls back to the last session if embeddings
    fail.
    """
    if not missing or not sessions:
        return sessions

    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        session_titles = [s.session_title for s in sessions]
        title_embeddings = model.encode(session_titles, normalize_embeddings=True)

        for topic in missing:
            topic_emb = model.encode([topic], normalize_embeddings=True)
            sims = topic_emb @ title_embeddings.T
            best_idx = int(np.argmax(sims[0]))
            sessions[best_idx].topics.append(topic)
            logger.info(
                "missing_topic_assigned",
                topic=topic,
                assigned_to=sessions[best_idx].session_title,
                similarity=float(sims[0][best_idx]),
            )
    except Exception as exc:
        logger.warning(
            "embedding_fallback_for_missing_topics",
            error=str(exc),
            count=len(missing),
        )
        # Fallback: just add to the last session
        for topic in missing:
            sessions[-1].topics.append(topic)

    return sessions


# ── Main function ────────────────────────────────────────────────


def clean_topic_list(topics: list[str]) -> list[str]:
    """Return topics with boilerplate removed (stable order preserved)."""
    return [t for t in topics if not _is_boilerplate(t)]


def propose_curriculum(
    client: OllamaClient,
    clean_topics: list[str],
    course_intent: str = "",
    book_titles: list[str] | None = None,
    max_retries: int = 3,
    timeout: int = 600,
    target_sessions: int = 15,
    min_sessions: int = 8,
    max_sessions: int = 25,
) -> dict:
    """LLM step ONLY: return the raw curriculum proposal dict (``{"sessions": [...]}``).

    Deterministic decoding is requested (temperature=0 + fixed seed). This raw
    proposal is what the caller hashes/stores and later REPLAYS — the plan is
    re-resolved deterministically from it, so generation never depends on the
    provider being bit-reproducible. Returns ``{}`` if the LLM never yields a
    usable proposal (caller falls back).
    """
    if not clean_topics:
        return {}

    effective_intent = course_intent.strip() or _infer_course_intent(clean_topics, book_titles)
    user_message = CURRICULUM_USER_TEMPLATE.format(
        course_intent=effective_intent,
        count=len(clean_topics),
        topic_listing=_build_topic_listing(clean_topics),
        target_sessions=target_sessions,
        min_sessions=min_sessions,
        max_sessions=max_sessions,
    )

    for attempt in range(1, max_retries + 1):
        try:
            result = client.chat_json(
                [
                    {"role": "system", "content": CURRICULUM_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                seed=CURRICULUM_SEED,
                timeout_override=timeout,
            )
            if isinstance(result.get("sessions"), list) and result["sessions"]:
                return result
            logger.warning("curriculum_invalid_response", attempt=attempt)
        except Exception as exc:
            logger.warning("curriculum_llm_error", attempt=attempt, error=str(exc))

    return {}


def resolve_curriculum(
    raw_proposal: dict,
    clean_topics: list[str],
    target_sessions: int = 15,
    max_sessions: int = 25,
) -> list[LLMCurriculumSession]:
    """DETERMINISTIC step: turn a raw proposal into a validated curriculum.

    Pure function of (raw_proposal, clean_topics) — no LLM, no randomness — so
    replaying a stored proposal always yields byte-identical structure. Falls
    back to a deterministic alphabetical grouping if the proposal is empty.
    """
    raw_sessions = (raw_proposal or {}).get("sessions", [])
    if not isinstance(raw_sessions, list) or not raw_sessions:
        return _alphabetical_fallback(clean_topics, target_sessions=target_sessions)

    parsed_sessions: list[LLMCurriculumSession] = []
    for raw in raw_sessions:
        try:
            parsed_sessions.append(LLMCurriculumSession(**raw))
        except Exception as parse_exc:
            logger.warning("curriculum_session_parse_error", error=str(parse_exc), raw=str(raw)[:200])

    if not parsed_sessions:
        return _alphabetical_fallback(clean_topics, target_sessions=target_sessions)

    validated_sessions = _validate_topics(parsed_sessions, clean_topics)

    used_topics: set[str] = set()
    for session in validated_sessions:
        used_topics.update(session.topics)
    missing = [t for t in clean_topics if t not in used_topics]
    if missing:
        validated_sessions = _assign_missing_topics(missing, validated_sessions)

    validated_sessions = [s for s in validated_sessions if s.topics]

    if len(validated_sessions) > max_sessions:
        validated_sessions = _merge_sessions_to_cap(validated_sessions, max_sessions)

    for i, session in enumerate(validated_sessions, 1):
        session.session_number = i

    logger.info(
        "curriculum_resolved",
        sessions=len(validated_sessions),
        total_topics=sum(len(s.topics) for s in validated_sessions),
    )
    return validated_sessions


def design_curriculum(
    client: OllamaClient,
    topics: list[str],
    course_intent: str = "",
    book_titles: list[str] | None = None,
    max_retries: int = 3,
    timeout: int = 600,
    target_sessions: int = 15,
    min_sessions: int = 8,
    max_sessions: int = 25,
) -> list[LLMCurriculumSession]:
    """Propose (LLM) then deterministically resolve a curriculum.

    Kept for back-compat / standalone use. The generator instead calls
    ``propose_curriculum`` + ``resolve_curriculum`` directly so it can capture,
    hash, store, and replay the raw proposal.
    """
    clean_topics = clean_topic_list(topics)
    if not clean_topics:
        return []
    raw = propose_curriculum(
        client, clean_topics, course_intent, book_titles,
        max_retries=max_retries, timeout=timeout,
        target_sessions=target_sessions, min_sessions=min_sessions, max_sessions=max_sessions,
    )
    return resolve_curriculum(raw, clean_topics, target_sessions=target_sessions, max_sessions=max_sessions)


# ── Session cap ──────────────────────────────────────────────────


def _merge_sessions_to_cap(
    sessions: list[LLMCurriculumSession],
    cap: int,
) -> list[LLMCurriculumSession]:
    """Merge consecutive sessions so at most ``cap`` remain.

    Consecutive (already pedagogically ordered) sessions are combined into
    ``cap`` groups as evenly as possible. The first session's title is kept
    for each merged group; topics and difficulties are concatenated.
    """
    if cap < 1 or len(sessions) <= cap:
        return sessions

    n = len(sessions)
    base, extra = divmod(n, cap)

    merged: list[LLMCurriculumSession] = []
    idx = 0
    for g in range(cap):
        size = base + (1 if g < extra else 0)
        group = sessions[idx : idx + size]
        idx += size

        topics: list[str] = []
        for s in group:
            topics.extend(s.topics)

        merged.append(
            LLMCurriculumSession(
                session_number=g + 1,
                session_title=group[0].session_title,
                topics=topics,
                difficulty=group[0].difficulty,
            )
        )

    return merged


# ── Topic validation ─────────────────────────────────────────────


def _validate_topics(
    sessions: list[LLMCurriculumSession],
    valid_topics: list[str],
) -> list[LLMCurriculumSession]:
    """Validate and clean topic strings in the LLM response.

    For each topic string the LLM used:
    - If it exactly matches a valid topic, keep it.
    - If it fuzzy-matches a valid topic, replace with the valid form.
    - If it matches nothing, remove it (invented topic).

    Also deduplicates — a topic can only appear in one session.
    """
    valid_set = set(valid_topics)
    used: set[str] = set()
    invented_count = 0

    for session in sessions:
        cleaned: list[str] = []
        for topic in session.topics:
            # Exact match
            if topic in valid_set and topic not in used:
                cleaned.append(topic)
                used.add(topic)
                continue

            # Fuzzy match
            remaining = [t for t in valid_topics if t not in used]
            match = _fuzzy_match(topic, remaining)
            if match and match not in used:
                cleaned.append(match)
                used.add(match)
                continue

            # No match — invented topic
            invented_count += 1
            logger.debug(
                "curriculum_invented_topic_removed",
                topic=topic,
                session=session.session_title,
            )

        session.topics = cleaned

    if invented_count:
        logger.info(
            "curriculum_validation_complete",
            invented_removed=invented_count,
            topics_assigned=len(used),
        )

    return sessions
