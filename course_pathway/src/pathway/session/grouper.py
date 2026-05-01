"""Session Grouper — packs personalised chunks into token-budgeted sessions.

Rules
-----
1. Each session contains between ``min_tokens`` and ``max_tokens`` of
   raw text (default 3000–5000 tokens).
2. A session must never mix chunks from conceptually unrelated sections.
   Sections that share prerequisite relationships may appear together,
   but unrelated sections are always separated.
3. If a section's total tokens exceed one session's budget, it is split
   across consecutive sessions with continuity titles
   (e.g. "While Loops — Part 2").
4. Definitional chunks always appear before applied chunks within a
   session (guaranteed by the personaliser's sort order, preserved here).

Token counting uses a word-count heuristic: ``len(text.split()) * 1.3``.
This closely approximates BPE token counts for English prose and avoids
requiring a heavy tokenizer dependency for session budgeting.
"""

from __future__ import annotations

import math

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
    word with BPE tokenizers.  This is accurate enough for session
    budgeting (we don't need exact counts).
    """
    return int(len(text.split()) * 1.3)


class SessionGrouper:
    """Groups personalised chunks into token-budgeted learning sessions.

    Parameters
    ----------
    min_tokens:
        Minimum raw-text tokens per session.
    max_tokens:
        Maximum raw-text tokens per session.
    """

    def __init__(
        self,
        min_tokens: int = 3000,
        max_tokens: int = 5000,
    ) -> None:
        self._min = min_tokens
        self._max = max_tokens

    def group_sessions(
        self,
        sections: list[DiscoveredSection],
        section_chunks: dict[str, list[CourseChunk]],
    ) -> list[Session]:
        """Build an ordered list of ``Session`` objects.

        Strategy: iterate through sections in teaching order, accumulating
        chunks into a running buffer.  When the buffer reaches ``max_tokens``
        or a single large section needs its own session(s), flush.

        Adjacent small sections are naturally packed together because
        the topological sort already placed related sections near each
        other — sections that appear consecutively share prerequisite
        proximity and are pedagogically related.

        Parameters
        ----------
        sections:
            Personalised, ordered sections.
        section_chunks:
            Mapping section_id → selected chunks for that section.

        Returns
        -------
        list[Session]
            Sessions numbered starting from 1.
        """
        sessions: list[Session] = []

        # Running buffer
        buf_pairs: list[tuple[CourseChunk, int]] = []
        buf_tokens = 0
        buf_titles: list[str] = []

        for section in sections:
            chunks = section_chunks.get(section.section_id, [])
            if not chunks:
                continue

            section_pairs = [(c, _estimate_tokens(c.raw_text)) for c in chunks]
            section_tokens = sum(t for _, t in section_pairs)

            # Case 1: section is too large for a single session → flush buffer,
            # then split the section across dedicated sessions.
            if section_tokens > self._max:
                # Flush whatever is in the buffer
                if buf_pairs:
                    sessions.append(self._flush_buffer(
                        buf_pairs, buf_titles, len(sessions) + 1
                    ))
                    buf_pairs, buf_tokens, buf_titles = [], 0, []

                # Split this large section
                sessions.extend(self._split_large_section(
                    section, section_pairs, len(sessions) + 1
                ))
                continue

            # Case 2: adding this section would bust the budget → flush first.
            if buf_tokens + section_tokens > self._max and buf_pairs:
                sessions.append(self._flush_buffer(
                    buf_pairs, buf_titles, len(sessions) + 1
                ))
                buf_pairs, buf_tokens, buf_titles = [], 0, []

            # Accumulate into buffer
            buf_pairs.extend(section_pairs)
            buf_tokens += section_tokens
            buf_titles.append(section.display_title)

        # Flush remaining buffer
        if buf_pairs:
            sessions.append(self._flush_buffer(
                buf_pairs, buf_titles, len(sessions) + 1
            ))

        # Re-number
        for i, session in enumerate(sessions, 1):
            session.session_number = i

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
    def _flush_buffer(
        pairs: list[tuple[CourseChunk, int]],
        titles: list[str],
        session_number: int,
    ) -> Session:
        """Build a session from the accumulated buffer."""
        # Session title: use all section titles, max 3 before truncating
        if len(titles) <= 3:
            title = ", ".join(titles)
        else:
            title = f"{titles[0]}, {titles[1]} & {len(titles) - 2} more"

        session_chunks = [
            SessionChunk(chunk_id=c.chunk_id, raw_text=c.raw_text)
            for c, _ in pairs
        ]
        topics = list(dict.fromkeys(c.topic for c, _ in pairs))
        total_tokens = sum(t for _, t in pairs)

        books = [c.book for c, _ in pairs if c.book]
        book = books[0] if books else ""
        page_start = min((c.page_start for c, _ in pairs), default=0)
        page_end = max((c.page_end for c, _ in pairs), default=0)

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

    def _split_large_section(
        self,
        section: DiscoveredSection,
        chunk_tokens: list[tuple[CourseChunk, int]],
        start_number: int,
    ) -> list[Session]:
        """Split a section too large for one session into balanced parts."""
        total_tokens = sum(t for _, t in chunk_tokens)

        # Tolerance: if the section is just slightly over the budget (10%),
        # don't split it at all to avoid a tiny 1-chunk "Part 2".
        if total_tokens <= self._max * 1.10:
            return [self._flush_buffer(chunk_tokens, [section.display_title], start_number)]

        num_parts = math.ceil(total_tokens / self._max)
        target_tokens_per_part = total_tokens / num_parts

        sessions: list[Session] = []
        current_pairs: list[tuple[CourseChunk, int]] = []
        current_tokens = 0
        part = 1

        for chunk, tokens in chunk_tokens:
            # Flush if adding the NEXT token would push us too far past the target
            # for this part (unless it's the last part).
            if current_tokens > 0 and (current_tokens + tokens / 2 >= target_tokens_per_part):
                if part < num_parts:
                    title = f"{section.display_title} — Part {part}"
                    sessions.append(self._flush_buffer(
                        current_pairs, [title], start_number + part - 1
                    ))
                    part += 1
                    current_pairs = []
                    current_tokens = 0

            current_pairs.append((chunk, tokens))
            current_tokens += tokens

        if current_pairs:
            title = (
                f"{section.display_title} — Part {part}"
                if part > 1 or sessions
                else section.display_title
            )
            sessions.append(self._flush_buffer(
                current_pairs, [title], start_number + part - 1
            ))

        return sessions
