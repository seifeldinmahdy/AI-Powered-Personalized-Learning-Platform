"""Shared pytest fixtures: mock LLM client, mock VectorStore, sample data."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.llm.client import OllamaCloudClient
from src.models.schemas import ChunkMetadata, RawChunk, SourceChunk


# ── Sample data ──────────────────────────────────────────────────

SAMPLE_TEXT = (
    "A binary search tree (BST) is a node-based binary tree data structure "
    "which has the following properties. The left subtree of a node contains "
    "only nodes with keys lesser than the node's key. The right subtree of "
    "a node contains only nodes with keys greater than the node's key. "
    "The left and right subtree each must also be a binary search tree. "
    "There must be no duplicate nodes. Binary search trees support fast "
    "lookup, addition, and removal of items with average time complexity "
    "of O(log n) for each operation."
)

SAMPLE_METADATA_JSON = json.dumps(
    {
        "topic": "binary search tree",
        "difficulty": "intermediate",
        "is_definitional": True,
        "depends_on": ["binary tree", "recursion"],
        "summary": "Introduces BST properties and average-case time complexity.",
    }
)

SAMPLE_CHUNK_METADATA = ChunkMetadata(
    topic="binary search tree",
    difficulty="intermediate",
    is_definitional=True,
    depends_on=["binary tree", "recursion"],
    summary="Introduces BST properties and average-case time complexity.",
)


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def sample_text() -> str:
    return SAMPLE_TEXT


@pytest.fixture()
def sample_raw_chunk() -> RawChunk:
    return RawChunk(
        text=SAMPLE_TEXT,
        page_start=1,
        page_end=1,
        chunk_index=0,
        book_stem="test_book",
    )


@pytest.fixture()
def sample_metadata() -> ChunkMetadata:
    return SAMPLE_CHUNK_METADATA


@pytest.fixture()
def mock_llm_client() -> OllamaCloudClient:
    """An OllamaCloudClient whose chat/chat_json methods are mocked.

    By default ``chat_json`` returns a valid chunk-analysis JSON dict.
    Tests can override ``client.chat_json.return_value`` as needed.
    """
    client = MagicMock(spec=OllamaCloudClient)
    client.chat.return_value = SAMPLE_METADATA_JSON
    client.chat_json.return_value = json.loads(SAMPLE_METADATA_JSON)
    return client


@pytest.fixture()
def mock_chroma_results() -> dict[str, Any]:
    """A ChromaDB query-result dict with one hit."""
    return {
        "ids": [["test_book_1_0"]],
        "documents": [[SAMPLE_TEXT]],
        "metadatas": [
            [
                {
                    "topic": "binary search tree",
                    "difficulty": "intermediate",
                    "is_definitional": True,
                    "depends_on": '["binary tree", "recursion"]',
                    "summary": "Introduces BST properties.",
                    "book": "test_book",
                    "course": "test_book",
                    "page_start": 1,
                    "page_end": 1,
                    "chunk_index": 0,
                }
            ]
        ],
        "distances": [[0.25]],
    }


@pytest.fixture()
def mock_vector_store(mock_chroma_results: dict) -> MagicMock:
    """A mocked VectorStore whose ``query`` returns ``mock_chroma_results``."""
    store = MagicMock()
    store.query.return_value = mock_chroma_results
    store.get_existing_ids.return_value = set()
    store.count = 1
    return store
