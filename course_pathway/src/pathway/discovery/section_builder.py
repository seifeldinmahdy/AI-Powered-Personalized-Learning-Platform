"""Section Discovery Engine — clusters chunks into pedagogical sections.

Takes all ``CourseChunk`` objects for a course and produces a list of
``DiscoveredSection`` objects by:

1. Normalising topic strings (lowercase, strip).
2. Fuzzy-merging near-duplicate topics (e.g. "While Loop" and "while loops")
   using ``difflib.SequenceMatcher`` above a configurable threshold.
3. Grouping chunks by their canonical (merged) topic.
4. Ordering chunks within each section: definitional first, then by
   ``chunk_index`` (preserving book order).
5. Computing per-section metadata (difficulty distribution, has_definitional).
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

import structlog

from pathway.models.schemas import CourseChunk, DiscoveredSection

logger = structlog.get_logger(__name__)

# ── Topic normalisation ──────────────────────────────────────────

_STRIP_RE = re.compile(r"[^a-z0-9\s]")


def _normalise_topic(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    normed = raw.lower().strip()
    normed = _STRIP_RE.sub("", normed)
    normed = re.sub(r"\s+", " ", normed).strip()
    return normed


def _topics_similar(a: str, b: str, threshold: float) -> bool:
    """Return True if normalised topics *a* and *b* are fuzzy-similar."""
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


# ── Canonical topic mapping ──────────────────────────────────────


class _TopicCanonicaliser:
    """Builds a mapping from raw topic strings to canonical representatives.

    The first topic string seen in each fuzzy cluster becomes the
    canonical form.  Later near-duplicates merge into it.
    """

    def __init__(self, threshold: float = 0.85) -> None:
        self._threshold = threshold
        # canonical normalised → original casing (first seen)
        self._canonical_map: dict[str, str] = {}

    def canonicalise(self, raw_topic: str) -> str:
        """Return the canonical normalised topic for *raw_topic*.

        If *raw_topic* is close enough to an existing canonical topic
        (above *threshold*), it merges into that cluster.  Otherwise a
        new canonical entry is created.
        """
        normed = _normalise_topic(raw_topic)
        if not normed:
            return "unknown"

        # Exact match first (fast path)
        if normed in self._canonical_map:
            return normed

        # Fuzzy match against existing canonicals
        for existing_normed in self._canonical_map:
            if _topics_similar(normed, existing_normed, self._threshold):
                return existing_normed

        # No match — create new canonical entry
        self._canonical_map[normed] = raw_topic
        return normed

    @property
    def canonical_topics(self) -> dict[str, str]:
        """Return mapping: normalised canonical → original casing."""
        return dict(self._canonical_map)


# ── Section builder ──────────────────────────────────────────────


class SectionBuilder:
    """Discovers pedagogical sections from course chunks.

    Parameters
    ----------
    similarity_threshold:
        Fuzzy string similarity threshold for merging near-duplicate
        topic names.  Default 0.85.
    """

    def __init__(self, similarity_threshold: float = 0.85) -> None:
        self._threshold = similarity_threshold

    def discover_sections(
        self, chunks: list[CourseChunk]
    ) -> list[DiscoveredSection]:
        """Cluster *chunks* into ``DiscoveredSection`` objects.

        Parameters
        ----------
        chunks:
            All ``CourseChunk`` objects for a single course, in any order.

        Returns
        -------
        list[DiscoveredSection]
            One section per canonical topic, with chunks ordered
            (definitional first, then by chunk_index).
        """
        if not chunks:
            logger.warning("section_builder_empty_input")
            return []

        # 1. Build canonical topic mapping
        canonicaliser = _TopicCanonicaliser(threshold=self._threshold)
        chunk_to_canonical: dict[str, str] = {}
        for chunk in chunks:
            canonical = canonicaliser.canonicalise(chunk.topic)
            chunk_to_canonical[chunk.chunk_id] = canonical

        canonical_map = canonicaliser.canonical_topics

        logger.info(
            "topic_canonicalisation_complete",
            raw_topics=len({c.topic for c in chunks}),
            canonical_topics=len(canonical_map),
            merge_ratio=round(
                1 - len(canonical_map) / max(len({c.topic for c in chunks}), 1), 3
            ),
        )

        # 2. Group chunks by canonical topic
        groups: dict[str, list[CourseChunk]] = defaultdict(list)
        for chunk in chunks:
            canonical = chunk_to_canonical[chunk.chunk_id]
            groups[canonical].append(chunk)

        # 3. Build DiscoveredSection for each group
        sections: list[DiscoveredSection] = []
        
        # Textbook boilerplate to ignore
        _IGNORED_TOPICS = {
            "index", "index entries", "glossary", "appendix", "bibliography", 
            "references", "table of contents", "contents", "preface", "acknowledgments"
        }

        for canonical_normed, group_chunks in groups.items():
            if canonical_normed in _IGNORED_TOPICS:
                logger.debug("section_builder_ignored_topic", topic=canonical_normed)
                continue

            # Sort: definitional first, then by chunk_index
            group_chunks.sort(
                key=lambda c: (not c.is_definitional, c.chunk_index)
            )

            # Difficulty distribution
            diff_dist: dict[str, int] = defaultdict(int)
            for c in group_chunks:
                diff_dist[c.difficulty] += 1

            has_def = any(c.is_definitional for c in group_chunks)

            # Use the original casing from the first-seen representative
            original_casing = canonical_map.get(canonical_normed, canonical_normed)

            section = DiscoveredSection(
                section_id=f"sec_{canonical_normed.replace(' ', '_')}",
                canonical_topic=canonical_normed,
                display_title=original_casing,  # Will be overwritten by LLM later
                chunk_ids=[c.chunk_id for c in group_chunks],
                difficulty_distribution=dict(diff_dist),
                has_definitional_chunks=has_def,
                prerequisite_sections=[],  # Filled by GraphBuilder
            )
            sections.append(section)

        logger.info(
            "section_discovery_complete",
            total_sections=len(sections),
            total_chunks=len(chunks),
        )

        return sections
