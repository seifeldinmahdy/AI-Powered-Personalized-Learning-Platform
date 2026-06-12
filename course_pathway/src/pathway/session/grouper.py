"""Session Grouper — turns curriculum sections into learning sessions.

Design principle
----------------
A *session* is a pedagogical unit (one study sitting), so the **number of
sessions must reflect the conceptual structure of the course, not the raw
text volume of the source book**.  Two textbooks covering the same syllabus
at different verbosity should yield a similar number of sessions.

For that reason the grouper maps **one curriculum section → one session**
(the sections themselves come from the top-down LLM curriculum designer,
which already groups related topics into a bounded number of logical
sessions).  A hard ``max_sessions`` cap is enforced by merging
pedagogically-adjacent sections when the curriculum is unusually long.
This fully decouples the session count from book size:

    num_sessions = min(num_non_empty_sections, max_sessions)

Historically this module re-packed every chunk into fixed token-budgeted
sessions (3000–5000 tokens) and split large sections into "— Part 2/3/4…".
That made the session count scale linearly with book size (big books →
80+ sessions), which is what this design replaces.

Token counting (``len(text.split()) * 1.3``) is retained for *reporting*
``estimated_token_count`` only — it no longer drives the session count.
"""

from __future__ import annotations

import structlog

from pathway.models.schemas import (
    CourseChunk,
    DiscoveredSection,
    Session,
    SessionChunk,
)

logger = structlog.get_logger(__name__)


def _estimate_tokens(text: str) -> int:
    """Estimate the token count of *text* using a word-count heuristic.

    English text averages ~1.3 sub-word tokens per whitespace-delimited
    word with BPE tokenizers.  Used only for reporting per-session token
    counts; it does not influence how sessions are formed.
    """
    return int(len(text.split()) * 1.3)


class SessionGrouper:
    """Builds learning sessions from personalised curriculum sections.

    One non-empty section becomes one session.  If the curriculum has more
    sections than ``max_sessions``, consecutive sections are merged evenly
    so the final count never exceeds the cap — keeping the session count a
    function of course structure rather than book length.

    Parameters
    ----------
    max_sessions:
        Hard upper bound on the number of sessions produced.  This is the
        primary control that decouples session count from book size.
    target_sessions:
        Informational target the curriculum designer aims for; retained for
        logging/diagnostics.
    min_tokens, max_tokens:
        Deprecated.  Accepted for backward compatibility with existing
        callers/tests but no longer used to size or split sessions.
    """

    def __init__(
        self,
        max_sessions: int = 25,
        target_sessions: int = 15,
        min_tokens: int | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self._max_sessions = max(1, max_sessions)
        self._target_sessions = target_sessions
        # Retained only so legacy callers passing token budgets don't break.
        self._min_tokens = min_tokens
        self._max_tokens = max_tokens

    def group_sessions(
        self,
        sections: list[DiscoveredSection],
        section_chunks: dict[str, list[CourseChunk]],
    ) -> list[Session]:
        """Build an ordered list of ``Session`` objects.

        Parameters
        ----------
        sections:
            Personalised, ordered sections (one per curriculum session).
        section_chunks:
            Mapping section_id → selected chunks for that section.

        Returns
        -------
        list[Session]
            Sessions numbered starting from 1, capped at ``max_sessions``.
        """
        # Build one unit per non-empty section, preserving teaching order.
        units: list[tuple[list[str], list[CourseChunk]]] = []
        for section in sections:
            chunks = section_chunks.get(section.section_id, [])
            if not chunks:
                continue
            units.append(([section.display_title], list(chunks)))

        if not units:
            return []

        # Enforce the hard cap by merging consecutive sections evenly.
        if len(units) > self._max_sessions:
            logger.info(
                "session_count_capped",
                sections=len(units),
                max_sessions=self._max_sessions,
            )
            units = self._merge_to_cap(units, self._max_sessions)

        sessions = [
            self._build_session(titles, chunks, i)
            for i, (titles, chunks) in enumerate(units, 1)
        ]

        total_chunks = sum(len(s.chunks) for s in sessions)
        total_tokens = sum(s.estimated_token_count for s in sessions)
        logger.info(
            "session_grouping_complete",
            total_sessions=len(sessions),
            total_chunks=total_chunks,
            total_tokens=total_tokens,
            avg_tokens_per_session=total_tokens // max(len(sessions), 1),
        )

        return sessions

    # ── Internal helpers ─────────────────────────────────────────

    @staticmethod
    def _merge_to_cap(
        units: list[tuple[list[str], list[CourseChunk]]],
        cap: int,
    ) -> list[tuple[list[str], list[CourseChunk]]]:
        """Merge consecutive units into exactly ``cap`` groups.

        Distribution is as even as possible while preserving order, so
        pedagogically-adjacent sections (already sorted) end up together.
        """
        n = len(units)
        base, extra = divmod(n, cap)

        merged: list[tuple[list[str], list[CourseChunk]]] = []
        idx = 0
        for g in range(cap):
            size = base + (1 if g < extra else 0)
            group = units[idx : idx + size]
            idx += size
            titles = [t for u in group for t in u[0]]
            chunks = [c for u in group for c in u[1]]
            merged.append((titles, chunks))

        return merged

    @staticmethod
    def _build_session(
        titles: list[str],
        chunks: list[CourseChunk],
        session_number: int,
    ) -> Session:
        """Build a session from a (possibly merged) group of sections."""
        # Session title: list section titles, collapsing once there are many.
        if len(titles) <= 3:
            title = ", ".join(titles)
        else:
            title = f"{titles[0]}, {titles[1]} & {len(titles) - 2} more"

        session_chunks = [
            SessionChunk(chunk_id=c.chunk_id, raw_text=c.raw_text)
            for c in chunks
        ]
        topics = list(dict.fromkeys(c.topic for c in chunks))
        total_tokens = sum(_estimate_tokens(c.raw_text) for c in chunks)

        books = [c.book for c in chunks if c.book]
        book = books[0] if books else ""
        page_start = min((c.page_start for c in chunks), default=0)
        page_end = max((c.page_end for c in chunks), default=0)

        return Session(
            session_number=session_number,
            session_title=title,
            chunks=session_chunks,
            topics_covered=topics,
            estimated_token_count=total_tokens,
            book=book,
            page_range_start=page_start,
            page_range_end=page_end,
        )
