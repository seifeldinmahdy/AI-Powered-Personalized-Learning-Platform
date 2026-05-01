"""
Document Processor — Stage 1 of the presentation pipeline.

Converts a raw PDF into a structured DocumentPlan by:
1. Loading and chunking the PDF (existing pdf_loader)
2. Embedding chunks with sentence-transformers
3. Detecting topic boundaries via cosine similarity
4. Grouping chunks into sections
5. Generating section titles via TF-IDF keyphrase extraction
"""

import numpy as np
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer

from slide_gen.core.document_plan import DocumentPlan, Section
from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf


# =============================================================================
# EMBEDDING
# =============================================================================

# Lazy-loaded model to avoid import-time overhead
_embedding_model = None


def _get_embedding_model():
    """Lazy-load the sentence-transformers model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def embed_chunks(chunks: list[str]) -> np.ndarray:
    """
    Embed text chunks using a pre-trained sentence transformer.

    Args:
        chunks: List of text strings

    Returns:
        2D numpy array of shape (n_chunks, embedding_dim)
    """
    model = _get_embedding_model()
    embeddings = model.encode(chunks, show_progress_bar=False)
    return np.array(embeddings)


# =============================================================================
# TOPIC SEGMENTATION
# =============================================================================


def find_topic_boundaries(
    embeddings: np.ndarray,
    threshold: float = 0.65
) -> list[int]:
    """
    Detect topic boundaries by measuring cosine similarity drops
    between consecutive chunk embeddings.

    Args:
        embeddings: 2D array of chunk embeddings
        threshold: Similarity below this triggers a boundary

    Returns:
        List of chunk indices where new topics begin (always includes 0)
    """
    if len(embeddings) == 0:
        return []
    if len(embeddings) == 1:
        return [0]

    boundaries = [0]  # First chunk always starts a section

    for i in range(1, len(embeddings)):
        # Cosine similarity between normalized vectors
        sim = np.dot(embeddings[i], embeddings[i - 1]) / (
            np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[i - 1])
            + 1e-8
        )
        if sim < threshold:
            boundaries.append(i)

    return boundaries


def group_into_sections(
    chunks: list[str],
    boundaries: list[int]
) -> list[Section]:
    """
    Group consecutive chunks into sections based on topic boundaries.

    Args:
        chunks: All text chunks
        boundaries: Indices where new topics start

    Returns:
        List of Section objects
    """
    sections = []

    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(chunks)
        section_chunks = chunks[start:end]
        chunk_indices = list(range(start, end))

        sections.append(Section(
            id=i,
            title="",  # Will be filled by generate_section_titles
            chunks=section_chunks,
            chunk_indices=chunk_indices,
        ))

    return sections


# =============================================================================
# SECTION TITLE GENERATION
# =============================================================================


_title_model = None
_title_tokenizer = None

def _load_title_model():
    """Lazy-load Flan-T5-Small for title generation."""
    global _title_model, _title_tokenizer
    if _title_model is None:
        from transformers import T5ForConditionalGeneration, T5Tokenizer
        model_name = "google/flan-t5-small"
        _title_tokenizer = T5Tokenizer.from_pretrained(model_name, legacy=True)
        _title_model = T5ForConditionalGeneration.from_pretrained(model_name)
        _title_model.eval()
    return _title_model, _title_tokenizer


def generate_section_titles(
    sections: list[Section],
    all_chunks: list[str]
) -> list[Section]:
    """
    Generate readable short titles for each section using an AI summarizer.

    Args:
        sections: Sections with empty titles
        all_chunks: All chunks (unused in AI method, kept for signature)

    Returns:
        Sections with natural language titles filled in
    """
    if not sections:
        return sections

    try:
        model, tokenizer = _load_title_model()
    except Exception as e:
        print(f"Failed to load title model: {e}")
        model = None

    for section in sections:
        # We grab the first chunk to establish the title context, up to ~1000 chars
        context_text = section.chunks[0][:1000]
        
        if model is None:
            # Absolute fallback
            section.title = context_text.split(".")[0].strip()[:60].title()
            continue

        prompt = f"Write a very short, 3 to 5 word title for this text: {context_text}"
        inputs = tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
        
        try:
            outputs = model.generate(
                **inputs,
                max_length=12,        # Ensure output is very short
                num_beams=2,
                early_stopping=True,
            )
            title = tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
            # Fallback if generation is totally empty
            if len(title) < 2:
                title = context_text.split(".")[0].strip()[:60]
                
            # Clean up casing gracefully
            section.title = title.title()
        except Exception as e:
            # Fallback on failure
            print(f"Title generation failed: {e}")
            section.title = context_text.split(".")[0].strip()[:60].title()

    return sections


def generate_document_title(sections: list[Section]) -> str:
    """
    Generate an overall document title from the sections.

    Strategy: use the first section's title as the document title,
    since it typically introduces the document's main topic.

    Args:
        sections: List of sections with titles

    Returns:
        Document title string
    """
    if not sections:
        return "Untitled Presentation"

    # Use first section title as the main topic
    return sections[0].title


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def process_document(
    pdf_path: str | Path,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    similarity_threshold: float = 0.65,
) -> DocumentPlan:
    """
    Process a PDF document into a structured DocumentPlan.

    Full pipeline:
    1. Load PDF → text chunks
    2. Embed chunks with sentence-transformers
    3. Detect topic boundaries via cosine similarity
    4. Group chunks into sections
    5. Generate titles via TF-IDF

    Args:
        pdf_path: Path to PDF file
        chunk_size: Character limit per chunk
        chunk_overlap: Overlap between chunks
        similarity_threshold: Cosine similarity below this = topic boundary

    Returns:
        DocumentPlan with sections and titles
    """
    # Step 1: Load and chunk
    chunks = load_and_chunk_pdf(pdf_path, chunk_size, chunk_overlap)
    print(f"  Loaded {len(chunks)} chunks from PDF")

    if not chunks:
        return DocumentPlan(title="Empty Document", sections=[])

    # Step 2: Embed chunks
    embeddings = embed_chunks(chunks)
    print(f"  Generated embeddings: shape {embeddings.shape}")

    # Step 3: Find topic boundaries
    boundaries = find_topic_boundaries(embeddings, similarity_threshold)
    print(f"  Found {len(boundaries)} topic sections")

    # Step 4: Group into sections
    sections = group_into_sections(chunks, boundaries)

    # Step 5: Generate titles
    sections = generate_section_titles(sections, chunks)

    # Step 6: Generate document title
    doc_title = generate_document_title(sections)

    plan = DocumentPlan(title=doc_title, sections=sections)
    print(f"  Document plan: '{doc_title}' with {len(sections)} sections")
    for s in sections:
        print(f"    Section {s.id}: '{s.title}' ({len(s.chunks)} chunks)")

    return plan
