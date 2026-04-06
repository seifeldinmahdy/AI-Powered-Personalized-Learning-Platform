"""Shared pytest fixtures: mock ChromaDB data, mock LLM, sample contexts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Ensure src is importable
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pathway.models.schemas import CourseChunk, StudentContext


# ── Sample chunks ────────────────────────────────────────────────

def _make_chunk(
    idx: int,
    topic: str,
    difficulty: str = "beginner",
    is_def: bool = False,
    depends_on: list[str] | None = None,
    book: str = "test_book",
) -> CourseChunk:
    return CourseChunk(
        chunk_id=f"{book}_{idx}_{idx}",
        raw_text=f"This is chunk {idx} about {topic}. " * 20,  # ~100 words
        topic=topic,
        difficulty=difficulty,
        is_definitional=is_def,
        depends_on=depends_on or [],
        summary=f"Chunk {idx} covers {topic}.",
        book=book,
        course="test_course",
        page_start=idx * 2,
        page_end=idx * 2 + 1,
        chunk_index=idx,
    )


SAMPLE_CHUNKS: list[CourseChunk] = [
    # Section: variables (3 chunks)
    _make_chunk(0, "variables", "beginner", is_def=True),
    _make_chunk(1, "variables", "beginner"),
    _make_chunk(2, "variables", "intermediate"),
    # Section: Variable Assignment (fuzzy match to "variables")
    _make_chunk(3, "Variable Assignment", "beginner", is_def=True),
    # Section: loops (4 chunks)
    _make_chunk(4, "loops", "beginner", is_def=True, depends_on=["variables"]),
    _make_chunk(5, "loops", "intermediate", depends_on=["variables"]),
    _make_chunk(6, "loops", "intermediate"),
    _make_chunk(7, "loops", "expert"),
    # Section: while loops (2 chunks)
    _make_chunk(8, "while loops", "intermediate", is_def=True, depends_on=["loops"]),
    _make_chunk(9, "while loops", "intermediate", depends_on=["loops"]),
    # Section: for loops (2 chunks)
    _make_chunk(10, "for loops", "intermediate", is_def=True, depends_on=["loops"]),
    _make_chunk(11, "for loops", "expert", depends_on=["loops", "variables"]),
    # Section: recursion (3 chunks)
    _make_chunk(12, "recursion", "expert", is_def=True, depends_on=["functions", "loops"]),
    _make_chunk(13, "recursion", "expert", depends_on=["functions"]),
    _make_chunk(14, "recursion", "expert"),
    # Section: functions (3 chunks)
    _make_chunk(15, "functions", "beginner", is_def=True, depends_on=["variables"]),
    _make_chunk(16, "functions", "intermediate", depends_on=["variables"]),
    _make_chunk(17, "functions", "expert"),
    # Section: strings (2 chunks, no deps)
    _make_chunk(18, "strings", "beginner", is_def=True),
    _make_chunk(19, "strings", "beginner"),
    # Section: lists (3 chunks)
    _make_chunk(20, "lists", "beginner", is_def=True, depends_on=["variables"]),
    _make_chunk(21, "lists", "intermediate"),
    _make_chunk(22, "lists", "expert", depends_on=["loops"]),
    # Section: dictionaries (2 chunks)
    _make_chunk(23, "dictionaries", "intermediate", is_def=True, depends_on=["variables", "loops"]),
    _make_chunk(24, "dictionaries", "expert", depends_on=["lists"]),
]


@pytest.fixture()
def sample_chunks() -> list[CourseChunk]:
    return list(SAMPLE_CHUNKS)


@pytest.fixture()
def novice_context() -> StudentContext:
    return StudentContext(
        student_id="test_novice",
        course_id="test_course",
        mastery_level="Novice",
        strengths=["strings"],
        weaknesses=["recursion", "loops"],
    )


@pytest.fixture()
def expert_context() -> StudentContext:
    return StudentContext(
        student_id="test_expert",
        course_id="test_course",
        mastery_level="Expert",
        strengths=["variables", "loops", "strings"],
        weaknesses=["recursion"],
    )


@pytest.fixture()
def intermediate_context() -> StudentContext:
    return StudentContext(
        student_id="test_intermediate",
        course_id="test_course",
        mastery_level="Intermediate",
        strengths=[],
        weaknesses=[],
    )
