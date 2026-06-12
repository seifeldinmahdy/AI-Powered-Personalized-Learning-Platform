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

    def test_session_count_capped(self, sample_chunks, intermediate_context):
        """The session count never exceeds max_sessions, regardless of volume."""
        sections, section_chunks = _build_personalised(
            sample_chunks, intermediate_context
        )
        grouper = SessionGrouper(max_sessions=3)
        sessions = grouper.group_sessions(sections, section_chunks)

        assert 0 < len(sessions) <= 3

    def test_one_session_per_section_when_under_cap(
        self, sample_chunks, intermediate_context
    ):
        """With a generous cap, each non-empty section becomes one session."""
        sections, section_chunks = _build_personalised(
            sample_chunks, intermediate_context
        )
        non_empty = sum(
            1 for s in sections if section_chunks.get(s.section_id)
        )
        grouper = SessionGrouper(max_sessions=100)
        sessions = grouper.group_sessions(sections, section_chunks)

        assert len(sessions) == non_empty

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

    def test_lower_cap_fewer_sessions(self, sample_chunks, novice_context):
        sections, section_chunks = _build_personalised(
            sample_chunks, novice_context
        )
        low_cap = SessionGrouper(max_sessions=2)
        high_cap = SessionGrouper(max_sessions=100)

        low_sessions = low_cap.group_sessions(sections, section_chunks)
        high_sessions = high_cap.group_sessions(sections, section_chunks)

        assert len(low_sessions) <= len(high_sessions)
        assert len(low_sessions) <= 2

    def test_count_independent_of_text_volume(
        self, sample_chunks, intermediate_context
    ):
        """Inflating every chunk's raw text must not change the session count."""
        sections, section_chunks = _build_personalised(
            sample_chunks, intermediate_context
        )
        grouper = SessionGrouper(max_sessions=25)
        base = grouper.group_sessions(sections, section_chunks)

        # Inflate raw text 10x — pure volume increase, same structure.
        inflated = {
            sid: [
                chunk.model_copy(update={"raw_text": chunk.raw_text * 10})
                for chunk in chunks
            ]
            for sid, chunks in section_chunks.items()
        }
        inflated_sessions = grouper.group_sessions(sections, inflated)

        assert len(inflated_sessions) == len(base)
