"""Personalisation layer — adapts the base teaching order to a student.

Takes the topologically sorted section sequence produced by ``GraphBuilder``
and applies student-specific adjustments:

1. **Weakness expansion**: Sections covering the student's weak topics are
   pulled earlier in the sequence and retain all available chunks (deeper
   coverage).
2. **Strength compression**: Sections covering strong topics keep only
   higher-difficulty chunks, reducing the session count.
3. **Mastery-based filtering**: The student's mastery level determines
   which difficulty tier of chunks is selected for each section:
   - Novice → prefer ``beginner`` chunks
   - Intermediate → prefer ``intermediate`` chunks
   - Expert → prefer ``expert`` chunks
4. **Definitional ordering**: Within every section, definitional chunks
   always precede applied/example chunks, regardless of other reordering.
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from pathway.models.schemas import CourseChunk, DiscoveredSection, StudentContext

logger = structlog.get_logger(__name__)

# Mastery → preferred difficulty tiers (in selection order)
_MASTERY_TO_DIFFICULTY: dict[str, list[str]] = {
    "Novice": ["beginner", "intermediate"],
    "Intermediate": ["intermediate", "beginner", "expert"],
    "Expert": ["expert", "intermediate"],
}

# When compressing strong topics, keep only these tiers
_STRENGTH_DIFFICULTY: dict[str, list[str]] = {
    "Novice": ["beginner"],
    "Intermediate": ["intermediate"],
    "Expert": ["expert"],
}


def _normalise_topic_for_match(topic: str) -> str:
    """Lowercase and strip for comparison against weakness/strength lists."""
    return topic.lower().strip()


class Personalizer:
    """Applies student context to transform the base section sequence.

    The personalizer never removes a section entirely — it adjusts
    ordering and chunk selection within sections.
    """

    def personalize(
        self,
        sections: list[DiscoveredSection],
        chunks: list[CourseChunk],
        context: StudentContext,
    ) -> tuple[list[DiscoveredSection], dict[str, list[CourseChunk]]]:
        """Personalise sections and select chunks for each.

        Parameters
        ----------
        sections:
            Topologically sorted sections from ``GraphBuilder``.
        chunks:
            All course chunks (for chunk-level filtering).
        context:
            The student's context (mastery, strengths, weaknesses).

        Returns
        -------
        tuple[list[DiscoveredSection], dict[str, list[CourseChunk]]]
            Reordered sections AND a mapping of section_id → selected
            chunks for that section (filtered and ordered).
        """
        if not sections:
            return [], {}

        chunk_by_id: dict[str, CourseChunk] = {c.chunk_id: c for c in chunks}

        # Normalise weakness/strength lists for matching
        weakness_set = {_normalise_topic_for_match(w) for w in context.weaknesses}
        strength_set = {_normalise_topic_for_match(s) for s in context.strengths}
        preferred_diffs = _MASTERY_TO_DIFFICULTY.get(
            context.mastery_level, ["intermediate", "beginner", "expert"]
        )
        strength_diffs = _STRENGTH_DIFFICULTY.get(
            context.mastery_level, ["intermediate"]
        )

        # Classify sections
        weakness_sections: list[DiscoveredSection] = []
        strength_sections: list[DiscoveredSection] = []
        neutral_sections: list[DiscoveredSection] = []

        for section in sections:
            topic_normed = _normalise_topic_for_match(section.canonical_topic)
            if topic_normed in weakness_set:
                weakness_sections.append(section)
            elif topic_normed in strength_set:
                strength_sections.append(section)
            else:
                neutral_sections.append(section)

        logger.info(
            "personalisation_classification",
            weakness_sections=len(weakness_sections),
            strength_sections=len(strength_sections),
            neutral_sections=len(neutral_sections),
        )

        # Reorder: weakness sections are pulled earlier.
        # Strategy: interleave weakness sections into the front of the
        # neutral sequence, respecting prerequisite constraints.
        # Since sections are already topologically sorted, weakness sections
        # that appear later in the topo order depend on earlier sections.
        # We only pull a weakness section forward if all its prerequisites
        # are already before it in the new order.
        reordered = self._reorder_with_weakness_priority(
            weakness_sections, strength_sections, neutral_sections, sections
        )

        # Select chunks per section
        section_chunks: dict[str, list[CourseChunk]] = {}

        for section in reordered:
            raw_chunks = [
                chunk_by_id[cid]
                for cid in section.chunk_ids
                if cid in chunk_by_id
            ]

            topic_normed = _normalise_topic_for_match(section.canonical_topic)

            if topic_normed in weakness_set:
                # Weakness: keep ALL chunks, prefer easier difficulty
                selected = self._select_chunks_for_weakness(
                    raw_chunks, preferred_diffs
                )
            elif topic_normed in strength_set:
                # Strength: compress — keep only higher-difficulty chunks
                selected = self._select_chunks_for_strength(
                    raw_chunks, strength_diffs
                )
            else:
                # Neutral: standard mastery-based selection
                selected = self._select_chunks_for_neutral(
                    raw_chunks, preferred_diffs
                )

            # Enforce: definitional chunks always come first
            selected.sort(key=lambda c: (not c.is_definitional, c.chunk_index))

            section_chunks[section.section_id] = selected

        total_selected = sum(len(v) for v in section_chunks.values())
        logger.info(
            "personalisation_complete",
            total_sections=len(reordered),
            total_chunks_selected=total_selected,
            total_chunks_available=len(chunks),
        )

        return reordered, section_chunks

    # ── Reordering ───────────────────────────────────────────────

    def _reorder_with_weakness_priority(
        self,
        weakness: list[DiscoveredSection],
        strength: list[DiscoveredSection],
        neutral: list[DiscoveredSection],
        original_order: list[DiscoveredSection],
    ) -> list[DiscoveredSection]:
        """Reorder sections, pulling weakness topics earlier.

        The algorithm preserves the topological invariant: no section
        appears before any of its prerequisites.

        Strategy:
        - Build a position map from original topo order.
        - Assign priority scores: weakness=0, neutral=1, strength=2.
        - Sort by (priority, original_position) — this pulls weakness
          sections earlier while keeping topo order stable within each
          priority group.
        - Validate/enforce prerequisite constraints with a final pass.
        """
        original_pos = {
            s.section_id: i for i, s in enumerate(original_order)
        }
        weakness_ids = {s.section_id for s in weakness}
        strength_ids = {s.section_id for s in strength}

        all_sections = list(original_order)

        def priority_key(section: DiscoveredSection) -> tuple[int, int]:
            if section.section_id in weakness_ids:
                pri = 0
            elif section.section_id in strength_ids:
                pri = 2
            else:
                pri = 1
            return (pri, original_pos.get(section.section_id, 0))

        all_sections.sort(key=priority_key)

        # Enforce prerequisites: if a section appears before a prereq,
        # swap them back.
        all_sections = self._enforce_prerequisites(all_sections)

        return all_sections

    @staticmethod
    def _enforce_prerequisites(
        sections: list[DiscoveredSection],
    ) -> list[DiscoveredSection]:
        """Ensure no section appears before its prerequisites.

        Uses iterative swapping — simple and correct since the input
        is already nearly sorted.
        """
        section_pos = {s.section_id: i for i, s in enumerate(sections)}
        changed = True
        max_passes = 50  # Safety bound

        for _ in range(max_passes):
            if not changed:
                break
            changed = False
            for i, section in enumerate(sections):
                for prereq_id in section.prerequisite_sections:
                    prereq_pos = section_pos.get(prereq_id)
                    if prereq_pos is not None and prereq_pos > i:
                        # Prereq is after this section — move section after prereq
                        sections.pop(i)
                        sections.insert(prereq_pos, section)
                        # Rebuild position map
                        section_pos = {
                            s.section_id: j for j, s in enumerate(sections)
                        }
                        changed = True
                        break
                if changed:
                    break

        return sections

    # ── Chunk selection strategies ────────────────────────────────

    @staticmethod
    def _select_chunks_for_weakness(
        chunks: list[CourseChunk],
        preferred_diffs: list[str],
    ) -> list[CourseChunk]:
        """Weakness topics: keep ALL chunks for maximum coverage.

        All difficulty tiers are included to ensure thorough learning.
        """
        return list(chunks)

    @staticmethod
    def _select_chunks_for_strength(
        chunks: list[CourseChunk],
        strength_diffs: list[str],
    ) -> list[CourseChunk]:
        """Strength topics: keep only higher-difficulty + definitional chunks.

        Definitional chunks are always kept (even at beginner level)
        because they define the concept.  Applied/example chunks are
        filtered to only the target difficulty tier.
        """
        selected: list[CourseChunk] = []
        for chunk in chunks:
            if chunk.is_definitional:
                selected.append(chunk)
            elif chunk.difficulty in strength_diffs:
                selected.append(chunk)

        # If filtering removed everything, keep at least the first chunk
        if not selected and chunks:
            selected = [chunks[0]]

        return selected

    @staticmethod
    def _select_chunks_for_neutral(
        chunks: list[CourseChunk],
        preferred_diffs: list[str],
    ) -> list[CourseChunk]:
        """Neutral topics: select chunks matching the mastery difficulty tier.

        Definitional chunks are always kept.  For non-definitional chunks,
        prefer the student's mastery-appropriate difficulty.  If no
        matching-difficulty chunks exist, fall back to all chunks.
        """
        definitional = [c for c in chunks if c.is_definitional]
        non_def = [c for c in chunks if not c.is_definitional]

        # Filter non-definitional by preferred difficulty
        filtered_non_def: list[CourseChunk] = []
        for diff in preferred_diffs:
            matches = [c for c in non_def if c.difficulty == diff]
            filtered_non_def.extend(matches)

        if not filtered_non_def and non_def:
            # No chunks match preferred difficulty — keep all
            filtered_non_def = non_def

        # Deduplicate (a chunk could match multiple preferred diffs)
        seen: set[str] = set()
        result: list[CourseChunk] = []
        for c in definitional + filtered_non_def:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                result.append(c)

        # If everything was filtered out, keep at least one chunk
        if not result and chunks:
            result = [chunks[0]]

        return result
