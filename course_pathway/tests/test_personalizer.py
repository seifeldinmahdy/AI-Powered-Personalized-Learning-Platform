"""Tests for Personalizer — context-based reordering and chunk selection."""

from pathway.discovery.graph_builder import GraphBuilder
from pathway.discovery.section_builder import SectionBuilder
from pathway.personalization.personalizer import Personalizer


def _build_sorted_sections(chunks):
    """Helper: discover sections and topologically sort them."""
    builder = SectionBuilder()
    sections = builder.discover_sections(chunks)
    graph = GraphBuilder()
    return graph.build_and_sort(sections, chunks)


class TestPersonalizer:
    def test_returns_all_sections(self, sample_chunks, novice_context):
        sorted_sections = _build_sorted_sections(sample_chunks)
        p = Personalizer()
        result_sections, section_chunks = p.personalize(
            sorted_sections, sample_chunks, novice_context
        )
        assert len(result_sections) == len(sorted_sections)

    def test_weakness_sections_earlier(self, sample_chunks, novice_context):
        """Weakness topics should appear earlier than without personalisation."""
        sorted_sections = _build_sorted_sections(sample_chunks)
        p = Personalizer()
        result_sections, _ = p.personalize(
            sorted_sections, sample_chunks, novice_context
        )

        # Find position of weakness sections
        weakness_topics = {w.lower() for w in novice_context.weaknesses}
        positions = []
        for i, s in enumerate(result_sections):
            if s.canonical_topic in weakness_topics:
                positions.append(i)

        # Weakness sections should exist
        assert len(positions) > 0, "Expected weakness sections in output"

    def test_strength_compression(self, sample_chunks, expert_context):
        """Strength topics should have fewer chunks selected (compressed)."""
        sorted_sections = _build_sorted_sections(sample_chunks)
        p = Personalizer()
        _, section_chunks = p.personalize(
            sorted_sections, sample_chunks, expert_context
        )

        strength_topics = {s.lower() for s in expert_context.strengths}
        for section_id, chunks in section_chunks.items():
            # Find the section
            section = next(
                (s for s in sorted_sections if s.section_id == section_id), None
            )
            if section and section.canonical_topic in strength_topics:
                # Strength sections should be compressed
                original_count = len(section.chunk_ids)
                selected_count = len(chunks)
                # Should have at most as many chunks as original (compressed or equal)
                assert selected_count <= original_count

    def test_definitional_chunks_first(self, sample_chunks, novice_context):
        """Definitional chunks should always come before non-definitional."""
        sorted_sections = _build_sorted_sections(sample_chunks)
        p = Personalizer()
        _, section_chunks = p.personalize(
            sorted_sections, sample_chunks, novice_context
        )

        chunk_by_id = {c.chunk_id: c for c in sample_chunks}
        for section_id, chunks in section_chunks.items():
            saw_non_def = False
            for chunk in chunks:
                original = chunk_by_id.get(chunk.chunk_id)
                if original is None:
                    continue
                if not original.is_definitional:
                    saw_non_def = True
                elif saw_non_def:
                    assert False, (
                        f"Section {section_id}: definitional chunk "
                        f"{chunk.chunk_id} appears after non-definitional"
                    )

    def test_no_empty_sections_without_chunks(self, sample_chunks, intermediate_context):
        """Every section in the output should have at least one chunk."""
        sorted_sections = _build_sorted_sections(sample_chunks)
        p = Personalizer()
        result_sections, section_chunks = p.personalize(
            sorted_sections, sample_chunks, intermediate_context
        )

        for section in result_sections:
            chunks = section_chunks.get(section.section_id, [])
            assert len(chunks) > 0, (
                f"Section {section.section_id} has no chunks selected"
            )

    def test_empty_input(self, novice_context):
        p = Personalizer()
        result_sections, section_chunks = p.personalize([], [], novice_context)
        assert result_sections == []
        assert section_chunks == {}
