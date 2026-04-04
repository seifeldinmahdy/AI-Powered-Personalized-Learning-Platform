"""Unit tests for the LLM response parser in ChunkAnalyzer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.indexing.analyzer import ChunkAnalyzer
from src.models.schemas import ChunkMetadata


# ── Parser tests (no real API calls) ─────────────────────────────


class TestParseResponse:
    """Tests for ChunkAnalyzer._parse_response — the JSON→ChunkMetadata logic."""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_llm_client: MagicMock):
        self.analyzer = ChunkAnalyzer(llm_client=mock_llm_client)

    def test_valid_response(self):
        data = {
            "topic": "linked lists",
            "difficulty": "beginner",
            "is_definitional": True,
            "depends_on": ["pointers"],
            "summary": "Introduces linked list basics.",
        }
        result = self.analyzer._parse_response(data, "chunk_0")
        assert isinstance(result, ChunkMetadata)
        assert result.topic == "linked lists"
        assert result.difficulty == "beginner"
        assert result.is_definitional is True
        assert result.depends_on == ["pointers"]

    def test_invalid_difficulty_coerced(self):
        data = {
            "topic": "arrays",
            "difficulty": "SUPER_HARD",
            "is_definitional": False,
            "depends_on": [],
            "summary": "Covers arrays.",
        }
        result = self.analyzer._parse_response(data, "chunk_1")
        assert result.difficulty == "beginner"  # coerced to default

    def test_depends_on_as_comma_string(self):
        data = {
            "topic": "hash tables",
            "difficulty": "intermediate",
            "is_definitional": False,
            "depends_on": "arrays, linked lists",
            "summary": "Hash table internals.",
        }
        result = self.analyzer._parse_response(data, "chunk_2")
        assert result.depends_on == ["arrays", "linked lists"]

    def test_depends_on_non_list_non_string(self):
        data = {
            "topic": "stacks",
            "difficulty": "beginner",
            "is_definitional": True,
            "depends_on": 42,
            "summary": "Stack basics.",
        }
        result = self.analyzer._parse_response(data, "chunk_3")
        assert result.depends_on == []

    def test_is_definitional_as_string(self):
        data = {
            "topic": "queues",
            "difficulty": "beginner",
            "is_definitional": "true",
            "depends_on": [],
            "summary": "Queue intro.",
        }
        result = self.analyzer._parse_response(data, "chunk_4")
        assert result.is_definitional is True

    def test_missing_fields_get_defaults(self):
        data = {}  # everything missing
        result = self.analyzer._parse_response(data, "chunk_5")
        assert result.topic == "unknown"
        assert result.difficulty == "beginner"
        assert result.is_definitional is False
        assert result.depends_on == []
        assert result.summary == ""


# ── Analyze integration (mocked LLM) ────────────────────────────


class TestAnalyze:
    def test_analyze_returns_metadata(self, mock_llm_client: MagicMock):
        analyzer = ChunkAnalyzer(llm_client=mock_llm_client)
        result = analyzer.analyze(
            chunk_text="Some CS text about trees.",
            chunk_id="test_0",
        )
        assert isinstance(result, ChunkMetadata)
        mock_llm_client.chat_json.assert_called_once()

    def test_analyze_propagates_runtime_error(self, mock_llm_client: MagicMock):
        mock_llm_client.chat_json.side_effect = RuntimeError("API down")
        analyzer = ChunkAnalyzer(llm_client=mock_llm_client)
        with pytest.raises(RuntimeError, match="API down"):
            analyzer.analyze(chunk_text="text", chunk_id="fail_0")
