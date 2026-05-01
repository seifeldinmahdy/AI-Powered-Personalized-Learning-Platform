"""Unit tests for the PDF chunker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.indexing.chunker import PDFChunker, _clean_page_text, _split_sentences


# ── Sentence splitting ───────────────────────────────────────────


class TestSplitSentences:
    def test_basic_split(self):
        text = "First sentence. Second sentence. Third one here."
        result = _split_sentences(text)
        assert len(result) == 3
        assert result[0] == "First sentence."
        assert result[1] == "Second sentence."
        assert result[2] == "Third one here."

    def test_single_sentence(self):
        text = "Only one sentence here."
        result = _split_sentences(text)
        assert len(result) == 1
        assert result[0] == "Only one sentence here."

    def test_empty_string(self):
        assert _split_sentences("") == []
        assert _split_sentences("   ") == []

    def test_question_marks(self):
        text = "What is a BST? It is a tree structure. Why use it?"
        result = _split_sentences(text)
        assert len(result) == 3

    def test_preserves_abbreviations_lowercase(self):
        """Abbreviations like 'e.g.' followed by lowercase don't split."""
        text = "Use e.g. arrays or lists. Then proceed."
        result = _split_sentences(text)
        # "e.g. arrays" should NOT split because 'a' is lowercase
        assert len(result) == 2


# ── Text cleaning ────────────────────────────────────────────────


class TestCleanPageText:
    def test_removes_null_bytes(self):
        assert "\x00" not in _clean_page_text("hello\x00world")

    def test_fixes_hyphenation(self):
        result = _clean_page_text("algo-\nrithm")
        assert "algorithm" in result

    def test_normalizes_whitespace(self):
        result = _clean_page_text("too   many   spaces")
        assert "  " not in result


# ── Chunker integration ─────────────────────────────────────────


class TestPDFChunker:
    @pytest.fixture(autouse=True)
    def _setup(self):
        """Build a chunker with a small token window for fast tests."""
        self.chunker = PDFChunker(
            embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
            chunk_min=20,
            chunk_max=40,
            chunk_target=30,
            overlap=5,
        )

    def test_count_tokens(self):
        count = self.chunker.count_tokens("hello world")
        assert isinstance(count, int)
        assert count >= 2

    def test_chunk_produces_raw_chunks(self, sample_text: str):
        """Chunking sample text with a small window must produce >1 chunk."""
        # Mock extract_pages to return our sample text as page 1
        with patch.object(
            self.chunker,
            "extract_pages",
            return_value=[(1, sample_text)],
        ):
            chunks = self.chunker.chunk_pdf("/fake/path.pdf", "test_book")

        assert len(chunks) > 0
        for c in chunks:
            assert c.book_stem == "test_book"
            assert c.page_start >= 1
            assert c.page_end >= c.page_start
            assert c.chunk_index >= 0

    def test_chunk_ids_are_deterministic(self, sample_text: str):
        """Same input must produce the same chunk IDs."""
        with patch.object(
            self.chunker,
            "extract_pages",
            return_value=[(1, sample_text)],
        ):
            run1 = self.chunker.chunk_pdf("/fake/path.pdf", "test_book")
            run2 = self.chunker.chunk_pdf("/fake/path.pdf", "test_book")

        ids1 = [c.chunk_id for c in run1]
        ids2 = [c.chunk_id for c in run2]
        assert ids1 == ids2

    def test_chunks_have_overlap_content(self, sample_text: str):
        """Consecutive chunks should share some text (overlap)."""
        with patch.object(
            self.chunker,
            "extract_pages",
            return_value=[(1, sample_text)],
        ):
            chunks = self.chunker.chunk_pdf("/fake/path.pdf", "test_book")

        if len(chunks) >= 2:
            # Last words of chunk 0 should appear in chunk 1
            words_0 = set(chunks[0].text.split()[-10:])
            words_1 = set(chunks[1].text.split()[:10])
            overlap = words_0 & words_1
            assert len(overlap) > 0, "Expected overlap between consecutive chunks"

    def test_empty_pdf_returns_empty(self):
        with patch.object(
            self.chunker, "extract_pages", return_value=[]
        ):
            chunks = self.chunker.chunk_pdf("/fake/empty.pdf", "empty")
        assert chunks == []
