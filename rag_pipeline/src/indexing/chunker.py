"""PDF text extraction and semantic chunking.

Uses PyMuPDF for extraction and the embedding model's tokenizer for
accurate token counting.  Never splits mid-sentence.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF
import structlog
from transformers import AutoTokenizer

from src.models.schemas import RawChunk

logger = structlog.get_logger(__name__)

# ── Sentence boundary regex ───────────────────────────────────────
# Splits after sentence-ending punctuation followed by whitespace and
# an uppercase letter.  Good enough for textbook prose; does not break
# on abbreviations like "e.g." because those are rarely followed by a
# capital letter without a true sentence boundary.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


# ── Text cleaning ────────────────────────────────────────────────

def _clean_page_text(text: str) -> str:
    """Normalize raw PDF-extracted text."""
    # Null bytes (OCR artifact)
    text = text.replace("\x00", "")
    # Fix mid-word hyphenation across lines
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Single newlines → spaces (paragraph flow)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    # Collapse multiple blank lines into one
    text = re.sub(r"\n{2,}", "\n", text)
    # Normalize runs of spaces
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping each sentence intact."""
    raw = _SENTENCE_BOUNDARY.split(text)
    return [s.strip() for s in raw if s.strip()]


# ── Data containers ──────────────────────────────────────────────

class _SentenceInfo:
    """Internal container pairing a sentence with its page and token count."""

    __slots__ = ("text", "page_num", "token_count")

    def __init__(self, text: str, page_num: int, token_count: int) -> None:
        self.text = text
        self.page_num = page_num
        self.token_count = token_count


# ── Public chunker ───────────────────────────────────────────────

class PDFChunker:
    """Extracts text from a PDF and splits it into overlapping semantic chunks.

    Parameters
    ----------
    embedding_model_name:
        HuggingFace model id whose tokenizer is used for token counting.
    chunk_min / chunk_max / chunk_target:
        Token-count window for each chunk.
    overlap:
        Number of overlap tokens between consecutive chunks.
    """

    def __init__(
        self,
        embedding_model_name: str,
        chunk_min: int = 300,
        chunk_max: int = 400,
        chunk_target: int = 350,
        overlap: int = 50,
    ) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(embedding_model_name)
        self.chunk_min = chunk_min
        self.chunk_max = chunk_max
        self.chunk_target = chunk_target
        self.overlap = overlap

    # ── helpers ───────────────────────────────────────────────────

    def count_tokens(self, text: str) -> int:
        """Return the token count for *text* using the embedding tokenizer."""
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    @staticmethod
    def extract_pages(pdf_path: str | Path) -> list[tuple[int, str]]:
        """Return list of (1-indexed page_num, cleaned_text) pairs."""
        doc = fitz.open(str(pdf_path))
        pages: list[tuple[int, str]] = []
        for idx in range(len(doc)):
            raw = doc[idx].get_text("text")
            cleaned = _clean_page_text(raw)
            if cleaned:
                pages.append((idx + 1, cleaned))
        doc.close()
        return pages

    # ── main entry point ─────────────────────────────────────────

    def chunk_pdf(self, pdf_path: str | Path, book_stem: str) -> list[RawChunk]:
        """Chunk a single PDF into a list of ``RawChunk`` objects.

        Each chunk targets *chunk_target* tokens, stays within
        [chunk_min, chunk_max], and overlaps the previous chunk by
        ~*overlap* tokens.  Sentences are never split.
        """
        pages = self.extract_pages(pdf_path)
        if not pages:
            logger.warning("pdf_empty", pdf_path=str(pdf_path))
            return []

        # Flatten all pages into sentence-level metadata
        sentences: list[_SentenceInfo] = []
        for page_num, text in pages:
            for sent_text in _split_sentences(text):
                token_count = self.count_tokens(sent_text)
                if token_count == 0:
                    continue
                sentences.append(
                    _SentenceInfo(
                        text=sent_text,
                        page_num=page_num,
                        token_count=token_count,
                    )
                )

        if not sentences:
            logger.warning("pdf_no_sentences", pdf_path=str(pdf_path))
            return []

        chunks: list[RawChunk] = []
        chunk_index = 0
        current: list[_SentenceInfo] = []
        current_tokens = 0
        idx = 0

        while idx < len(sentences):
            sent = sentences[idx]

            # If adding this sentence would bust the max AND we already
            # have enough content, flush the current chunk.
            if (
                current_tokens + sent.token_count > self.chunk_max
                and current_tokens >= self.chunk_min
            ):
                chunk_text = " ".join(s.text for s in current)
                chunks.append(
                    RawChunk(
                        text=chunk_text,
                        page_start=current[0].page_num,
                        page_end=current[-1].page_num,
                        chunk_index=chunk_index,
                        book_stem=book_stem,
                    )
                )
                chunk_index += 1

                # Build overlap from the tail of the flushed chunk
                overlap_sents: list[_SentenceInfo] = []
                overlap_tok = 0
                for s in reversed(current):
                    if overlap_tok + s.token_count > self.overlap:
                        break
                    overlap_sents.insert(0, s)
                    overlap_tok += s.token_count

                current = list(overlap_sents)
                current_tokens = overlap_tok
                # Do NOT increment idx — this sentence still needs to be
                # added to the new chunk.
                continue

            current.append(sent)
            current_tokens += sent.token_count
            idx += 1

        # Flush remaining sentences as the final chunk
        if current:
            chunk_text = " ".join(s.text for s in current)
            chunks.append(
                RawChunk(
                    text=chunk_text,
                    page_start=current[0].page_num,
                    page_end=current[-1].page_num,
                    chunk_index=chunk_index,
                    book_stem=book_stem,
                )
            )

        logger.info(
            "chunking_complete",
            pdf=str(pdf_path),
            total_chunks=len(chunks),
            total_sentences=len(sentences),
        )
        return chunks
