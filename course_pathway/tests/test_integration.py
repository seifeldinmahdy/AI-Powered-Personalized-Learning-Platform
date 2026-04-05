"""Integration tests — full pipeline with fixture data (no LLM, no ChromaDB).

These tests exercise the deterministic parts of the pipeline using
the old SectionBuilder/GraphBuilder path for backward compatibility,
plus the new top-down curriculum path.
"""

import tempfile
from collections import defaultdict
from pathlib import Path

from pathway.config import PathwaySettings
from pathway.discovery.graph_builder import GraphBuilder
from pathway.discovery.section_builder import SectionBuilder
from pathway.generator import PathwayGenerator, _find_chunks_for_topic
from pathway.models.schemas import (
    CourseChunk,
    DiscoveredSection,
    LLMCurriculumSession,
    SessionPlan,
    StudentContext,
)
from pathway.models.synthetic import SyntheticContextGenerator
from pathway.personalization.personalizer import Personalizer
from pathway.session.grouper import SessionGrouper
from pathway.storage.plan_store import PlanStore


class TestLegacyPipeline:
    """Backward-compatibility: SectionBuilder + GraphBuilder still work."""

    def test_section_builder_produces_sections(self, sample_chunks):
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)
        assert len(sections) > 0

    def test_graph_builder_sorts(self, sample_chunks):
        builder = SectionBuilder()
        sections = builder.discover_sections(sample_chunks)
        graph = GraphBuilder()
        sorted_sections = graph.build_and_sort(sections, sample_chunks)
        assert len(sorted_sections) == len(sections)


class TestNewPipeline:
    """Test the new top-down curriculum → personaliser → grouper path."""

    def _build_chunks_by_topic(self, chunks):
        result = defaultdict(list)
        for c in chunks:
            result[c.topic].append(c)
        return result

    def test_build_sections_from_curriculum(self, sample_chunks):
        """LLM curriculum → DiscoveredSections with correct chunks."""
        gen = PathwayGenerator.__new__(PathwayGenerator)
        gen._personalizer = Personalizer()
        gen._grouper = SessionGrouper(min_tokens=100, max_tokens=1000)

        curriculum = [
            LLMCurriculumSession(
                session_number=1,
                session_title="Variables and Basics",
                topics=["variables", "Variable Assignment", "strings"],
                difficulty="beginner",
            ),
            LLMCurriculumSession(
                session_number=2,
                session_title="Loops and Iteration",
                topics=["loops", "while loops", "for loops"],
                difficulty="beginner",
            ),
            LLMCurriculumSession(
                session_number=3,
                session_title="Functions and Recursion",
                topics=["functions", "recursion"],
                difficulty="intermediate",
            ),
            LLMCurriculumSession(
                session_number=4,
                session_title="Data Structures",
                topics=["lists", "dictionaries"],
                difficulty="intermediate",
            ),
        ]

        chunks_by_topic = self._build_chunks_by_topic(sample_chunks)

        sections, section_chunks = gen._build_sections_from_curriculum(
            curriculum, chunks_by_topic
        )

        assert len(sections) == 4
        assert sections[0].display_title == "Variables and Basics"
        assert sections[1].display_title == "Loops and Iteration"

        # Check that chunks are correctly assigned
        total_chunks = sum(len(v) for v in section_chunks.values())
        assert total_chunks > 0

        # Definitional chunks should come first
        for section_id, chunks in section_chunks.items():
            if len(chunks) >= 2:
                def_indices = [
                    i for i, c in enumerate(chunks) if c.is_definitional
                ]
                non_def_indices = [
                    i for i, c in enumerate(chunks) if not c.is_definitional
                ]
                if def_indices and non_def_indices:
                    assert max(def_indices) < min(non_def_indices), (
                        f"Definitional chunks not first in {section_id}"
                    )

    def test_personalise_new_sections(self, sample_chunks, novice_context):
        """Personaliser works on sections built from LLM curriculum."""
        gen = PathwayGenerator.__new__(PathwayGenerator)
        gen._personalizer = Personalizer()
        gen._grouper = SessionGrouper(min_tokens=100, max_tokens=1000)

        curriculum = [
            LLMCurriculumSession(
                session_number=1,
                session_title="Basics",
                topics=["variables", "strings"],
                difficulty="beginner",
            ),
            LLMCurriculumSession(
                session_number=2,
                session_title="Loops",
                topics=["loops", "while loops", "for loops"],
                difficulty="beginner",
            ),
        ]

        chunks_by_topic = self._build_chunks_by_topic(sample_chunks)
        sections, section_chunks_raw = gen._build_sections_from_curriculum(
            curriculum, chunks_by_topic
        )

        p_sections, p_chunks = gen._personalizer.personalize(
            sections, sample_chunks, novice_context
        )

        assert len(p_sections) > 0
        total = sum(len(v) for v in p_chunks.values())
        assert total > 0

    def test_group_sessions_from_new_pipeline(self, sample_chunks, novice_context):
        """Full new pipeline: curriculum → sections → personalise → group."""
        gen = PathwayGenerator.__new__(PathwayGenerator)
        gen._personalizer = Personalizer()
        gen._grouper = SessionGrouper(min_tokens=100, max_tokens=1000)

        curriculum = [
            LLMCurriculumSession(
                session_number=1,
                session_title="Basics",
                topics=["variables", "strings", "Variable Assignment"],
                difficulty="beginner",
            ),
            LLMCurriculumSession(
                session_number=2,
                session_title="Loops",
                topics=["loops", "while loops", "for loops"],
                difficulty="beginner",
            ),
            LLMCurriculumSession(
                session_number=3,
                session_title="Functions",
                topics=["functions", "recursion"],
                difficulty="intermediate",
            ),
            LLMCurriculumSession(
                session_number=4,
                session_title="Data Structures",
                topics=["lists", "dictionaries"],
                difficulty="intermediate",
            ),
        ]

        chunks_by_topic = self._build_chunks_by_topic(sample_chunks)
        sections, _ = gen._build_sections_from_curriculum(curriculum, chunks_by_topic)

        p_sections, p_chunks = gen._personalizer.personalize(
            sections, sample_chunks, novice_context
        )

        sessions = gen._grouper.group_sessions(p_sections, p_chunks)

        assert len(sessions) > 0
        total_chunks = sum(len(s.chunks) for s in sessions)
        assert total_chunks > 0


class TestTopicMatching:
    """Test _find_chunks_for_topic exact and fuzzy matching."""

    def test_exact_match(self, sample_chunks):
        chunks_by_topic = defaultdict(list)
        for c in sample_chunks:
            chunks_by_topic[c.topic].append(c)

        result = _find_chunks_for_topic("variables", chunks_by_topic)
        assert len(result) > 0
        assert all(c.topic == "variables" for c in result)

    def test_fuzzy_match(self, sample_chunks):
        chunks_by_topic = defaultdict(list)
        for c in sample_chunks:
            chunks_by_topic[c.topic].append(c)

        # "while loop" should match "while loops"
        result = _find_chunks_for_topic("while loop", chunks_by_topic)
        assert len(result) > 0

    def test_no_match_returns_empty(self, sample_chunks):
        chunks_by_topic = defaultdict(list)
        for c in sample_chunks:
            chunks_by_topic[c.topic].append(c)

        result = _find_chunks_for_topic("quantum computing", chunks_by_topic)
        assert result == []


class TestSyntheticGenerator:
    def test_deterministic_with_seed(self):
        gen = SyntheticContextGenerator(seed=123)
        ctx1 = gen.generate("s1", "c1", ["a", "b", "c", "d", "e"])
        gen2 = SyntheticContextGenerator(seed=123)
        ctx2 = gen2.generate("s1", "c1", ["a", "b", "c", "d", "e"])
        assert ctx1.mastery_level == ctx2.mastery_level
        assert ctx1.strengths == ctx2.strengths
        assert ctx1.weaknesses == ctx2.weaknesses

    def test_no_overlap_strengths_weaknesses(self):
        gen = SyntheticContextGenerator(seed=42)
        topics = [f"topic_{i}" for i in range(50)]
        ctx = gen.generate("s1", "c1", topics)

        overlap = set(ctx.strengths) & set(ctx.weaknesses)
        assert len(overlap) == 0, f"Overlap found: {overlap}"


class TestPlanStore:
    def test_save_and_load(self, sample_chunks, novice_context):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            store = PlanStore(db_path=db_path)

            # Build a plan using the legacy pipeline for simplicity
            builder = SectionBuilder()
            sections = builder.discover_sections(sample_chunks)
            graph = GraphBuilder()
            sorted_sections = graph.build_and_sort(sections, sample_chunks)
            personalizer = Personalizer()
            p_sections, p_chunks = personalizer.personalize(
                sorted_sections, sample_chunks, novice_context
            )
            grouper = SessionGrouper(min_tokens=100, max_tokens=1000)
            sessions = grouper.group_sessions(p_sections, p_chunks)

            plan = SessionPlan(
                student_id=novice_context.student_id,
                course_id=novice_context.course_id,
                sessions=sessions,
                total_sessions=len(sessions),
                total_chunks=sum(len(s.chunks) for s in sessions),
                student_context_hash=novice_context.context_hash(),
            )

            store.save(plan)

            loaded = store.load(novice_context.student_id, novice_context.course_id)
            assert loaded is not None
            assert loaded.total_sessions == plan.total_sessions
            assert loaded.student_context_hash == plan.student_context_hash

    def test_needs_regeneration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            store = PlanStore(db_path=db_path)

            assert store.needs_regeneration("s1", "c1", "hash_a")

    def test_context_hash_change(self):
        ctx1 = StudentContext(
            student_id="s1", course_id="c1", mastery_level="Novice",
            strengths=["a"], weaknesses=["b"],
        )
        ctx2 = StudentContext(
            student_id="s1", course_id="c1", mastery_level="Novice",
            strengths=["a"], weaknesses=["b", "c"],
        )
        assert ctx1.context_hash() != ctx2.context_hash()
