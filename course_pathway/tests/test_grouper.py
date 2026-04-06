"""Tests for SessionGrouper — token budgeting and session packing."""

from pathway.discovery.graph_builder import GraphBuilder
from pathway.discovery.section_builder import SectionBuilder
from pathway.personalization.personalizer import Personalizer
from pathway.session.grouper import SessionGrouper, _estimate_tokens


def _build_personalised(chunks, context):
    """Full pipeline up to personalisation."""
    builder = SectionBuilder()
    sections = builder.discover_sections(chunks)
    graph = GraphBuilder()
    sorted_sections = graph.build_and_sort(sections, chunks)
    p = Personalizer()
    return p.personalize(sorted_sections, chunks, context)


class TestEstimateTokens:
    def test_empty(self):
        assert _estimate_tokens("") == 0

    def test_known_count(self):
        text = "one two three four five"
        # 5 words * 1.3 = 6.5 → 6
        assert _estimate_tokens(text) == 6


class TestSessionGrouper:
    def test_produces_sessions(self, sample_chunks, novice_context):
        sections, section_chunks = _build_personalised(
            sample_chunks, novice_context
        )
        grouper = SessionGrouper(min_tokens=100, max_tokens=1000)
        sessions = grouper.group_sessions(sections, section_chunks)

        assert len(sessions) > 0

    def test_no_empty_sessions(self, sample_chunks, intermediate_context):
        sections, section_chunks = _build_personalised(
            sample_chunks, intermediate_context
        )
        grouper = SessionGrouper(min_tokens=100, max_tokens=1000)
        sessions = grouper.group_sessions(sections, section_chunks)

        for session in sessions:
            assert len(session.chunks) > 0

    def test_token_budget_respected(self, sample_chunks, intermediate_context):
        max_tokens = 1000
        sections, section_chunks = _build_personalised(
            sample_chunks, intermediate_context
        )
        grouper = SessionGrouper(min_tokens=100, max_tokens=max_tokens)
        sessions = grouper.group_sessions(sections, section_chunks)

        for session in sessions:
            assert session.estimated_token_count <= max_tokens * 1.1, (
                f"Session {session.session_number} exceeds budget: "
                f"{session.estimated_token_count} > {max_tokens}"
            )

    def test_session_numbering(self, sample_chunks, novice_context):
        sections, section_chunks = _build_personalised(
            sample_chunks, novice_context
        )
        grouper = SessionGrouper(min_tokens=100, max_tokens=1000)
        sessions = grouper.group_sessions(sections, section_chunks)

        for i, session in enumerate(sessions, 1):
            assert session.session_number == i

    def test_all_chunks_in_sessions(self, sample_chunks, intermediate_context):
        """Every selected chunk should appear in exactly one session."""
        sections, section_chunks = _build_personalised(
            sample_chunks, intermediate_context
        )
        grouper = SessionGrouper(min_tokens=100, max_tokens=5000)
        sessions = grouper.group_sessions(sections, section_chunks)

        session_chunk_ids = set()
        for session in sessions:
            for chunk in session.chunks:
                assert chunk.chunk_id not in session_chunk_ids, (
                    f"Chunk {chunk.chunk_id} appears in multiple sessions"
                )
                session_chunk_ids.add(chunk.chunk_id)

        expected_ids = set()
        for chunks in section_chunks.values():
            for c in chunks:
                expected_ids.add(c.chunk_id)

        assert session_chunk_ids == expected_ids

    def test_large_budget_fewer_sessions(self, sample_chunks, novice_context):
        sections, section_chunks = _build_personalised(
            sample_chunks, novice_context
        )
        small_budget = SessionGrouper(min_tokens=50, max_tokens=200)
        large_budget = SessionGrouper(min_tokens=500, max_tokens=5000)

        small_sessions = small_budget.group_sessions(sections, section_chunks)
        large_sessions = large_budget.group_sessions(sections, section_chunks)

        assert len(large_sessions) <= len(small_sessions)
