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


def generate_section_titles(
    sections: list[Section],
    all_chunks: list[str]
) -> list[Section]:
    """
    Generate titles for each section using TF-IDF keyphrase extraction.

    Finds the most distinctive words in each section compared to the
    full document, then forms a readable title.

    Args:
        sections: Sections with empty titles
        all_chunks: All chunks for corpus-level TF-IDF

    Returns:
        Sections with titles filled in
    """
    if not sections:
        return sections

    # Build a "document" per section by joining its chunks
    section_texts = [" ".join(s.chunks) for s in sections]

    # Fit TF-IDF on all individual chunks for better IDF scores
    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=200,
        ngram_range=(1, 2),  # Unigrams and bigrams
        min_df=1,
        max_df=0.9,
    )
    vectorizer.fit(all_chunks)

    feature_names = vectorizer.get_feature_names_out()

    for section in sections:
        section_text = " ".join(section.chunks)
        tfidf_vector = vectorizer.transform([section_text]).toarray()[0]

        # Get top 3 terms by TF-IDF score
        top_indices = tfidf_vector.argsort()[-3:][::-1]
        top_terms = [feature_names[idx] for idx in top_indices if tfidf_vector[idx] > 0]

        if top_terms:
            # Capitalize and join into a readable title
            section.title = " & ".join(term.title() for term in top_terms[:3])
        else:
            # Fallback: use first sentence of first chunk
            first_sentence = section.chunks[0].split(".")[0].strip()
            section.title = first_sentence[:60]

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
