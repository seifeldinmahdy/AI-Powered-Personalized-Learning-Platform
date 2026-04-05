"""Tests for GraphBuilder — dependency resolution and topological sort."""

from pathway.discovery.graph_builder import GraphBuilder
from pathway.discovery.section_builder import SectionBuilder


class TestGraphBuilder:
    def test_empty_input(self):
        graph = GraphBuilder()
        assert graph.build_and_sort([], []) == []

    def test_produces_valid_order(self, sample_chunks):
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)

        graph = GraphBuilder()
        sorted_sections = graph.build_and_sort(sections, sample_chunks)

        # Same number of sections in and out
        assert len(sorted_sections) == len(sections)

    def test_no_prereq_before_section(self, sample_chunks):
        """No section should appear before any of its prerequisites."""
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)

        graph = GraphBuilder()
        sorted_sections = graph.build_and_sort(sections, sample_chunks)

        position = {s.section_id: i for i, s in enumerate(sorted_sections)}

        for section in sorted_sections:
            for prereq_id in section.prerequisite_sections:
                if prereq_id in position:
                    assert position[prereq_id] < position[section.section_id], (
                        f"Prerequisite {prereq_id} should appear before "
                        f"{section.section_id} but doesn't"
                    )

    def test_prerequisite_sections_populated(self, sample_chunks):
        """Sections with depends_on metadata should have prerequisite_sections."""
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)

        graph = GraphBuilder()
        sorted_sections = graph.build_and_sort(sections, sample_chunks)

        # At least one section should have prerequisites
        has_prereqs = any(s.prerequisite_sections for s in sorted_sections)
        assert has_prereqs, "Expected at least one section with prerequisites"

    def test_no_self_dependency(self, sample_chunks):
        """No section should list itself as a prerequisite."""
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)

        graph = GraphBuilder()
        sorted_sections = graph.build_and_sort(sections, sample_chunks)

        for section in sorted_sections:
            assert section.section_id not in section.prerequisite_sections

    def test_all_sections_present(self, sample_chunks):
        """Topological sort must include all sections, none dropped."""
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)
        original_ids = {s.section_id for s in sections}

        graph = GraphBuilder()
        sorted_sections = graph.build_and_sort(sections, sample_chunks)
        sorted_ids = {s.section_id for s in sorted_sections}

        assert sorted_ids == original_ids
