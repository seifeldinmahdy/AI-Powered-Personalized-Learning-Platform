"""Tests for SectionBuilder — topic canonicalisation and chunk grouping."""

from pathway.discovery.section_builder import SectionBuilder, _normalise_topic
from pathway.models.schemas import CourseChunk


class TestNormaliseTopic:
    def test_lowercase_strip(self):
        assert _normalise_topic("  While Loops  ") == "while loops"

    def test_remove_punctuation(self):
        assert _normalise_topic("C++ Programming!") == "c programming"

    def test_collapse_whitespace(self):
        assert _normalise_topic("binary   search   tree") == "binary search tree"

    def test_empty(self):
        assert _normalise_topic("") == ""


class TestSectionBuilder:
    def test_empty_input(self):
        builder = SectionBuilder()
        assert builder.discover_sections([]) == []

    def test_groups_by_topic(self, sample_chunks):
        builder = SectionBuilder(similarity_threshold=0.85)
        sections = builder.discover_sections(sample_chunks)

        # Should have fewer sections than unique raw topics due to merging
        raw_topics = {c.topic for c in sample_chunks}
        assert len(sections) <= len(raw_topics)
        assert len(sections) > 0

    def test_fuzzy_merge(self, sample_chunks):
        """Near-duplicate topics should merge at a permissive threshold."""
        builder = SectionBuilder(similarity_threshold=0.60)
        sections = builder.discover_sections(sample_chunks)

        # With a 0.60 threshold, 'Variable Assignment' should merge into 'variables'
        section_topics = {s.canonical_topic for s in sections}
        assert not (
            "variables" in section_topics and "variable assignment" in section_topics
        ), "Expected fuzzy merge of 'variables' and 'variable assignment' at threshold 0.60"

    def test_definitional_first(self, sample_chunks):
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)

        for section in sections:
            if len(section.chunk_ids) > 1 and section.has_definitional_chunks:
                # First chunk should be definitional
                first_id = section.chunk_ids[0]
                chunk = next(c for c in sample_chunks if c.chunk_id == first_id)
                assert chunk.is_definitional, (
                    f"Section {section.section_id}: first chunk should be definitional"
                )

    def test_difficulty_distribution(self, sample_chunks):
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)

        for section in sections:
            total = sum(section.difficulty_distribution.values())
            assert total == len(section.chunk_ids)

    def test_all_chunks_assigned(self, sample_chunks):
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)

        all_assigned = set()
        for section in sections:
            all_assigned.update(section.chunk_ids)

        original_ids = {c.chunk_id for c in sample_chunks}
        assert all_assigned == original_ids, "Every chunk must be assigned to exactly one section"
