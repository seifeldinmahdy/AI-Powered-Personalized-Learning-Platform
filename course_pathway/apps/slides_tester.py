#!/usr/bin/env python3
"""Streamlit test app — Session Chunks -> Full Slide Deck Generation.

Feeds the course pathway generator's session chunks through the full
slides-generator pipeline (Content Specialist + Visual Classifier +
Code Extractor + Summary Generator + Deck Assembly + Validation)
and displays the generated slides for every session.

Run:
    cd course_pathway/
    source .venv/bin/activate
    PYTHONPATH=src streamlit run apps/slides_tester.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_PATHWAY_SRC = _THIS_DIR.parent / "src"
_PROJECT_ROOT = _THIS_DIR.parent.parent
_SLIDES_SRC = _PROJECT_ROOT / "slides-generator" / "src"

for p in [str(_PATHWAY_SRC), str(_SLIDES_SRC)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st
import structlog
import torch

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from pathway.chromadb_reader import ChromaDBReader
from pathway.config import get_settings
from pathway.generator import PathwayGenerator
from pathway.llm.naming import OllamaClient
from pathway.models.schemas import SessionPlan, StudentContext
from pathway.session.grouper import SessionGrouper
from pathway.storage.plan_store import PlanStore

# Slides-generator pipeline imports
from slide_gen.core.profile_schema import (
    CompositionMode,
    LanguageProficiency,
    MasteryLevel,
    StudentProfile,
)
from slide_gen.core.slide_schema import (
    CodeBlock,
    ContentItem,
    HighlightType,
    Layout,
    SlideInstruction,
    SlideType,
    VisualTemplate,
)
from slide_gen.agents.content_specialist import (
    format_input as _cs_format_input,
    parse_output as _cs_parse_output,
)
from slide_gen.agents.code_extractor import extract_code
from slide_gen.agents.visual_classifier import classify_visual, should_render_visual
from slide_gen.agents.accessibility import generate_alt_text
from slide_gen.agents.visual_param_generator import generate_visual_params
from slide_gen.pipeline.summary_generator import generate_summary_slide
from slide_gen.pipeline.validation import validate_deck

logger = structlog.get_logger(__name__)

# ── Resolve model paths ─────────────────────────────────────────
_CONTENT_SPECIALIST_DIR = _PROJECT_ROOT / "slides-generator" / "models" / "content_specialist"
_VISUAL_CLASSIFIER_DIR = _PROJECT_ROOT / "slides-generator" / "models" / "visual_classifier"

# ── Text cleaning (from slides-generator/scripts/clean_dataset.py) ──
LIGATURE_MAP = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    "\u2011": "-", "\u00a0": " ",
    "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
}
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PAGE_TEXT_RE = re.compile(r"(?i)(continues on next page|continued from previous page)")
STANDALONE_PAGE_RE = re.compile(r"^\s*\d+\s*(?:\|?\s*.{0,50})?\s*$", re.MULTILINE)
DOUBLE_COMMA_RE = re.compile(r",{2,}")
DOUBLE_SEMICOLON_RE = re.compile(r";{2,}")
DOUBLE_PERIOD_RE = re.compile(r"(?<!\.)\.\.(?!\.)(?=\s|$)")
ENCODING_ARTIFACTS = ["\ufffd", "\u00e2\u20ac", "\u00c2", "\u00c3"]
MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
LOWER_UPPER_RE = re.compile(r"([a-z])([A-Z][a-z]+)")
PYTHON_IMPORTS_MAP = {
    "importnumpy": "import numpy", "importmatplotlib": "import matplotlib",
    "importpandas": "import pandas", "fromnumpy": "from numpy",
    "asnp": "as np", "aspd": "as pd",
}
PYTHON_IMPORTS_RE = re.compile(
    r"\b(importnumpy|importmatplotlib|importpandas|fromnumpy|asnp|aspd)\b"
)


def _clean_broken_words_outside_code(text: str) -> str:
    parts = text.split("`")
    cleaned = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            part = LOWER_UPPER_RE.sub(r"\1 \2", part)
        cleaned.append(part)
    return "`".join(cleaned)


def clean_text(text: str) -> str:
    """Exact same cleaning as scripts/clean_dataset.py process_text_field."""
    for lig, rep in LIGATURE_MAP.items():
        text = text.replace(lig, rep)
    text = CONTROL_CHAR_RE.sub("", text)
    lines = text.split("\n")
    lines = [
        ln for ln in lines
        if not PAGE_TEXT_RE.search(ln) and not STANDALONE_PAGE_RE.match(ln)
    ]
    text = "\n".join(lines)
    text = PYTHON_IMPORTS_RE.sub(lambda m: PYTHON_IMPORTS_MAP[m.group(1)], text)
    text = _clean_broken_words_outside_code(text)
    text = DOUBLE_COMMA_RE.sub(",", text)
    text = DOUBLE_SEMICOLON_RE.sub(";", text)
    text = DOUBLE_PERIOD_RE.sub(".", text)
    for art in ENCODING_ARTIFACTS:
        text = text.replace(art, "")
    out_lines: list[str] = []
    in_code = False
    for ln in text.split("\n"):
        if ln.startswith("```"):
            in_code = not in_code
            out_lines.append(ln.rstrip())
            continue
        is_indented_code = (ln.startswith(" ") or ln.startswith("\t")) and any(
            kw in ln for kw in ["def ", "class ", "import ", "return ", "if ", "for ", "while "]
        )
        if in_code or is_indented_code:
            out_lines.append(ln.rstrip())
        else:
            out_lines.append(MULTI_SPACE_RE.sub(" ", ln).strip())
    text = "\n".join(out_lines)
    text = MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


# ── T5 output parsing with BINE fix ─────────────────────────────
# The model sometimes generates "BINE" instead of "DEFINE" due to
# beam-search token boundary issues.  Normalise before parsing.

def _fix_tag_typos(text: str) -> str:
    """Fix known T5 tokenisation artifacts in tag names.

    The model sometimes generates truncated tag names like BINE instead
    of DEFINE due to beam-search token boundary issues.
    Uses regex with word boundaries to avoid corrupting valid tags.
    """
    # Order matters: longest fragments first to avoid partial matches
    replacements = [
        (r'\bBINE\s*\[', 'DEFINE ['),
        (r'\bBINE:', 'DEFINE:'),
        (r'\bEFINE\s*\[', 'DEFINE ['),
        (r'\bEFINE:', 'DEFINE:'),
        (r'\bITLE:', 'TITLE:'),
        (r'\bULLET\s*\[', 'BULLET ['),
        (r'\bULLET:', 'BULLET:'),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    return text


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
        settings=settings, reader=reader, store=store, llm_client=llm_client,
    )


@st.cache_resource
def _load_t5_model():
    """Load the fine-tuned Flan-T5-Large Content Specialist once."""
    model_path = str(_CONTENT_SPECIALIST_DIR)
    if not _CONTENT_SPECIALIST_DIR.exists():
        raise FileNotFoundError(
            f"Content Specialist model not found at {model_path}."
        )
    tokenizer = AutoTokenizer.from_pretrained(model_path, legacy=False)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
    model.eval()
    return model, tokenizer


# ── Inference helpers ────────────────────────────────────────────

MAX_INPUT_TOKENS = 512


def _truncate_to_token_limit(
    input_text: str,
    tokenizer,
    max_tokens: int = MAX_INPUT_TOKENS,
) -> tuple[str, int]:
    token_ids = tokenizer.encode(input_text, add_special_tokens=True)
    if len(token_ids) <= max_tokens:
        return input_text, 0
    tokens_over = len(token_ids) - max_tokens
    truncated_ids = token_ids[:max_tokens]
    truncated_text = tokenizer.decode(truncated_ids, skip_special_tokens=True)
    last_period = truncated_text.rfind(".")
    last_newline = truncated_text.rfind("\n")
    cut = max(last_period, last_newline)
    if cut > len(truncated_text) * 0.5:
        truncated_text = truncated_text[: cut + 1]
    logger.warning("input_truncated", tokens_trimmed=tokens_over,
                   original_tokens=len(token_ids))
    return truncated_text, tokens_over


_HL_MAP = {
    "key_concept": HighlightType.KEY_CONCEPT,
    "example": HighlightType.EXAMPLE,
    "attention": HighlightType.ATTENTION,
    "code": HighlightType.CODE,
    "definition": HighlightType.DEFINITION,
    "none": HighlightType.NONE,
}


def _process_chunk_full_pipeline(
    raw_text: str,
    profile: StudentProfile,
    model,
    tokenizer,
    classifier_path: str,
    ollama_host: str | None = None,
    ollama_model: str | None = None,
    ollama_api_key: str | None = None,
) -> tuple[SlideInstruction, str, str, int]:
    """Run a single chunk through the full 5-agent pipeline.

    Returns (slide, formatted_input, raw_t5_output, tokens_trimmed).
    """
    # Clean
    cleaned = clean_text(raw_text)

    # Format input
    profile_dict = profile.to_prompt_dict()
    formatted = _cs_format_input(cleaned, profile_dict)

    # Truncate
    truncated, trimmed = _truncate_to_token_limit(formatted, tokenizer)

    # Agent 1: Content Specialist (T5)
    inputs = tokenizer(
        truncated, return_tensors="pt", max_length=MAX_INPUT_TOKENS, truncation=True,
    )
    with torch.no_grad():
        outputs = model.generate(
            **inputs, max_length=150, num_beams=4,
            early_stopping=True, no_repeat_ngram_size=3,
        )
    raw_output = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # Fix known tag typos before parsing
    fixed_output = _fix_tag_typos(raw_output)
    parsed = _cs_parse_output(fixed_output)
    title = parsed["title"]
    items = parsed["items"]

    # Build ContentItem list
    body_content = []
    for item in items:
        hl = _HL_MAP.get(item.get("highlight_type", "none"), HighlightType.NONE)
        body_content.append(ContentItem(
            text=item["text"], highlight_type=hl, term=item.get("term"),
        ))

    # Agent 2: Visual Classifier
    try:
        classification = classify_visual(cleaned, model_path=classifier_path)
    except Exception:
        classification = {"top_3": [], "category": "none"}

    # Agent 3: Visual Gate
    visual = None
    template_id = None
    visual_params = {}
    for candidate in classification.get("top_3", []):
        candidate_classification = {
            "template_id": candidate["template_id"],
            "confidence": candidate["confidence"],
            "category": classification.get("category", "none"),
        }
        visual_decision = should_render_visual(
            candidate_classification, profile.composition_mode.value,
        )
        if visual_decision is not None:
            attempted_id = visual_decision["template_id"]
            bullet_texts = [item["text"] for item in items]
            attempted_params = generate_visual_params(
                attempted_id, bullet_texts, title,
                ollama_host=ollama_host, ollama_model=ollama_model, api_key=ollama_api_key,
            )
            if attempted_params is not None:
                template_id = attempted_id
                visual_params = attempted_params
                visual = VisualTemplate(template=template_id, params=visual_params)
                break

    # Agent 4: Code Extractor
    code_data = extract_code(cleaned)
    code_block = None
    if code_data:
        code_block = CodeBlock(language=code_data["language"], code=code_data["code"])

    # Agent 5: Accessibility
    alt_text = generate_alt_text(
        template_id=template_id, params=visual_params,
        slide_title=title, screen_reader_active=profile.screen_reader_active,
    )

    # Layout selection
    if code_block:
        layout = Layout.CODE_MAIN
    elif visual:
        layout = Layout.CONTENT_VISUAL
    else:
        layout = Layout.LIST_VIEW

    slide = SlideInstruction(
        slide_type=SlideType.CONTENT, layout=layout, title=title,
        body_content=body_content, visual=visual,
        code_block=code_block, alt_text=alt_text,
    )

    return slide, truncated, raw_output, trimmed


# ── Slide rendering (presentation-style) ─────────────────────────

_HL_STYLE = {
    HighlightType.DEFINITION:  ("font-weight:700; color:#1e40af;", True),
    HighlightType.KEY_CONCEPT: ("font-weight:700; color:#111827;", False),
    HighlightType.EXAMPLE:     ("font-style:italic; color:#374151;", False),
    HighlightType.ATTENTION:   ("font-weight:700; color:#b91c1c;", False),
    HighlightType.CODE:        ("font-family:monospace; background:#f3f4f6; padding:2px 4px; border-radius:3px; color:#111827;", False),
    HighlightType.NONE:        ("color:#374151;", False),
}

SLIDE_WIDTH = 720
SLIDE_HEIGHT = 405   # 16:9


def _render_slide_html(slide: SlideInstruction, slide_num: int, total: int) -> str:
    """Render one slide as a fixed-size white card that looks like a real slide."""

    # Determine background based on slide type
    if slide.slide_type == SlideType.TITLE:
        bg = "background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%);"
        title_style = "color:#ffffff; font-size:28px; font-weight:700; text-align:center; margin-top:80px;"
        subtitle_html = ""
        if slide.body_content:
            subtitle_html = f'<p style="color:#94a3b8; font-size:14px; text-align:center;">{slide.body_content[0].text}</p>'
        return (
            f'<div style="width:{SLIDE_WIDTH}px; height:{SLIDE_HEIGHT}px; {bg} '
            f'border-radius:8px; padding:40px; box-sizing:border-box; position:relative; '
            f'border:1px solid #e5e7eb; overflow:hidden;">'
            f'<p style="{title_style}">{slide.title}</p>'
            f'{subtitle_html}'
            f'<p style="position:absolute; bottom:12px; right:16px; color:#64748b; font-size:11px;">'
            f'{slide_num}/{total}</p></div>'
        )

    if slide.slide_type == SlideType.SECTION_OPENER:
        bg = "background: linear-gradient(135deg, #312e81 0%, #1e1b4b 100%);"
        return (
            f'<div style="width:{SLIDE_WIDTH}px; height:{SLIDE_HEIGHT}px; {bg} '
            f'border-radius:8px; padding:40px; box-sizing:border-box; position:relative; '
            f'border:1px solid #e5e7eb; overflow:hidden; display:flex; flex-direction:column; '
            f'justify-content:center; align-items:center;">'
            f'<p style="color:#c7d2fe; font-size:13px; text-transform:uppercase; letter-spacing:2px; margin-bottom:8px;">'
            f'{slide.body_content[0].text if slide.body_content else ""}</p>'
            f'<p style="color:#ffffff; font-size:26px; font-weight:700; text-align:center;">{slide.title}</p>'
            f'<p style="position:absolute; bottom:12px; right:16px; color:#818cf8; font-size:11px;">'
            f'{slide_num}/{total}</p></div>'
        )

    # Content / Agenda / Summary slides — white background
    bg = "background:#ffffff;"
    title_color = "#111827"
    if slide.slide_type == SlideType.SUMMARY:
        title_color = "#1e40af"
    elif slide.slide_type == SlideType.AGENDA:
        title_color = "#374151"

    # Title bar
    html = (
        f'<div style="width:{SLIDE_WIDTH}px; height:{SLIDE_HEIGHT}px; {bg} '
        f'border-radius:8px; padding:28px 32px 16px 32px; box-sizing:border-box; '
        f'position:relative; border:1px solid #d1d5db; overflow-y:auto;">'
        f'<p style="color:{title_color}; font-size:20px; font-weight:700; '
        f'margin:0 0 12px 0; padding-bottom:8px; border-bottom:2px solid #e5e7eb;">'
        f'{slide.title}</p>'
    )

    # Body content
    html += '<div style="margin:0; padding:0;">'
    for item in slide.body_content:
        style_str, is_def = _HL_STYLE.get(item.highlight_type, ("color:#374151;", False))
        if item.term and item.highlight_type == HighlightType.DEFINITION:
            # Definition: bold term header + description
            html += (
                f'<div style="margin:8px 0 4px 0;">'
                f'<span style="font-weight:700; color:#1e40af; font-size:14px;">{item.term}</span>'
                f'</div>'
                f'<p style="margin:0 0 8px 16px; font-size:13px; {style_str}">{item.text}</p>'
            )
        else:
            # Bullet point
            html += (
                f'<p style="margin:4px 0 4px 16px; font-size:13px; {style_str}">'
                f'&bull;&nbsp; {item.text}</p>'
            )
    html += '</div>'

    # Code block
    if slide.code_block:
        html += (
            f'<div style="background:#1e293b; border-radius:6px; padding:12px; margin-top:8px;">'
            f'<pre style="color:#e2e8f0; font-family:monospace; font-size:11px; '
            f'margin:0; white-space:pre-wrap; overflow-x:auto;">{slide.code_block.code}</pre></div>'
        )

    # Visual badge
    if slide.visual:
        html += (
            f'<div style="position:absolute; top:8px; right:12px; background:#e0e7ff; '
            f'color:#3730a3; font-size:10px; padding:2px 8px; border-radius:10px;">'
            f'Visual: {slide.visual.template}</div>'
        )

    # Slide number
    html += (
        f'<p style="position:absolute; bottom:8px; right:12px; color:#9ca3af; font-size:11px; margin:0;">'
        f'{slide_num}/{total}</p>'
    )

    html += '</div>'
    return html


# ── Main UI ──────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Slides Tester",
        page_icon="Slides",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("Slides Tester — Session to Slide Deck")
    st.caption("Generate full slide decks from the course pathway's session chunks")

    # ── Sidebar ──────────────────────────────────────────────────
    st.sidebar.header("Student Profile")

    reader = _init_reader()
    courses = reader.get_available_courses()

    student_id = st.sidebar.text_input("Student ID", value="test_student_001")
    selected_course = st.sidebar.selectbox(
        "Course", courses,
        index=courses.index("pythonlearn") if "pythonlearn" in courses else 0,
    )

    mastery = st.sidebar.select_slider(
        "Mastery Level", options=["Novice", "Intermediate", "Expert"], value="Intermediate",
    )

    composition_map = {"Balanced": "balanced", "Visual Heavy": "visual_heavy", "Text Heavy": "text_heavy"}
    composition_label = st.sidebar.selectbox("Composition Mode", list(composition_map.keys()))
    composition_raw = composition_map[composition_label]

    language = st.sidebar.selectbox(
        "Language Proficiency", ["Elementary", "Intermediate", "Advanced", "Native"], index=1,
    )

    use_synthetic = st.sidebar.checkbox("Use Synthetic Context", value=True)

    strengths_input = ""
    weaknesses_input = ""
    if not use_synthetic:
        st.sidebar.divider()
        st.sidebar.subheader("Topic Knowledge")
        strengths_input = st.sidebar.text_area(
            "Strengths (comma-separated)", placeholder="variables, loops, functions",
        )
        weaknesses_input = st.sidebar.text_area(
            "Weaknesses (comma-separated)", placeholder="recursion, regex",
        )

    st.sidebar.divider()
    st.sidebar.markdown(f"**Indexed chunks:** {reader.chunk_count}")
    st.sidebar.markdown(f"**Available courses:** {len(courses)}")

    st.sidebar.divider()
    st.sidebar.subheader("Session Settings")
    min_tok = st.sidebar.number_input("Min Tokens/Session", value=3000, step=500)
    max_tok = st.sidebar.number_input("Max Tokens/Session", value=5000, step=500)

    # ── Generate pathway ─────────────────────────────────────────
    col1, col2 = st.columns([1, 1])
    with col1:
        gen_btn = st.button("Generate Pathway", type="primary", use_container_width=True)
    with col2:
        force_btn = st.button("Force Regenerate", use_container_width=True)

    if gen_btn or force_btn:
        strengths = [s.strip() for s in strengths_input.split(",") if s.strip()] if strengths_input else []
        weaknesses = [w.strip() for w in weaknesses_input.split(",") if w.strip()] if weaknesses_input else []

        context = StudentContext(
            student_id=student_id, course_id=selected_course,
            mastery_level=mastery, composition_mode=composition_raw,
            language_proficiency=language,
            strengths=strengths, weaknesses=weaknesses,
            use_synthetic_context=use_synthetic,
        )

        gen = _init_generator()
        gen._grouper = SessionGrouper(min_tokens=min_tok, max_tokens=max_tok)

        with st.spinner("Generating personalised pathway..."):
            start = time.time()
            response = gen.generate(context, force_regenerate=force_btn)
            elapsed = time.time() - start

        st.session_state["plan"] = response.plan
        st.session_state["cached"] = response.cached
        st.session_state["elapsed"] = elapsed
        st.session_state["mastery"] = mastery
        st.session_state["mode"] = composition_label
        st.session_state["mode_raw"] = composition_raw
        st.session_state["lang"] = language
        st.session_state["use_synthetic"] = use_synthetic
        st.session_state["strengths"] = strengths
        st.session_state["weaknesses"] = weaknesses

    # ── Show plan ────────────────────────────────────────────────
    plan: SessionPlan | None = st.session_state.get("plan")
    if plan is None:
        st.info("Configure the student profile and click Generate Pathway to start.")
        return

    cached = st.session_state.get("cached", False)
    elapsed = st.session_state.get("elapsed", 0)
    status = "Served from cache" if cached else "Freshly generated"
    st.success(f"{status} in {elapsed:.2f}s")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sessions", plan.total_sessions)
    m2.metric("Total Chunks", plan.total_chunks)
    m3.metric("Avg Tokens/Session",
              sum(s.estimated_token_count for s in plan.sessions) // max(plan.total_sessions, 1))
    m4.metric("Context Hash", plan.student_context_hash[:12] + "...")

    st.divider()

    # Session selector
    session_options = [
        f"Session {s.session_number}: {s.session_title}" for s in plan.sessions
    ]
    selected_idx = st.selectbox("Select Session", range(len(session_options)),
                                format_func=lambda i: session_options[i])
    session = plan.sessions[selected_idx]

    # Session metadata
    st.subheader(session.session_title)
    info_cols = st.columns(5)
    info_cols[0].markdown(f"**Book:** {session.book}")
    info_cols[1].markdown(f"**Pages:** {session.page_range_start} - {session.page_range_end}")
    info_cols[2].markdown(f"**Chunks:** {len(session.chunks)}")
    info_cols[3].markdown(f"**Tokens:** {session.estimated_token_count}")
    info_cols[4].markdown(f"**Topics:** {len(session.topics_covered)}")
    st.markdown("**Topics:** " + ", ".join(f"`{t}`" for t in session.topics_covered))
    st.divider()

    # ── Generate Slides ──────────────────────────────────────────
    generate_slides_btn = st.button(
        f"Generate Slides for Session {session.session_number} ({len(session.chunks)} chunks)",
        type="primary", use_container_width=True,
    )

    if generate_slides_btn:
        t5_model, t5_tokenizer = _load_t5_model()

        eff_mastery = st.session_state.get("mastery", "Intermediate")
        eff_mode = st.session_state.get("mode_raw", "balanced")
        eff_lang = st.session_state.get("lang", "Intermediate")

        # Build slides-generator StudentProfile
        mastery_enum = MasteryLevel(eff_mastery)
        mode_enum = {"balanced": CompositionMode.BALANCED,
                     "visual_heavy": CompositionMode.VISUAL_HEAVY,
                     "text_heavy": CompositionMode.TEXT_HEAVY}[eff_mode]
        lang_enum = LanguageProficiency(eff_lang)
        sg_profile = StudentProfile(
            mastery_level=mastery_enum,
            composition_mode=mode_enum,
            language_proficiency=lang_enum,
        )

        classifier_path = str(_VISUAL_CLASSIFIER_DIR)
        settings = get_settings()

        content_slides: list[SlideInstruction] = []
        raw_outputs: list[str] = []
        inputs_used: list[str] = []
        trims: list[int] = []

        progress_bar = st.progress(0, text="Generating slides...")
        for i, chunk in enumerate(session.chunks):
            progress_bar.progress(
                (i + 1) / len(session.chunks),
                text=f"Processing chunk {i + 1}/{len(session.chunks)}...",
            )
            slide, inp_used, raw_out, trimmed = _process_chunk_full_pipeline(
                chunk.raw_text, sg_profile, t5_model, t5_tokenizer, classifier_path,
                ollama_host=settings.ollama_host,
                ollama_model=settings.ollama_model,
                ollama_api_key=settings.ollama_api_key,
            )
            content_slides.append(slide)
            raw_outputs.append(raw_out)
            inputs_used.append(inp_used)
            trims.append(trimmed)
        progress_bar.empty()

        # Summary slide
        with st.spinner("Generating summary slide..."):
            summary_slide = generate_summary_slide(content_slides, session.session_title, sg_profile)

        # Build structural slides
        title_slide = SlideInstruction(
            slide_type=SlideType.TITLE, layout=Layout.CONTENT_VISUAL,
            title=session.session_title, body_content=[
                ContentItem(text=f"Session {session.session_number}", highlight_type=HighlightType.NONE)
            ],
        )
        agenda_items = [
            ContentItem(text=t, highlight_type=HighlightType.NONE)
            for t in session.topics_covered[:10]
        ]
        agenda_slide = SlideInstruction(
            slide_type=SlideType.AGENDA, layout=Layout.LIST_VIEW,
            title="What We'll Cover", body_content=agenda_items,
        )

        # Assemble deck: Title -> Agenda -> Content... -> Summary
        deck: list[SlideInstruction] = [title_slide, agenda_slide]
        deck.extend(content_slides)
        deck.append(summary_slide)

        # Validate
        deck = validate_deck(deck, sg_profile)

        # Number slides
        for i, slide in enumerate(deck):
            slide.slide_number = i + 1

        st.session_state[f"deck_{selected_idx}"] = deck
        st.session_state[f"content_slides_{selected_idx}"] = content_slides
        st.session_state[f"raw_{selected_idx}"] = raw_outputs
        st.session_state[f"inputs_{selected_idx}"] = inputs_used
        st.session_state[f"trims_{selected_idx}"] = trims

    # ── Display per-chunk details ────────────────────────────────
    content_slides = st.session_state.get(f"content_slides_{selected_idx}")
    raw_outputs = st.session_state.get(f"raw_{selected_idx}")
    inputs_used = st.session_state.get(f"inputs_{selected_idx}")
    trims = st.session_state.get(f"trims_{selected_idx}")
    deck = st.session_state.get(f"deck_{selected_idx}")

    if content_slides:
        st.subheader(f"Per-Chunk Details ({len(content_slides)} content slides)")

        for i, (slide, src_chunk, raw_out, inp_used, trimmed) in enumerate(
            zip(content_slides, session.chunks, raw_outputs, inputs_used, trims)
        ):
            title = slide.title
            short_title = title[:60] + "..." if len(title) > 60 else title
            label = f"Slide {i + 1} - {short_title}"
            if trimmed > 0:
                label += f" [{trimmed} tokens trimmed]"

            with st.expander(label, expanded=(i == 0)):
                # Render the slide as a card
                slide_html = _render_slide_html(slide, i + 3, len(content_slides) + 3)
                st.markdown(slide_html, unsafe_allow_html=True)
                st.write("")

                # Raw model output
                with st.expander("Raw model output"):
                    st.code(raw_out, language="text")

                # Source chunk
                with st.expander(f"Source chunk - {src_chunk.chunk_id}"):
                    st.text(src_chunk.raw_text[:800] + ("..." if len(src_chunk.raw_text) > 800 else ""))

                # Formatted model input
                with st.expander("Formatted model input"):
                    st.code(inp_used[:800], language="text")

        # ── Summary panel ────────────────────────────────────────
        st.divider()
        st.subheader("Session Summary")

        n_title = sum(1 for s in content_slides if s.title != "Untitled")
        n_define = sum(
            1 for s in content_slides
            if any(it.highlight_type == HighlightType.DEFINITION for it in s.body_content)
        )
        n_bullet = sum(
            1 for s in content_slides
            if any(it.highlight_type != HighlightType.DEFINITION for it in s.body_content)
        )
        n_code = sum(1 for s in content_slides if s.code_block is not None)
        n_visual = sum(1 for s in content_slides if s.visual is not None)
        n_trimmed = sum(1 for t in trims if t > 0)

        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Total content slides", len(content_slides))
        sc1.metric("With TITLE tags", n_title)
        sc2.metric("With DEFINE tags", n_define)
        sc2.metric("With BULLET tags", n_bullet)
        sc3.metric("With code blocks", n_code)
        sc3.metric("With visuals", n_visual)
        st.metric("Inputs truncated", f"{n_trimmed}" if n_trimmed > 0 else "0 (none)")

    # ── Full slide deck viewer ───────────────────────────────────
    if deck:
        st.divider()
        st.subheader(f"Full Slide Deck ({len(deck)} slides)")

        if "deck_index" not in st.session_state:
            st.session_state["deck_index"] = 0

        idx = st.session_state["deck_index"]
        idx = max(0, min(idx, len(deck) - 1))

        # Navigation
        nav_prev, nav_label, nav_next = st.columns([1, 3, 1])
        with nav_prev:
            if st.button("Previous", use_container_width=True, disabled=(idx == 0)):
                st.session_state["deck_index"] = idx - 1
                st.rerun()
        with nav_label:
            current_slide = deck[idx]
            st.markdown(
                f'<p style="text-align:center; font-size:14px; color:#6b7280; margin-top:8px;">'
                f'Slide {idx + 1} of {len(deck)} &mdash; '
                f'{current_slide.slide_type.value}: {current_slide.title[:50]}</p>',
                unsafe_allow_html=True,
            )
        with nav_next:
            if st.button("Next", use_container_width=True, disabled=(idx >= len(deck) - 1)):
                st.session_state["deck_index"] = idx + 1
                st.rerun()

        # Render current slide
        slide_html = _render_slide_html(deck[idx], idx + 1, len(deck))
        st.markdown(
            f'<div style="display:flex; justify-content:center; margin:16px 0;">{slide_html}</div>',
            unsafe_allow_html=True,
        )

        # Slide jump
        jump = st.slider("Jump to slide", 1, len(deck), idx + 1)
        if jump - 1 != idx:
            st.session_state["deck_index"] = jump - 1
            st.rerun()

    elif not generate_slides_btn:
        st.info("Press Generate Slides to run the full pipeline on this session's chunks.")


if __name__ == "__main__":
    main()
