"""
Category Service — LLM-powered topic grouping for placement tests.

Performs a two-step filtering pipeline before asking the LLM to group
topics into categories:

  Step 1 — Semantic Deduplication:
    Embeds all raw topic tags using sentence-transformers/all-MiniLM-L6-v2,
    clusters them at a cosine similarity threshold of 0.82, and keeps only
    the most frequent variant per cluster as the canonical representative.

  Step 2 — Frequency Filtering:
    Queries ChromaDB for chunk counts, discards topics with fewer than 3
    chunks, and keeps the top 30 by chunk count.

Only the resulting ≤30 canonical topics are sent to the LLM, which groups
them into exactly 5 pedagogical categories.
"""

from __future__ import annotations

import os
import sys
import json
import logging
from pathlib import Path
from collections import defaultdict

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

# Ensure course_pathway/src and rag_pipeline are on sys.path
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)
_rag_dir = str(Path(__file__).resolve().parent.parent.parent / "rag_pipeline")
if _rag_dir not in sys.path:
    sys.path.insert(0, _rag_dir)

from pathway.llm.naming import OllamaClient  # type: ignore
from pathway.config import get_settings  # type: ignore
from src.indexing.store import VectorStore  # type: ignore
from src.retrieval.retrieval_service import RetrievalService, RetrievalScope  # type: ignore

logger = logging.getLogger(__name__)

# ── Singletons ──────────────────────────────────────────────────

_client: OllamaClient | None = None
_service: RetrievalService | None = None
_embedder: SentenceTransformer | None = None

_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _get_ollama_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=180,
        )
    return _client


def _get_service() -> RetrievalService:
    """The single scoped retrieval entry point for assessment topic reads."""
    global _service
    if _service is None:
        settings = get_settings()
        store = VectorStore(
            persist_dir=settings.chroma_db_path,
            collection_name=settings.chroma_collection_name,
        )
        _service = RetrievalService(store=store)
    return _service


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        logger.info("Loading sentence-transformers model: %s", _EMBEDDING_MODEL)
        _embedder = SentenceTransformer(_EMBEDDING_MODEL)
        logger.info("Sentence-transformers model loaded")
    return _embedder


# ── Public API ──────────────────────────────────────────────────


def get_course_topics(scope: RetrievalScope) -> list[str]:
    """Get unique topic tags for a corpus scope (via the scoped service)."""
    try:
        return _get_service().get_topics(scope)
    except Exception as e:
        logger.warning("Failed to read scoped topics: %s", e)
        return []


def get_topic_chunk_counts(scope: RetrievalScope) -> dict[str, int]:
    """Get topic → chunk_count mapping for a corpus scope."""
    try:
        return _get_service().get_topic_summary(scope)
    except Exception as e:
        logger.warning("Failed to read scoped topic summary: %s", e)
        return {}


# ── Step 1: Semantic Deduplication ──────────────────────────────


def deduplicate_topics(
    topics: list[str],
    topic_counts: dict[str, int],
    similarity_threshold: float = 0.82,
) -> tuple[list[str], dict[str, list[str]]]:
    """Cluster semantically similar topics and keep the most frequent variant.

    Parameters
    ----------
    topics :
        All unique topic strings from ChromaDB.
    topic_counts :
        topic → chunk_count for frequency-based representative selection.
    similarity_threshold :
        Cosine similarity above which two topics are considered duplicates.

    Returns
    -------
    canonical_topics :
        Deduplicated list of canonical topic names.
    variant_map :
        Mapping from each canonical topic to all its variant strings
        (including itself).
    """
    if len(topics) <= 1:
        return topics, {t: [t] for t in topics}

    embedder = _get_embedder()
    embeddings = embedder.encode(topics, convert_to_numpy=True, show_progress_bar=False)

    # Pairwise cosine similarity
    sim_matrix = cosine_similarity(embeddings)

    # Union-Find clustering
    n = len(topics)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i][j] >= similarity_threshold:
                union(i, j)

    # Group topics by cluster
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    # Pick the most frequent topic string as the canonical representative
    canonical_topics: list[str] = []
    variant_map: dict[str, list[str]] = {}

    for indices in clusters.values():
        cluster_topics = [topics[i] for i in indices]
        # Sort by chunk count descending, then alphabetically for tie-breaking
        best = max(cluster_topics, key=lambda t: (topic_counts.get(t, 0), t))
        canonical_topics.append(best)
        variant_map[best] = sorted(cluster_topics)

    logger.info(
        "semantic_dedup_complete",
        extra={
            "raw_count": len(topics),
            "canonical_count": len(canonical_topics),
            "clusters": len(clusters),
        },
    )
    return sorted(canonical_topics), variant_map


# ── Step 2: Frequency Filtering ────────────────────────────────


def filter_by_frequency(
    canonical_topics: list[str],
    variant_map: dict[str, list[str]],
    topic_counts: dict[str, int],
    min_chunks: int = 3,
    top_n: int = 30,
) -> tuple[list[str], dict[str, list[str]]]:
    """Keep the top N canonical topics by total chunk count.

    Parameters
    ----------
    canonical_topics :
        Deduplicated canonical topic names.
    variant_map :
        canonical → list of all variant topic strings.
    topic_counts :
        raw topic → chunk count from ChromaDB.
    min_chunks :
        Minimum total chunks across all variants to keep a topic.
    top_n :
        Maximum number of topics to pass to the LLM.

    Returns
    -------
    filtered_topics :
        Up to *top_n* canonical topic names sorted by chunk count desc.
    filtered_variant_map :
        Variant map limited to the filtered topics.
    """
    # Compute total chunk count for each canonical topic across all variants
    scored: list[tuple[str, int]] = []
    for canon in canonical_topics:
        total = sum(topic_counts.get(v, 0) for v in variant_map.get(canon, [canon]))
        if total >= min_chunks:
            scored.append((canon, total))

    # Sort by chunk count descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Keep top N
    filtered = scored[:top_n]
    filtered_topics = [t for t, _ in filtered]
    filtered_variant_map = {t: variant_map.get(t, [t]) for t in filtered_topics}

    logger.info(
        "frequency_filter_complete",
        extra={
            "input_count": len(canonical_topics),
            "filtered_count": len(filtered_topics),
            "min_chunks": min_chunks,
            "top_n": top_n,
        },
    )
    return filtered_topics, filtered_variant_map


# ── LLM Category Grouping ──────────────────────────────────────


def group_topics_into_categories(
    course_title: str,
    topics: list[str],
    variant_map: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Use the LLM to group canonical topics into exactly 5 categories.

    Parameters
    ----------
    course_title :
        Human-readable course name.
    topics :
        Filtered canonical topic names (≤30).
    variant_map :
        Optional mapping from canonical → variant topic strings.
        When present, the returned categories include an ``all_topics``
        field listing every variant string for ChromaDB querying.

    Returns
    -------
    list[dict]
        Each dict: ``{"name", "description", "topics", "all_topics"}``.
    """
    if not topics:
        return [{"name": "General", "description": f"General knowledge of {course_title}.", "topics": [], "all_topics": []}]

    client = _get_ollama_client()

    prompt = f"""You are a curriculum designer. Given the course "{course_title}" and these {len(topics)} topic tags extracted from its textbook:

{json.dumps(topics)}

Group these topics into exactly 5 high-level pedagogically meaningful categories that represent the major conceptual pillars of the course. Each category needs:
- A clear, concise category name (e.g. "Control Flow", "Data Structures")
- A one-line description of what this section tests
- The list of raw topic tags that belong to it

Every topic tag must appear in exactly one category. No topic left out, no duplicates.

Return ONLY valid JSON with no markdown fences:
{{
  "categories": [
    {{
      "name": "Category Name",
      "description": "One line describing what this section covers.",
      "topics": ["topic_tag_1", "topic_tag_2"]
    }}
  ]
}}"""

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            data = client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                timeout_override=180,
            )

            categories = data.get("categories", [])
            if not isinstance(categories, list) or len(categories) == 0:
                raise ValueError("No categories returned")

            # Validate: every topic assigned exactly once
            assigned: list[str] = []
            for cat in categories:
                assigned.extend(cat.get("topics", []))

            missing = set(topics) - set(assigned)

            if missing:
                logger.warning("Topics missing from categories (attempt %d): %s", attempt, missing)
                if attempt < max_retries:
                    continue
                # On final attempt, add missing to the smallest category
                smallest = min(categories, key=lambda c: len(c.get("topics", [])))
                smallest["topics"].extend(list(missing))

            # Expand variant_map into all_topics for ChromaDB querying
            if variant_map:
                for cat in categories:
                    all_topics: list[str] = []
                    for t in cat.get("topics", []):
                        all_topics.extend(variant_map.get(t, [t]))
                    cat["all_topics"] = sorted(set(all_topics))
            else:
                for cat in categories:
                    cat["all_topics"] = cat.get("topics", [])

            logger.info(
                "category_grouping_complete",
                extra={"num_categories": len(categories), "attempt": attempt},
            )
            return categories

        except Exception as e:
            logger.error("Category grouping failed (attempt %d): %s", attempt, e)
            if attempt >= max_retries:
                break

    logger.warning("All category grouping attempts failed — using single category fallback")
    all_topics = []
    if variant_map:
        for t in topics:
            all_topics.extend(variant_map.get(t, [t]))
    else:
        all_topics = topics
    return [{"name": "General", "description": f"General knowledge of {course_title}.", "topics": topics, "all_topics": sorted(set(all_topics))}]


# ── Orchestrator ────────────────────────────────────────────────


def build_assessment_categories(course_title: str, scope: RetrievalScope) -> list[dict]:
    """Full pipeline: scoped topic read → dedup → filter → LLM grouping.

    This is the single entry point called by the router. Topics are read ONLY
    from the given corpus scope — the old fuzzy ``course_title``→ChromaDB-course
    matcher is gone, so the assessment generator can no longer accidentally read
    another course's topics. ``course_title`` is kept solely as a human label for
    the LLM grouping prompt.

    Returns
    -------
    list[dict]
        Exactly 5 categories (or 1 "General" fallback), each with:
        ``name``, ``description``, ``topics`` (canonical), ``all_topics``.
    """
    scope.validate()

    # Fetch raw topics and chunk counts from the scoped corpus
    raw_topics = get_course_topics(scope)
    topic_counts = get_topic_chunk_counts(scope)

    logger.info(
        "Raw topics for corpus '%s' (course '%s'): %d",
        scope.corpus_id, course_title, len(raw_topics),
    )

    if not raw_topics:
        return [{"name": "General", "description": f"General knowledge of {course_title}.", "topics": [], "all_topics": []}]

    # Step 1: Semantic deduplication
    canonical, variant_map = deduplicate_topics(raw_topics, topic_counts)
    logger.info("After dedup: %d canonical topics", len(canonical))

    # Step 2: Frequency filtering
    filtered, filtered_variants = filter_by_frequency(
        canonical, variant_map, topic_counts,
        min_chunks=3, top_n=30,
    )
    logger.info("After frequency filter: %d topics", len(filtered))

    # Step 3: LLM grouping into exactly 5 categories
    categories = group_topics_into_categories(course_title, filtered, filtered_variants)

    return categories

