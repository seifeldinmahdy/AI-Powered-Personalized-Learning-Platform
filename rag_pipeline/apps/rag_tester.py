#!/usr/bin/env python3
"""Streamlit test app for the Conversational RAG pipeline.

Run:
    cd rag_pipeline/
    streamlit run apps/rag_tester.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from src.config.settings import get_settings
from src.llm.client import build_client_from_settings
from src.logger.setup import setup_logging
from src.indexing.store import VectorStore
from src.retrieval.engine import RAGEngine


# ── Initialization (cached across reruns) ─────────────────────────

@st.cache_resource
def _init_engine() -> RAGEngine:
    """Build the RAG engine once and cache it."""
    setup_logging()
    settings = get_settings()
    llm_client = build_client_from_settings(settings)
    return RAGEngine(settings=settings, llm_client=llm_client)


@st.cache_resource
def _init_store() -> VectorStore:
    """Build a VectorStore for fetching filter options."""
    settings = get_settings()
    return VectorStore(
        persist_dir=settings.chroma_db_path,
        collection_name=settings.chroma_collection_name,
    )


# ── UI ────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="RAG Tester",
        page_icon="📚",
        layout="wide",
    )

    st.title("📚 RAG Pipeline Tester")
    st.caption("Ask questions grounded in indexed course material.")

    # Sidebar — filters
    store = _init_store()

    st.sidebar.header("Filters")

    courses = ["(all)"] + store.get_all_metadata_values("course")
    selected_course = st.sidebar.selectbox("Course", courses)

    difficulties = ["(all)", "beginner", "intermediate", "expert"]
    selected_difficulty = st.sidebar.selectbox("Difficulty", difficulties)

    top_k = st.sidebar.slider("Top-K chunks", min_value=1, max_value=20, value=5)

    st.sidebar.divider()
    st.sidebar.metric("Indexed chunks", store.count)

    # Main area — question input
    question = st.text_area(
        "Your question",
        placeholder="e.g. What is the time complexity of binary search?",
        height=100,
    )

    if st.button("Ask", type="primary", disabled=not question.strip()):
        engine = _init_engine()

        course_filter = None if selected_course == "(all)" else selected_course
        diff_filter = None if selected_difficulty == "(all)" else selected_difficulty

        with st.spinner("Retrieving and generating answer…"):
            response = engine.ask(
                question=question.strip(),
                course=course_filter,
                difficulty=diff_filter,
                top_k=top_k,
            )

        # Answer
        st.subheader("Answer")
        st.markdown(response.answer)

        # Sources
        if response.sources:
            st.subheader("Sources")
            for i, src in enumerate(response.sources, 1):
                with st.expander(
                    f"Source {i}: {src.book} — pp. {src.page_start}-{src.page_end} "
                    f"(relevance: {src.relevance_score:.2%})"
                ):
                    st.markdown(f"**Topic:** {src.topic}  |  **Difficulty:** {src.difficulty}")
                    st.text(src.text[:1000])
        else:
            st.info("No sources were retrieved for this query.")


if __name__ == "__main__":
    main()
