"""Dependency Graph Builder & Topological Sorter.

Constructs a directed acyclic graph (DAG) of section dependencies from
the ``depends_on`` metadata across all chunks, then topologically sorts
it to produce a valid teaching order.

Algorithm
---------
1. For each ``DiscoveredSection``, union all ``depends_on`` lists from
   its chunks.
2. Resolve each dependency topic string to the matching section using
   the same fuzzy normalisation as ``SectionBuilder``.
3. Create directed edges: prerequisite section → dependent section.
4. Topological sort via Kahn's algorithm.
5. If cycles exist, break them by removing the edge with the fewest
   supporting chunk references, then retry.
"""

from __future__ import annotations

from collections import defaultdict, deque
from difflib import SequenceMatcher

import structlog

from pathway.models.schemas import CourseChunk, DiscoveredSection

logger = structlog.get_logger(__name__)


def _fuzzy_match_topic(
    query: str,
    canonical_topics: dict[str, str],
    threshold: float = 0.70,
) -> str | None:
    """Find the canonical topic that best matches *query*.

    Parameters
    ----------
    query:
        A raw dependency topic string (e.g. "binary tree").
    canonical_topics:
        Mapping of normalised canonical topic → section_id.
    threshold:
        Minimum similarity ratio required for a match.

    Returns
    -------
    str | None
        The matching ``section_id``, or None if no match found.
    """
    query_normed = query.lower().strip()
    if not query_normed:
        return None

    best_score = 0.0
    best_section_id: str | None = None

    for canonical_normed, section_id in canonical_topics.items():
        # Fast exact match
        if query_normed == canonical_normed:
            return section_id

        score = SequenceMatcher(None, query_normed, canonical_normed).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_section_id = section_id

    return best_section_id


class GraphBuilder:
    """Builds a section dependency graph and produces a topological order.

    Parameters
    ----------
    dependency_match_threshold:
        Fuzzy similarity threshold for resolving ``depends_on`` topic
        strings to sections.  Lower than the section builder's threshold
        because dependency references are often abbreviated.
    """

    def __init__(self, dependency_match_threshold: float = 0.70) -> None:
        self._threshold = dependency_match_threshold

    def build_and_sort(
        self,
        sections: list[DiscoveredSection],
        chunks: list[CourseChunk],
    ) -> list[DiscoveredSection]:
        """Build the dependency graph, set prerequisite_sections, and sort.

        Parameters
        ----------
        sections:
            Sections discovered by ``SectionBuilder``.
        chunks:
            All course chunks (needed for their ``depends_on`` metadata).

        Returns
        -------
        list[DiscoveredSection]
            Sections in valid teaching order (prerequisites first).
            Each section's ``prerequisite_sections`` field is populated.
        """
        if not sections:
            return []

        # Build lookup structures
        section_by_id: dict[str, DiscoveredSection] = {
            s.section_id: s for s in sections
        }
        chunk_to_section: dict[str, str] = {}
        for section in sections:
            for cid in section.chunk_ids:
                chunk_to_section[cid] = section.section_id

        # canonical_topic → section_id mapping for dependency resolution
        canonical_to_section: dict[str, str] = {
            s.canonical_topic: s.section_id for s in sections
        }

        # Collect raw dependencies per section
        section_raw_deps: dict[str, set[str]] = defaultdict(set)
        chunk_by_id: dict[str, CourseChunk] = {c.chunk_id: c for c in chunks}

        for section in sections:
            for cid in section.chunk_ids:
                chunk = chunk_by_id.get(cid)
                if chunk is None:
                    continue
                for dep_topic in chunk.depends_on:
                    section_raw_deps[section.section_id].add(dep_topic)

        # Resolve raw dependency topics → section_ids
        adjacency: dict[str, set[str]] = defaultdict(set)
        # Also track edge weights (how many chunk references support each edge)
        edge_weights: dict[tuple[str, str], int] = defaultdict(int)

        for section_id, dep_topics in section_raw_deps.items():
            for dep_topic in dep_topics:
                resolved = _fuzzy_match_topic(
                    dep_topic, canonical_to_section, self._threshold
                )
                if resolved is None:
                    continue
                # Skip self-dependencies
                if resolved == section_id:
                    continue
                # Edge: prerequisite → dependent
                adjacency[resolved].add(section_id)
                edge_weights[(resolved, section_id)] += 1

        # Populate prerequisite_sections on each section
        for section in sections:
            prereqs: set[str] = set()
            for prereq_id, dependents in adjacency.items():
                if section.section_id in dependents:
                    prereqs.add(prereq_id)
            section.prerequisite_sections = sorted(prereqs)

        resolved_edge_count = sum(len(deps) for deps in adjacency.values())
        logger.info(
            "dependency_graph_built",
            total_sections=len(sections),
            resolved_edges=resolved_edge_count,
            unresolved_deps=sum(
                1
                for section_id, dep_topics in section_raw_deps.items()
                for dep_topic in dep_topics
                if _fuzzy_match_topic(dep_topic, canonical_to_section, self._threshold) is None
            ),
        )

        # Topological sort with cycle breaking
        sorted_ids = self._topological_sort(
            section_ids=[s.section_id for s in sections],
            adjacency=adjacency,
            edge_weights=edge_weights,
        )

        # Return sections in sorted order
        return [section_by_id[sid] for sid in sorted_ids]

    def _topological_sort(
        self,
        section_ids: list[str],
        adjacency: dict[str, set[str]],
        edge_weights: dict[tuple[str, str], int],
    ) -> list[str]:
        """Kahn's algorithm with cycle-breaking fallback.

        Parameters
        ----------
        section_ids:
            All section IDs.
        adjacency:
            prerequisite → set of dependent section IDs.
        edge_weights:
            (prereq, dependent) → number of chunk references.

        Returns
        -------
        list[str]
            Section IDs in topological order.
        """
        # Compute in-degree for each node
        in_degree: dict[str, int] = {sid: 0 for sid in section_ids}
        for prereq, dependents in adjacency.items():
            for dep in dependents:
                if dep in in_degree:
                    in_degree[dep] = in_degree.get(dep, 0) + 1

        # Initialise queue with zero in-degree nodes
        queue: deque[str] = deque()
        for sid in section_ids:
            if in_degree[sid] == 0:
                queue.append(sid)

        result: list[str] = []
        remaining_adjacency = {k: set(v) for k, v in adjacency.items()}

        max_iterations = len(section_ids) * 2  # Safety bound
        iteration = 0

        while len(result) < len(section_ids):
            iteration += 1
            if iteration > max_iterations:
                # Should never happen, but prevents infinite loops
                logger.error("topological_sort_exceeded_max_iterations")
                remaining = [sid for sid in section_ids if sid not in set(result)]
                result.extend(remaining)
                break

            if queue:
                # Standard Kahn's step
                node = queue.popleft()
                result.append(node)

                for dep in list(remaining_adjacency.get(node, set())):
                    remaining_adjacency[node].discard(dep)
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)
            else:
                # Cycle detected — break the weakest edge
                cycle_nodes = [
                    sid for sid in section_ids
                    if sid not in set(result) and in_degree[sid] > 0
                ]

                if not cycle_nodes:
                    # All remaining nodes have in_degree 0 but weren't queued
                    remaining = [sid for sid in section_ids if sid not in set(result)]
                    result.extend(remaining)
                    break

                # Find the weakest incoming edge among cycle nodes
                weakest_edge: tuple[str, str] | None = None
                weakest_weight = float("inf")

                for prereq, dependents in remaining_adjacency.items():
                    for dep in dependents:
                        if dep in set(cycle_nodes):
                            w = edge_weights.get((prereq, dep), 1)
                            if w < weakest_weight:
                                weakest_weight = w
                                weakest_edge = (prereq, dep)

                if weakest_edge is None:
                    # No edges found — just add remaining
                    remaining = [sid for sid in section_ids if sid not in set(result)]
                    result.extend(remaining)
                    break

                prereq, dep = weakest_edge
                remaining_adjacency[prereq].discard(dep)
                in_degree[dep] -= 1

                logger.warning(
                    "cycle_broken",
                    removed_edge=f"{prereq} → {dep}",
                    edge_weight=weakest_weight,
                )

                if in_degree[dep] == 0:
                    queue.append(dep)

        logger.info(
            "topological_sort_complete",
            total_sections=len(section_ids),
            sorted_sections=len(result),
        )

        return result