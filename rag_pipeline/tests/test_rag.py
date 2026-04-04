"""Unit tests for the RAG query builder and retrieval pipeline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.models.schemas import RAGQuery, RAGResponse, SourceChunk
from src.retrieval.retriever import Retriever
from src.retrieval.generator import AnswerGenerator


# ── Filter construction ──────────────────────────────────────────


class TestBuildFilters:
    def test_no_filters(self):
        query = RAGQuery(question="What is a BST?")
        result = Retriever._build_filters(query)
        assert result is None

    def test_single_course_filter(self):
        query = RAGQuery(question="What is a BST?", course="data_structures")
        result = Retriever._build_filters(query)
        assert result == {"course": "data_structures"}

    def test_single_difficulty_filter(self):
        query = RAGQuery(question="Explain hashing", difficulty="expert")
        result = Retriever._build_filters(query)
        assert result == {"difficulty": "expert"}

    def test_multiple_filters_uses_and(self):
        query = RAGQuery(
            question="What is recursion?",
            course="python",
            difficulty="beginner",
        )
        result = Retriever._build_filters(query)
        assert "$and" in result
        conditions = result["$and"]
        assert {"course": "python"} in conditions
        assert {"difficulty": "beginner"} in conditions

    def test_all_three_filters(self):
        query = RAGQuery(
            question="Trees",
            course="ds",
            topic="binary tree",
            difficulty="intermediate",
        )
        result = Retriever._build_filters(query)
        assert "$and" in result
        assert len(result["$and"]) == 3


# ── Result parsing ───────────────────────────────────────────────


class TestParseResults:
    def test_parses_valid_results(self, mock_chroma_results: dict):
        sources = Retriever._parse_results(mock_chroma_results)
        assert len(sources) == 1
        src = sources[0]
        assert isinstance(src, SourceChunk)
        assert src.chunk_id == "test_book_1_0"
        assert src.book == "test_book"
        assert src.page_start == 1
        assert 0.0 <= src.relevance_score <= 1.0

    def test_empty_results(self):
        empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        sources = Retriever._parse_results(empty)
        assert sources == []

    def test_no_ids_key(self):
        sources = Retriever._parse_results({"ids": [], "documents": [], "metadatas": [], "distances": []})
        assert sources == []

    def test_relevance_score_range(self, mock_chroma_results: dict):
        # distance 0.25 → relevance = 1 - 0.25/2 = 0.875
        sources = Retriever._parse_results(mock_chroma_results)
        assert sources[0].relevance_score == pytest.approx(0.875, abs=0.01)


# ── Retriever integration (mocked store) ─────────────────────────


class TestRetriever:
    def test_retrieve_calls_store(self, mock_vector_store: MagicMock):
        retriever = Retriever(store=mock_vector_store)
        query = RAGQuery(question="What is a BST?", top_k=5)
        embedding = [0.1] * 384

        sources = retriever.retrieve(query_embedding=embedding, query=query)

        mock_vector_store.query.assert_called_once()
        assert len(sources) == 1


# ── Answer generator (mocked LLM) ────────────────────────────────


class TestAnswerGenerator:
    def test_generate_with_sources(self, mock_llm_client: MagicMock):
        mock_llm_client.chat.return_value = (
            "A BST is a binary tree where left < root < right. "
            "[Book: test_book, Pages: 1-1]"
        )
        gen = AnswerGenerator(llm_client=mock_llm_client)

        source = SourceChunk(
            chunk_id="test_0",
            text="BST definition text here.",
            book="test_book",
            page_start=1,
            page_end=1,
            relevance_score=0.9,
            topic="BST",
            difficulty="intermediate",
        )
        answer = gen.generate(question="What is a BST?", sources=[source])

        assert "BST" in answer
        mock_llm_client.chat.assert_called_once()

    def test_generate_no_sources(self, mock_llm_client: MagicMock):
        gen = AnswerGenerator(llm_client=mock_llm_client)
        answer = gen.generate(question="Unknown topic", sources=[])

        assert "could not find" in answer.lower()
        mock_llm_client.chat.assert_not_called()
