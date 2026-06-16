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
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
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


# ── Backward design: CLO concept set (replaces ChromaDB-topic discovery) ──────

import httpx  # noqa: E402

_DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")


def _fetch_clo_concepts(course_id: str) -> tuple[list[dict], list[dict]]:
    """Fetch the course's CLO concept set from Django.

    Returns one row per (CLO, concept): ``[{clo_code, clo_text, concept_id,
    label}]`` plus the raw CLO list. This is the backbone the placement test is
    backward-designed against — questions are generated to cover THIS set, not
    arbitrary chunks.
    """
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    headers = {"X-Service-Key": service_key} if service_key else {}
    base = _DJANGO_API_URL.rstrip("/")
    try:
        with httpx.Client(timeout=15.0) as client:
            clo_resp = client.get(f"{base}/courses/courses/{course_id}/clos/", headers=headers)
            con_resp = client.get(f"{base}/courses/courses/{course_id}/concepts/", headers=headers)
    except Exception as e:
        logger.warning("Failed to fetch CLO concepts for course %s: %s", course_id, e)
        return []

    if clo_resp.status_code != 200 or con_resp.status_code != 200:
        logger.warning(
            "CLO/concept fetch bad status for course %s: clos=%s concepts=%s",
            course_id, clo_resp.status_code, con_resp.status_code,
        )
        return [], []

    def _rows(payload):
        return payload.get("results", payload) if isinstance(payload, dict) else payload

    clos = _rows(clo_resp.json())
    concepts = _rows(con_resp.json())

    logger.info(
        "CLO/concept fetch succeeded for course %s: %d clos, %d concepts",
        course_id, len(clos), len(concepts),
    )

    if clos and not concepts:
        logger.info(
            "Course %s has %d CLO(s) but 0 concepts; using CLO-only plan.",
            course_id, len(clos),
        )

    label_map: dict[str, str] = {}
    for c in concepts:
        label_map[str(c["id"])] = c["label"]

    rows: list[dict] = []
    for clo in clos:
        for cid in clo.get("concepts", []):
            cid = str(cid)
            rows.append({
                "clo_code": clo.get("code", ""),
                "clo_text": clo.get("text", ""),
                "concept_id": cid,
                "label": label_map.get(cid, cid),
            })

    # Fallback: if CLOs and concepts both exist but no explicit links have been
    # made, treat all concepts as global context attached to every CLO. This
    # keeps the placement test backward-designed against real course content
    # instead of falling back to flat topic generation.
    if not rows and clos and concepts:
        logger.info(
            "No explicit CLO-concept links for course %s; falling back to global concepts.",
            course_id,
        )
        for clo in clos:
            for c in concepts:
                cid = str(c["id"])
                rows.append({
                    "clo_code": clo.get("code", ""),
                    "clo_text": clo.get("text", ""),
                    "concept_id": cid,
                    "label": c.get("label", cid),
                })

    return rows, clos


def build_clo_assessment_plan(course_id: str, course_title: str) -> list[dict]:
    """Group the CLO concept set into per-CLO categories for the placement test.

    The placement test is backward-designed: it probes the concepts the course's
    CLOs declare, NOT topics discovered from whatever chunks exist. Each returned
    category corresponds to a CLO and lists the concepts that CLO must teach.

    If the course has CLOs but no linked concepts, a CLO-only plan is returned
    (empty concept list per CLO) so the assessment can still be generated from
    the CLO outcome statements.

    Returns
    -------
    list[dict]
        ``[{"name", "description", "clo_code", "concepts": [{"id","label"}]}]``.
        Empty list only if the course has no CLOs at all.
    """
    rows, clos = _fetch_clo_concepts(course_id)
    if not clos:
        logger.warning("No CLOs for course %s — backward-designed plan empty.", course_id)
        return []

    by_clo: dict[str, dict] = {}
    seen_concept_per_clo: dict[str, set] = {}
    for r in rows:
        code = r["clo_code"] or "CLO"
        grp = by_clo.setdefault(code, {
            "name": code,
            "description": r["clo_text"] or f"{course_title} outcome {code}",
            "clo_code": code,
            "concepts": [],
        })
        seen = seen_concept_per_clo.setdefault(code, set())
        if r["concept_id"] not in seen:
            seen.add(r["concept_id"])
            grp["concepts"].append({"id": r["concept_id"], "label": r["label"]})

    # Ensure every CLO appears in the plan, even if it has no linked concepts.
    for clo in clos:
        code = clo.get("code") or "CLO"
        if code not in by_clo:
            by_clo[code] = {
                "name": code,
                "description": clo.get("text", f"{course_title} outcome {code}"),
                "clo_code": code,
                "concepts": [],
            }

    return list(by_clo.values())
