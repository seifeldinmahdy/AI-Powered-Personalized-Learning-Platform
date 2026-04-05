#!/usr/bin/env python3
"""Streamlit test app for the Course Pathway Generator.

Run:
    cd course_pathway/
    source .venv/bin/activate
    PYTHONPATH=src streamlit run apps/pathway_tester.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Ensure src is importable
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st

from pathway.chromadb_reader import ChromaDBReader
from pathway.config import get_settings
from pathway.discovery.graph_builder import GraphBuilder
from pathway.discovery.section_builder import SectionBuilder
from pathway.generator import PathwayGenerator
from pathway.llm.naming import OllamaClient
from pathway.models.schemas import StudentContext
from pathway.models.synthetic import SyntheticContextGenerator
from pathway.personalization.personalizer import Personalizer
from pathway.session.grouper import SessionGrouper
from pathway.storage.plan_store import PlanStore


# ── Cached resources ─────────────────────────────────────────────

@st.cache_resource
def _init_reader():
    settings = get_settings()
    return ChromaDBReader(
        persist_dir=settings.chroma_db_path,
        collection_name=settings.chroma_collection_name,
    )


@st.cache_resource
def _init_generator():
    settings = get_settings()
    reader = _init_reader()
    store = PlanStore(db_path=settings.sqlite_db_path)

    llm_client = None
    if settings.ollama_api_key:
        llm_client = OllamaClient(
            host=settings.ollama_host,
            model=settings.ollama_model,
            api_key=settings.ollama_api_key,
            max_retries=settings.max_retries,
        )

    return PathwayGenerator(
        settings=settings,
        reader=reader,
        store=store,
        llm_client=llm_client,
    )


# ── Main UI ──────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Course Pathway Generator",
        page_icon="🗺️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Custom styling
    st.markdown("""
    <style>
        .stMetric .metric-container { background: #1e1e2e; border-radius: 10px; padding: 12px; }
        .session-card { 
            background: linear-gradient(135deg, #1e1e2e, #2a2a4a); 
            border-radius: 12px; padding: 16px; margin: 8px 0;
            border-left: 4px solid #7c3aed;
        }
        .chunk-card {
            background: #2a2a3a; border-radius: 8px; padding: 12px; margin: 4px 0;
            border-left: 3px solid #06b6d4;
        }
        .section-badge {
            display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 0.75em; font-weight: 600; margin: 2px;
        }
        .badge-beginner { background: #166534; color: #bbf7d0; }
        .badge-intermediate { background: #854d0e; color: #fde68a; }
        .badge-expert { background: #7f1d1d; color: #fecaca; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🗺️ Course Pathway Generator")
    st.caption("Personalised session-by-session learning plans from your indexed textbooks")

    reader = _init_reader()
    courses = reader.get_available_courses()

    # ── Sidebar: Student Profile ─────────────────────────────────
    st.sidebar.header("📋 Student Profile")

    student_id = st.sidebar.text_input("Student ID", value="test_student_001")

    selected_course = st.sidebar.selectbox(
        "Course", courses, index=courses.index("pythonlearn") if "pythonlearn" in courses else 0
    )

    mastery = st.sidebar.select_slider(
        "Mastery Level",
        options=["Novice", "Intermediate", "Expert"],
        value="Intermediate",
    )

    composition = st.sidebar.selectbox(
        "Composition Mode",
        ["balanced", "visual_heavy", "text_heavy"],
    )

    language = st.sidebar.selectbox(
        "Language Proficiency",
        ["Elementary", "Intermediate", "Advanced", "Native"],
        index=1,
    )

    use_synthetic = st.sidebar.checkbox("🧪 Use Synthetic Context", value=True)

    # Manual strengths/weaknesses (shown if not synthetic)
    strengths_input = ""
    weaknesses_input = ""
    if not use_synthetic:
        st.sidebar.divider()
        st.sidebar.subheader("Topic Knowledge")
        strengths_input = st.sidebar.text_area(
            "Strengths (comma-separated)", placeholder="variables, loops, functions"
        )
        weaknesses_input = st.sidebar.text_area(
            "Weaknesses (comma-separated)", placeholder="recursion, regex"
        )

    # Sidebar metrics
    st.sidebar.divider()
    st.sidebar.metric("📚 Total Indexed Chunks", reader.chunk_count)
    st.sidebar.metric("📖 Available Courses", len(courses))

    # Settings
    st.sidebar.divider()
    st.sidebar.subheader("⚙️ Session Settings")
    min_tok = st.sidebar.number_input("Min Tokens/Session", value=3000, step=500)
    max_tok = st.sidebar.number_input("Max Tokens/Session", value=5000, step=500)

    # ── Main area ────────────────────────────────────────────────

    col1, col2 = st.columns([1, 1])
    with col1:
        generate_btn = st.button("🚀 Generate Pathway", type="primary", use_container_width=True)
    with col2:
        force_regen = st.button("🔄 Force Regenerate", use_container_width=True)

    if generate_btn or force_regen:
        strengths = [s.strip() for s in strengths_input.split(",") if s.strip()] if strengths_input else []
        weaknesses = [w.strip() for w in weaknesses_input.split(",") if w.strip()] if weaknesses_input else []

        context = StudentContext(
            student_id=student_id,
            course_id=selected_course,
            mastery_level=mastery,
            composition_mode=composition,
            language_proficiency=language,
            strengths=strengths,
            weaknesses=weaknesses,
            use_synthetic_context=use_synthetic,
        )

        gen = _init_generator()

        # Override session settings
        gen._grouper = SessionGrouper(min_tokens=min_tok, max_tokens=max_tok)

        with st.spinner("Generating personalised pathway..."):
            start = time.time()
            response = gen.generate(context, force_regenerate=force_regen)
            elapsed = time.time() - start

        plan = response.plan
        cached = response.cached

        # ── Results Header ───────────────────────────────────────
        st.divider()

        status_icon = "💾 Served from cache" if cached else "✨ Freshly generated"
        st.success(f"{status_icon} in {elapsed:.2f}s")

        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sessions", plan.total_sessions)
        m2.metric("Total Chunks", plan.total_chunks)
        m3.metric("Avg Tokens/Session",
                   sum(s.estimated_token_count for s in plan.sessions) // max(plan.total_sessions, 1))
        m4.metric("Context Hash", plan.student_context_hash[:12] + "...")

        # ── Student Profile Card ─────────────────────────────────
        st.divider()
        st.subheader("👤 Active Student Profile")

        # If synthetic was used, reload the actual context from the plan
        profile_cols = st.columns(4)
        profile_cols[0].markdown(f"**Student ID:** `{plan.student_id}`")
        profile_cols[1].markdown(f"**Course:** `{plan.course_id}`")
        profile_cols[2].markdown(f"**Mastery:** {mastery}")
        profile_cols[3].markdown(f"**Generated:** {plan.generated_at[:19]}")

        if use_synthetic:
            st.info("🧪 Synthetic context was used — strengths and weaknesses were auto-generated.")

        # ── Intermediate Pipeline Data ───────────────────────────
        st.divider()
        with st.expander("🔬 Pipeline Internals (Sections & Dependency Graph)", expanded=False):
            chunks = reader.get_all_course_chunks(selected_course)
            builder = SectionBuilder(similarity_threshold=0.85)
            sections = builder.discover_sections(chunks)

            graph = GraphBuilder()
            sorted_sections = graph.build_and_sort(sections, chunks)

            st.markdown(f"**Discovered {len(sections)} sections** from {len(chunks)} chunks "
                        f"({len({c.topic for c in chunks})} raw topics → {len(sections)} canonical)")

            # Section table
            section_data = []
            for i, sec in enumerate(sorted_sections, 1):
                prereqs = ", ".join(sec.prerequisite_sections[:3])
                if len(sec.prerequisite_sections) > 3:
                    prereqs += f" +{len(sec.prerequisite_sections) - 3} more"
                section_data.append({
                    "Order": i,
                    "Section": sec.display_title,
                    "Chunks": len(sec.chunk_ids),
                    "Definitional": "✅" if sec.has_definitional_chunks else "❌",
                    "Difficulty": str(sec.difficulty_distribution),
                    "Prerequisites": prereqs or "—",
                })

            st.dataframe(section_data, use_container_width=True, height=400)

        # ── Session Plan ─────────────────────────────────────────
        st.divider()
        st.subheader("📅 Session Plan")

        # Session overview table
        overview_data = []
        for session in plan.sessions:
            overview_data.append({
                "#": session.session_number,
                "Title": session.session_title[:60],
                "Chunks": len(session.chunks),
                "Tokens": session.estimated_token_count,
                "Topics": ", ".join(session.topics_covered[:3]) + (
                    f" +{len(session.topics_covered) - 3}" if len(session.topics_covered) > 3 else ""
                ),
                "Book": session.book,
                "Pages": f"{session.page_range_start}–{session.page_range_end}",
            })

        st.dataframe(overview_data, use_container_width=True)

        # ── Individual Session Details ───────────────────────────
        st.divider()
        st.subheader("📖 Session Details")

        for session in plan.sessions:
            with st.expander(
                f"Session {session.session_number}: {session.session_title} "
                f"({len(session.chunks)} chunks, {session.estimated_token_count} tok)",
                expanded=False,
            ):
                # Session metadata
                info_cols = st.columns(4)
                info_cols[0].markdown(f"**📄 Book:** {session.book}")
                info_cols[1].markdown(f"**📑 Pages:** {session.page_range_start}–{session.page_range_end}")
                info_cols[2].markdown(f"**🔢 Tokens:** {session.estimated_token_count}")
                info_cols[3].markdown(f"**📌 Chunks:** {len(session.chunks)}")

                st.markdown("**Topics:** " + ", ".join(
                    f"`{t}`" for t in session.topics_covered
                ))

                # Chunk details
                st.markdown("---")
                for j, chunk in enumerate(session.chunks, 1):
                    with st.container():
                        st.markdown(f"**Chunk {j}:** `{chunk.chunk_id}`")
                        # Show first 300 chars of raw text
                        preview = chunk.raw_text[:300]
                        if len(chunk.raw_text) > 300:
                            preview += "..."
                        st.text(preview)

        # ── Raw JSON Export ──────────────────────────────────────
        st.divider()
        with st.expander("📋 Raw JSON Export"):
            st.json(json.loads(plan.model_dump_json()))

    else:
        # Landing state
        st.info(
            "👈 Configure the student profile in the sidebar and click **Generate Pathway** "
            "to create a personalised session plan."
        )

        # Show available courses
        st.subheader("📚 Available Courses")
        for course in courses:
            topics = reader.get_course_topics(course)
            chunks = reader.get_all_course_chunks(course)
            st.markdown(
                f"- **{course}** — {len(chunks)} chunks, {len(topics)} topics"
            )


if __name__ == "__main__":
    main()
