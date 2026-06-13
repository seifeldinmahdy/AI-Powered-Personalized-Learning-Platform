# PersonifAI — MCQ Generation Tester
# A developer tool for testing personalized MCQ generation across signal combinations.
#
# Run from the project root:
#   uv run streamlit run mcq_service/streamlit_tester.py
#
# Requires:
#   - mcq_service installed as editable package (uv pip install -e mcq_service/)
#   - course_pathway installed as editable package (uv pip install -e course_pathway/)
#   - ChromaDB data at rag_pipeline/data/chroma (run RAG indexing first)

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

# ── Ensure project packages are importable regardless of CWD ─────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _pkg in ["mcq_service/src", "mcq_service/config", "course_pathway/src", "ai_service"]:
    _p = str(_PROJECT_ROOT / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PersonifAI — MCQ Tester",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT GUARDS — catch missing packages early with clear error messages
# ─────────────────────────────────────────────────────────────────────────────
_import_errors: list[str] = []

try:
    from settings import get_settings as _get_mcq_settings  # type: ignore
    MCQ_SETTINGS_OK = True
except ImportError as e:
    MCQ_SETTINGS_OK = False
    _import_errors.append(f"mcq_service not importable: {e}")

try:
    from mcq.selector import select_question_type  # type: ignore
    from mcq.qg import generate_question  # type: ignore
    from mcq.dg import generate_mcq  # type: ignore
    from mcq.models import GeneratedQuestion, MCQQuestion, MCQOption  # type: ignore
    from mcq.question_types import (  # type: ignore
        MASTERY_TYPE_ELIGIBILITY,
        TYPE_COGNITIVE_LEVEL,
        ALL_QUESTION_TYPES,
    )
    from mcq.scoring_categories import get_score_category  # type: ignore
    MCQ_PIPELINE_OK = True
except ImportError as e:
    MCQ_PIPELINE_OK = False
    _import_errors.append(f"mcq pipeline modules: {e}")

try:
    import chromadb  # type: ignore
    CHROMA_OK = True
except ImportError as e:
    CHROMA_OK = False
    _import_errors.append(f"chromadb: {e}")

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    ST_OK = True
except ImportError as e:
    ST_OK = False
    _import_errors.append(f"sentence_transformers: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
CHROMA_PATH = str(_PROJECT_ROOT / "rag_pipeline" / "data" / "chroma")
COLLECTION_NAME = "course_chunks"

MASTERY_OPTIONS = ["Novice", "Intermediate", "Expert"]
SCORE_CATEGORY_OPTIONS = ["very_weak", "weak", "moderate", "strong"]
TYPE_OPTIONS = ["auto", "1", "2", "3", "4a", "4b", "4c", "4d", "4e"]
MISCONCEPTION_OPTIONS = ["none", "auto-generate", "custom"]

TYPE_LABELS = {
    "1": "Type 1 — Method/API",
    "2": "Type 2 — Code Output",
    "3": "Type 3 — Code Completion",
    "4a": "Type 4a — Definition/Recall",
    "4b": "Type 4b — Distinction",
    "4c": "Type 4c — Application",
    "4d": "Type 4d — Reasoning",
    "4e": "Type 4e — Misconception",
    "auto": "Auto (selector)",
}

MASTERY_COLORS = {
    "Novice": "#3B82F6",
    "Intermediate": "#F59E0B",
    "Expert": "#10B981",
}

CATEGORY_COLORS = {
    "very_weak": "#EF4444",
    "weak": "#F97316",
    "moderate": "#EAB308",
    "strong": "#22C55E",
}

# ─────────────────────────────────────────────────────────────────────────────
# PREDEFINED VARIATION SETS
# ─────────────────────────────────────────────────────────────────────────────
VARIATION_SETS: dict[str, list[dict]] = {
    "A — Mastery Sweep": [
        {"mastery": "Novice",       "score_cat": "moderate", "q_type": "auto", "misconception": "none", "custom_misc": ""},
        {"mastery": "Intermediate", "score_cat": "moderate", "q_type": "auto", "misconception": "none", "custom_misc": ""},
        {"mastery": "Expert",       "score_cat": "moderate", "q_type": "auto", "misconception": "none", "custom_misc": ""},
    ],
    "B — Score Category Sweep": [
        {"mastery": "Intermediate", "score_cat": "very_weak", "q_type": "auto", "misconception": "none", "custom_misc": ""},
        {"mastery": "Intermediate", "score_cat": "weak",      "q_type": "auto", "misconception": "none", "custom_misc": ""},
        {"mastery": "Intermediate", "score_cat": "moderate",  "q_type": "auto", "misconception": "none", "custom_misc": ""},
        {"mastery": "Intermediate", "score_cat": "strong",    "q_type": "auto", "misconception": "none", "custom_misc": ""},
    ],
    "C — Type Sweep": [
        {"mastery": "Expert", "score_cat": "strong", "q_type": "4b", "misconception": "none", "custom_misc": ""},
        {"mastery": "Expert", "score_cat": "strong", "q_type": "4c", "misconception": "none", "custom_misc": ""},
        {"mastery": "Expert", "score_cat": "strong", "q_type": "4d", "misconception": "none", "custom_misc": ""},
        {"mastery": "Expert", "score_cat": "strong", "q_type": "4e", "misconception": "none", "custom_misc": ""},
    ],
    "D — Misconception Effect": [
        {"mastery": "Expert", "score_cat": "moderate", "q_type": "4c", "misconception": "none",          "custom_misc": ""},
        {"mastery": "Expert", "score_cat": "moderate", "q_type": "4c", "misconception": "auto-generate", "custom_misc": ""},
        {"mastery": "Expert", "score_cat": "moderate", "q_type": "4c", "misconception": "custom",        "custom_misc": "Student confuses time complexity with space complexity, believing O(n²) time automatically means O(n²) space."},
    ],
    "E — Full Personalization Showcase": [
        {"mastery": "Novice",       "score_cat": "very_weak", "q_type": "4a", "misconception": "none",          "custom_misc": ""},
        {"mastery": "Novice",       "score_cat": "strong",    "q_type": "1",  "misconception": "none",          "custom_misc": ""},
        {"mastery": "Intermediate", "score_cat": "moderate",  "q_type": "4b", "misconception": "none",          "custom_misc": ""},
        {"mastery": "Intermediate", "score_cat": "strong",    "q_type": "4c", "misconception": "none",          "custom_misc": ""},
        {"mastery": "Expert",       "score_cat": "moderate",  "q_type": "4d", "misconception": "none",          "custom_misc": ""},
        {"mastery": "Expert",       "score_cat": "strong",    "q_type": "4e", "misconception": "auto-generate", "custom_misc": ""},
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# CACHED RESOURCES
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Loading sentence embedder…")
def _load_embedder():
    return SentenceTransformer("all-MiniLM-L6-v2")


@st.cache_resource(show_spinner="Loading QG LoRA model…")
def _load_qg_model(lora_path: str):
    """Load QG model. Returns (model, tokenizer) or None on failure."""
    if not lora_path:
        return None
    try:
        from unsloth import FastLanguageModel  # type: ignore
        settings = _get_mcq_settings()
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=lora_path,
            max_seq_length=settings.MAX_SEQ_LENGTH,
            load_in_4bit=settings.LOAD_IN_4BIT,
        )
        FastLanguageModel.for_inference(model)
        return model, tokenizer
    except Exception:
        return None


@st.cache_resource(show_spinner="Loading DG LoRA model…")
def _load_dg_model(lora_path: str):
    """Load DG model. Returns (model, tokenizer) or None on failure."""
    if not lora_path:
        return None
    try:
        from unsloth import FastLanguageModel  # type: ignore
        settings = _get_mcq_settings()
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=lora_path,
            max_seq_length=settings.MAX_SEQ_LENGTH,
            load_in_4bit=settings.LOAD_IN_4BIT,
        )
        FastLanguageModel.for_inference(model)
        return model, tokenizer
    except Exception:
        return None


@st.cache_resource(show_spinner="Connecting to ChromaDB…")
def _load_chroma_collection():
    """Connect to the shared ChromaDB collection. Returns collection or None."""
    if not Path(CHROMA_PATH).exists():
        return None
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        return collection
    except Exception:
        return None


@st.cache_data(show_spinner="Loading chunks from ChromaDB…", ttl=300)
def _load_all_chunks() -> list[dict]:
    """Load every chunk from ChromaDB into a flat list of dicts."""
    collection = _load_chroma_collection()
    if collection is None:
        return []
    try:
        results = collection.get(include=["documents", "metadatas"])
        chunks = []
        for chunk_id, doc, meta in zip(
            results["ids"], results["documents"], results["metadatas"]
        ):
            chunks.append({
                "chunk_id": chunk_id,
                "text": doc,
                "topic": meta.get("topic", ""),
                "book": meta.get("book", ""),
                "course": meta.get("course", ""),
                "difficulty": meta.get("difficulty", ""),
                "page_start": meta.get("page_start", 0),
                "page_end": meta.get("page_end", 0),
                "chunk_index": meta.get("chunk_index", 0),
            })
        chunks.sort(key=lambda c: (c["course"], c["chunk_index"]))
        return chunks
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE INITIALISATION
# ─────────────────────────────────────────────────────────────────────────────

def _init_session_state():
    defaults = {
        "selected_chunk": None,       # dict with chunk data
        "chunk_source": "ChromaDB",   # "ChromaDB" or "Manual"
        "manual_chunk_text": "",
        "manual_chunk_topic": "",
        "variation_set_name": "A — Mastery Sweep",
        "variation_matrix": [r.copy() for r in VARIATION_SETS["A — Mastery Sweep"]],
        "generated_results": [],      # list of result dicts
        "chunk_search": "",
        "filter_book": "All",
        "filter_topic": "All",
        "filter_min_len": 50,
        "show_debug": False,
        "qg_temperature": 0.7,
        "dg_temperature": 0.8,
        "qg_max_tokens": 150,
        "dg_max_tokens": 80,
        "parallel": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# HELPER UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _cosine_similarity(a, b) -> float:
    """Compute cosine similarity between two embedding vectors."""
    import numpy as np
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _distractor_similarity(correct: str, distractors: list[str], embedder) -> list[float]:
    """Return cosine similarity of each distractor vs the correct answer."""
    if not distractors or embedder is None:
        return [0.0] * len(distractors)
    try:
        texts = [correct] + distractors
        embs = embedder.encode(texts, show_progress_bar=False)
        correct_emb = embs[0]
        return [_cosine_similarity(correct_emb, embs[i + 1]) for i in range(len(distractors))]
    except Exception:
        return [0.0] * len(distractors)


def _build_misconception_context_auto(chunk_text: str, topic: str, settings) -> str:
    """Auto-generate a plausible misconception context by creating a simple 4a
    question, then fabricating a plausible wrong answer as the previous failure."""
    try:
        gen_q = generate_question(
            chunk_text=chunk_text[:600],
            topic=topic or "General",
            question_type="4a",
            mastery_level="Novice",
            score_category="moderate",
            settings=settings,
        )
        if gen_q is None:
            return f"Student struggled with core concepts in {topic or 'this topic'}."
        # Fabricate a plausible wrong answer by inverting or simplifying
        wrong = f"incorrectly believing that '{gen_q.correct_answer[:60]}' is always the case without conditions"
        return (
            f"The student previously failed this question: '{gen_q.question[:120]}'. "
            f"They chose an answer suggesting they were {wrong}."
        )
    except Exception:
        return f"Student demonstrated confusion about foundational concepts in {topic or 'this topic'}."


def _generate_single_variation(
    chunk_text: str,
    topic: str,
    row: dict,
    settings,
    embedder,
    topic_performance: dict,
    incorrectly_answered: list,
    qg_max_tokens: int,
    dg_max_tokens: int,
) -> dict:
    """Run the full QG → DG pipeline for one variation row. Returns result dict."""
    start = time.perf_counter()
    result = {
        "row": row,
        "resolved_type": None,
        "selector_reason": None,
        "misconception_ctx": None,
        "raw_qg_output": None,
        "raw_dg_outputs": [],
        "mcq": None,
        "distractor_scores": [],
        "error": None,
        "elapsed_ms": 0,
    }

    try:
        mastery = row["mastery"]
        score_cat = row["score_cat"]
        q_type = row["q_type"]
        misc_mode = row["misconception"]
        custom_misc = row.get("custom_misc", "")

        # ── 1. Resolve question type ─────────────────────────────────
        if q_type == "auto":
            resolved_type, resolved_cat, topic_score = select_question_type(
                chunk_text=chunk_text,
                chunk_topic=topic,
                mastery_level=mastery,
                topic_performance=topic_performance,
                incorrectly_answered=incorrectly_answered,
                embedder=embedder,
                settings=settings,
            )
            result["selector_reason"] = f"Auto: score={topic_score:.2f} → {resolved_cat} → type {resolved_type}"
            # Override with the forced score_cat from the row (tester controls it)
            resolved_type = resolved_type
            score_cat_used = score_cat  # tester's score_cat wins for conditioning
        else:
            resolved_type = q_type
            score_cat_used = score_cat

        result["resolved_type"] = resolved_type

        # ── 2. Build misconception context ───────────────────────────
        if misc_mode == "none":
            misconception_ctx = None
        elif misc_mode == "auto-generate":
            misconception_ctx = _build_misconception_context_auto(chunk_text, topic, settings)
        else:  # custom
            misconception_ctx = custom_misc.strip() or None
        result["misconception_ctx"] = misconception_ctx

        # ── 3. Monkey-patch temperature/tokens into generation call ──
        # We call the public API functions directly; they read settings.
        # For temperature/token control we patch generate_question locally.
        gen_q = _call_qg(
            chunk_text=chunk_text,
            topic=topic,
            question_type=resolved_type,
            mastery_level=mastery,
            score_category=score_cat_used,
            misconception_context=misconception_ctx,
            settings=settings,
            max_new_tokens=qg_max_tokens,
        )
        result["raw_qg_output"] = gen_q["_raw"] if gen_q and "_raw" in gen_q else None

        if gen_q is None:
            result["error"] = "QG failed — no output after all retry attempts."
            result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
            return result

        generated_q = GeneratedQuestion(
            question=gen_q["question"],
            correct_answer=gen_q["correct_answer"],
            question_type=resolved_type,
            topic=topic,
            explanation=gen_q.get("explanation", ""),
            mastery_used=mastery,
            score_category_used=score_cat_used,
            generation_mode="llama_lora" if settings.QG_LORA_PATH else "ollama",
        )

        # ── 4. Generate distractors ──────────────────────────────────
        mcq, raw_dg_outputs = _call_dg(
            generated_q=generated_q,
            chunk_text=chunk_text,
            settings=settings,
            max_new_tokens=dg_max_tokens,
        )
        result["raw_dg_outputs"] = raw_dg_outputs

        if mcq is None:
            result["error"] = "DG failed — could not generate enough distractors."
            result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
            return result

        # ── 5. Distractor similarity scores ─────────────────────────
        distractors = [o.text for o in mcq.options if not o.is_correct]
        scores = _distractor_similarity(mcq.correct_answer, distractors, embedder)
        result["distractor_scores"] = scores
        result["mcq"] = mcq

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
    return result


def _call_qg(
    chunk_text, topic, question_type, mastery_level, score_category,
    misconception_context, settings, max_new_tokens
) -> dict | None:
    """Call QG with optional misconception context. Returns dict or None."""
    use_llama = bool(settings.QG_LORA_PATH)

    if use_llama:
        from mcq.prompts.mcq_prompts import build_qg_chat_prompt, format_chat_for_training, extract_qg_output  # type: ignore
        import torch  # type: ignore

        qg_pair = _load_qg_model(settings.QG_LORA_PATH)
        if qg_pair is None:
            # fallback to Ollama
            return _call_qg_ollama(chunk_text, topic, question_type, mastery_level, score_category, misconception_context, settings)

        model, tokenizer = qg_pair
        messages = build_qg_chat_prompt(
            chunk_text, question_type, mastery_level, score_category, misconception_context
        )
        input_text = format_chat_for_training(messages, tokenizer)
        inputs = tokenizer(
            input_text, return_tensors="pt", truncation=True,
            max_length=settings.MAX_SEQ_LENGTH,
        )
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[1]
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.0,
                do_sample=False,
            )
        new_tokens = outputs[0][input_len:]
        raw = tokenizer.decode(new_tokens, skip_special_tokens=True)
        parsed = extract_qg_output(raw)
        if parsed:
            parsed["_raw"] = raw
        return parsed
    else:
        return _call_qg_ollama(chunk_text, topic, question_type, mastery_level, score_category, misconception_context, settings)


def _call_qg_ollama(chunk_text, topic, question_type, mastery_level, score_category, misconception_context, settings) -> dict | None:
    from mcq.prompts.mcq_prompts import build_qg_chat_prompt, extract_qg_output  # type: ignore
    import sys
    from pathlib import Path

    pathway_src = str(Path(__file__).resolve().parent.parent / "course_pathway" / "src")
    if pathway_src not in sys.path:
        sys.path.insert(0, pathway_src)
    from pathway.llm.naming import OllamaClient  # type: ignore

    # Resolve model name: local override → cloud fallback
    model_name = settings.QG_OLLAMA_MODEL or settings.OLLAMA_MODEL
    is_local = bool(settings.QG_OLLAMA_MODEL)
    host = "http://localhost:11434" if is_local else settings.OLLAMA_HOST
    api_key = "" if is_local else settings.OLLAMA_API_KEY

    client = OllamaClient(
        host=host,
        model=model_name,
        api_key=api_key,
        max_retries=2,
        timeout=120,
    )

    # Use the SAME chat-format prompt the model was fine-tuned on.
    # Output is tagged text: QUESTION: / ANSWER: / EXPLANATION:
    messages = build_qg_chat_prompt(
        chunk_text, question_type, mastery_level, score_category, misconception_context
    )
    raw = client.chat(
        messages=messages,
        temperature=0.0,
        json_mode=False,
        timeout_override=120,
        num_predict=256,
    )
    raw_label = f"[{'local:' + model_name if is_local else 'cloud:' + model_name} — {len(messages[0]['content']) + len(messages[1]['content'])} chars]"
    parsed = extract_qg_output(raw)
    if parsed:
        parsed["_raw"] = raw_label
        return parsed
    return None


def _call_dg(generated_q, chunk_text, settings, max_new_tokens) -> tuple[MCQQuestion | None, list[str]]:
    """Call DG. Returns (MCQQuestion | None, list of raw dg outputs)."""
    use_llama = bool(settings.DG_LORA_PATH)
    num_distractors = settings.MCQ_DISTRACTOR_COUNT
    raw_outputs: list[str] = []
    distractors: list[str] = []
    correct_lower = generated_q.correct_answer.strip().lower()

    if use_llama:
        from mcq.prompts.mcq_prompts import build_dg_chat_prompt, format_chat_for_training, extract_dg_output  # type: ignore
        import torch  # type: ignore

        dg_pair = _load_dg_model(settings.DG_LORA_PATH)
        if dg_pair is None:
            return _call_dg_ollama(generated_q, chunk_text, settings, raw_outputs)

        model, tokenizer = dg_pair
        max_attempts = num_distractors + 2

        for _ in range(max_attempts):
            if len(distractors) >= num_distractors:
                break
            messages = build_dg_chat_prompt(
                question=generated_q.question,
                correct_answer=generated_q.correct_answer,
                question_type=generated_q.question_type,
                mastery_level=generated_q.mastery_used,
                score_category=generated_q.score_category_used,
                chunk_text=chunk_text,
            )
            input_text = format_chat_for_training(messages, tokenizer)
            inputs = tokenizer(
                input_text, return_tensors="pt", truncation=True,
                max_length=settings.MAX_SEQ_LENGTH,
            )
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
            input_len = inputs["input_ids"].shape[1]
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=0.0,
                    do_sample=False,
                )
            new_tokens = outputs[0][input_len:]
            raw = tokenizer.decode(new_tokens, skip_special_tokens=True)
            raw_outputs.append(raw)
            parsed = extract_dg_output(raw)
            if parsed and parsed.strip().lower() != correct_lower:
                if not any(parsed.strip().lower() == d.strip().lower() for d in distractors):
                    distractors.append(parsed)
    else:
        return _call_dg_ollama(generated_q, chunk_text, settings, raw_outputs)

    if not distractors:
        return None, raw_outputs

    # Fallback padding
    fallbacks = [f"None of the above", f"All of the above", f"Not defined in this context"]
    for fb in fallbacks:
        if len(distractors) >= num_distractors:
            break
        if fb.strip().lower() != correct_lower and fb not in distractors:
            distractors.append(fb)

    distractors = distractors[:num_distractors]

    import random
    options = [MCQOption(text=generated_q.correct_answer, is_correct=True)]
    for d in distractors:
        options.append(MCQOption(text=d, is_correct=False))
    random.shuffle(options)

    mcq = MCQQuestion(
        question=generated_q.question,
        options=options,
        correct_answer=generated_q.correct_answer,
        explanation=generated_q.explanation,
        question_type=generated_q.question_type,
        topic=generated_q.topic,
        mastery_used=generated_q.mastery_used,
        score_category_used=generated_q.score_category_used,
        distractor_scores=None,
        generation_mode=generated_q.generation_mode,
    )
    return mcq, raw_outputs


def _call_dg_ollama(generated_q, chunk_text, settings, raw_outputs) -> tuple[MCQQuestion | None, list[str]]:
    from mcq.prompts.mcq_prompts import build_dg_chat_prompt, extract_dg_output  # type: ignore
    import sys, random
    from pathlib import Path

    pathway_src = str(Path(__file__).resolve().parent.parent / "course_pathway" / "src")
    if pathway_src not in sys.path:
        sys.path.insert(0, pathway_src)
    from pathway.llm.naming import OllamaClient  # type: ignore

    # Resolve model name: local override → cloud fallback
    model_name = settings.DG_OLLAMA_MODEL or settings.OLLAMA_MODEL
    is_local = bool(settings.DG_OLLAMA_MODEL)
    host = "http://localhost:11434" if is_local else settings.OLLAMA_HOST
    api_key = "" if is_local else settings.OLLAMA_API_KEY

    client = OllamaClient(
        host=host,
        model=model_name,
        api_key=api_key,
        max_retries=2,
        timeout=120,
    )
    num_distractors = settings.MCQ_DISTRACTOR_COUNT
    correct_lower = generated_q.correct_answer.strip().lower()
    distractors: list[str] = []
    label = f"[{'local:' + model_name if is_local else 'cloud:' + model_name}]"

    # Call DG once per distractor — mirrors the LoRA path exactly.
    # build_dg_chat_prompt generates ONE distractor per call.
    max_attempts = num_distractors + 2
    for _ in range(max_attempts):
        if len(distractors) >= num_distractors:
            break
        messages = build_dg_chat_prompt(
            question=generated_q.question,
            correct_answer=generated_q.correct_answer,
            question_type=generated_q.question_type,
            mastery_level=generated_q.mastery_used,
            score_category=generated_q.score_category_used,
            chunk_text=chunk_text,
        )
        raw = client.chat(
            messages=messages,
            temperature=0.8,
            json_mode=False,
            timeout_override=60,
            num_predict=80,
        )
        raw_outputs.append(f"{label} {raw[:120]}")
        parsed = extract_dg_output(raw)
        if parsed and parsed.strip().lower() != correct_lower:
            if not any(parsed.strip().lower() == d.strip().lower() for d in distractors):
                distractors.append(parsed)

    # Fallback padding so we always reach num_distractors
    fallbacks = ["None of the above", "All of the above", "Not defined in this context"]
    for fb in fallbacks:
        if len(distractors) >= num_distractors:
            break
        if fb.strip().lower() != correct_lower and fb not in distractors:
            distractors.append(fb)

    if not distractors:
        return None, raw_outputs

    distractors = distractors[:num_distractors]

    options = [MCQOption(text=generated_q.correct_answer, is_correct=True)]
    for d in distractors:
        options.append(MCQOption(text=d, is_correct=False))
    random.shuffle(options)

    mcq = MCQQuestion(
        question=generated_q.question,
        options=options,
        correct_answer=generated_q.correct_answer,
        explanation=generated_q.explanation,
        question_type=generated_q.question_type,
        topic=generated_q.topic,
        mastery_used=generated_q.mastery_used,
        score_category_used=generated_q.score_category_used,
        distractor_scores=None,
        generation_mode=generated_q.generation_mode,
    )
    return mcq, raw_outputs


# ─────────────────────────────────────────────────────────────────────────────
# COMPONENT: Render a single MCQ result card
# ─────────────────────────────────────────────────────────────────────────────

def _render_result_card(idx: int, result: dict, show_debug: bool):
    row = result["row"]
    mastery = row["mastery"]
    score_cat = row["score_cat"]
    resolved_type = result["resolved_type"] or row["q_type"]
    mcq: MCQQuestion | None = result["mcq"]
    error = result["error"]
    elapsed = result["elapsed_ms"]

    # Badge styles
    mastery_color = MASTERY_COLORS.get(mastery, "#6B7280")
    cat_color = CATEGORY_COLORS.get(score_cat, "#6B7280")
    misc_flag = row["misconception"] != "none"

    # Card header
    col_n, col_m, col_s, col_t, col_e = st.columns([0.5, 1.5, 1.5, 2, 1])
    with col_n:
        st.markdown(f"### #{idx + 1}")
    with col_m:
        st.markdown(
            f'<span style="background:{mastery_color};color:white;padding:3px 10px;'
            f'border-radius:4px;font-size:0.8rem;font-weight:600">{mastery}</span>',
            unsafe_allow_html=True,
        )
    with col_s:
        st.markdown(
            f'<span style="background:{cat_color};color:white;padding:3px 10px;'
            f'border-radius:4px;font-size:0.8rem;font-weight:600">{score_cat}</span>',
            unsafe_allow_html=True,
        )
    with col_t:
        label = TYPE_LABELS.get(resolved_type, resolved_type)
        st.markdown(
            f'<span style="background:#1E293B;color:#94A3B8;padding:3px 10px;'
            f'border-radius:4px;font-size:0.8rem;border:1px solid #334155">{label}</span>',
            unsafe_allow_html=True,
        )
    with col_e:
        misc_badge = (
            '<span style="background:#7C3AED;color:white;padding:3px 8px;'
            'border-radius:4px;font-size:0.75rem">⚡ Misconception</span>'
            if misc_flag else
            '<span style="color:#475569;font-size:0.75rem">No misconception</span>'
        )
        st.markdown(misc_badge, unsafe_allow_html=True)

    st.markdown(f"<span style='color:#64748B;font-size:0.75rem'>⏱ {elapsed} ms</span>", unsafe_allow_html=True)

    if error:
        st.error(f"**Generation failed:** {error[:400]}")
        if show_debug and len(error) > 400:
            with st.expander("Full traceback"):
                st.code(error, language="text")
        return

    if mcq is None:
        st.warning("No question was generated.")
        return

    # Question text
    st.markdown("---")
    question_text = mcq.question
    if any(sig in question_text for sig in ["def ", "print(", ">>>", "```", "    "]):
        st.code(question_text, language="python")
    else:
        st.markdown(f"**{question_text}**")

    # Options
    distractors_in_order: list[str] = []
    scores = result.get("distractor_scores", [])
    score_iter = iter(scores)

    for opt in mcq.options:
        if opt.is_correct:
            st.markdown(
                f'<div style="border-left:4px solid #22C55E;padding:8px 12px;'
                f'margin:4px 0;background:#052e16;border-radius:0 6px 6px 0;">'
                f'✅ <strong>{opt.text}</strong></div>',
                unsafe_allow_html=True,
            )
        else:
            sim = next(score_iter, None)
            sim_badge = (
                f' <span style="color:#94A3B8;font-size:0.7rem">[sim: {sim:.2f}]</span>'
                if sim is not None else ""
            )
            st.markdown(
                f'<div style="border-left:4px solid #334155;padding:8px 12px;'
                f'margin:4px 0;background:#0F172A;border-radius:0 6px 6px 0;">'
                f'⬜ {opt.text}{sim_badge}</div>',
                unsafe_allow_html=True,
            )
            distractors_in_order.append(opt.text)

    # Explanation (collapsible)
    if mcq.explanation:
        with st.expander("📖 Explanation"):
            st.markdown(mcq.explanation)

    # Debug panel (collapsible)
    debug_items = []
    if result.get("selector_reason"):
        debug_items.append(("Selector", result["selector_reason"]))
    if result.get("misconception_ctx"):
        debug_items.append(("Misconception context", result["misconception_ctx"]))
    if result.get("raw_qg_output"):
        debug_items.append(("QG raw output", result["raw_qg_output"]))
    if result.get("raw_dg_outputs"):
        debug_items.append(("DG raw outputs", "\n---\n".join(result["raw_dg_outputs"])))
    debug_items.append(("Generation mode", mcq.generation_mode))

    with st.expander("🔧 Debug", expanded=show_debug):
        for label, content in debug_items:
            st.markdown(f"**{label}:**")
            st.code(content, language="text")


# ─────────────────────────────────────────────────────────────────────────────
# COMPONENT: Variation matrix editor
# ─────────────────────────────────────────────────────────────────────────────

def _render_variation_editor() -> list[dict]:
    """Render the variation matrix editor. Returns the current matrix."""
    matrix = st.session_state.variation_matrix

    st.markdown("#### Variation Matrix")
    st.caption("Each row is one generated question. Configure signals per row.")

    to_delete = None
    for i, row in enumerate(matrix):
        cols = st.columns([1.2, 1.2, 1.2, 1.2, 2.5, 0.4])
        with cols[0]:
            matrix[i]["mastery"] = st.selectbox(
                "Mastery", MASTERY_OPTIONS,
                index=MASTERY_OPTIONS.index(row["mastery"]),
                key=f"mastery_{i}", label_visibility="collapsed",
            )
        with cols[1]:
            matrix[i]["score_cat"] = st.selectbox(
                "Score cat", SCORE_CATEGORY_OPTIONS,
                index=SCORE_CATEGORY_OPTIONS.index(row["score_cat"]),
                key=f"score_cat_{i}", label_visibility="collapsed",
            )
        with cols[2]:
            matrix[i]["q_type"] = st.selectbox(
                "Type", TYPE_OPTIONS,
                index=TYPE_OPTIONS.index(row["q_type"]),
                key=f"q_type_{i}", label_visibility="collapsed",
            )
        with cols[3]:
            matrix[i]["misconception"] = st.selectbox(
                "Misc", MISCONCEPTION_OPTIONS,
                index=MISCONCEPTION_OPTIONS.index(row["misconception"]),
                key=f"misc_{i}", label_visibility="collapsed",
            )
        with cols[4]:
            if row["misconception"] == "custom":
                matrix[i]["custom_misc"] = st.text_input(
                    "Custom misconception", value=row.get("custom_misc", ""),
                    key=f"custom_misc_{i}", label_visibility="collapsed",
                    placeholder="Describe the prior misconception…",
                )
            else:
                matrix[i]["custom_misc"] = row.get("custom_misc", "")
                st.empty()
        with cols[5]:
            if st.button("✕", key=f"del_{i}", help="Remove this row"):
                to_delete = i

    if to_delete is not None:
        matrix.pop(to_delete)
        st.session_state.variation_matrix = matrix
        st.rerun()

    if st.button("➕ Add Row"):
        matrix.append({
            "mastery": "Intermediate", "score_cat": "moderate",
            "q_type": "auto", "misconception": "none", "custom_misc": "",
        })
        st.session_state.variation_matrix = matrix
        st.rerun()

    st.session_state.variation_matrix = matrix
    return matrix


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

def _render_sidebar():
    with st.sidebar:
        st.markdown("## 🧠 MCQ Tester Controls")
        st.divider()

        # ── Model Status ─────────────────────────────────────────────
        st.markdown("### Model Status")
        if not MCQ_PIPELINE_OK:
            st.error("mcq_service not importable.")
        else:
            settings = _get_mcq_settings()
            qg_path = settings.QG_LORA_PATH
            dg_path = settings.DG_LORA_PATH

            local_models = {
                "QG": (qg_path, settings.QG_OLLAMA_MODEL),
                "DG": (dg_path, settings.DG_OLLAMA_MODEL),
            }
            for label, (lora_path, local_model) in local_models.items():
                if lora_path:
                    path_exists = Path(lora_path).exists() or Path(_PROJECT_ROOT / "mcq_service" / lora_path).exists()
                    color = "#22C55E" if path_exists else "#EF4444"
                    mode = "LoRA (Llama)" if path_exists else "LoRA path set but NOT found"
                    icon = "🟢" if path_exists else "🔴"
                    detail = lora_path
                elif local_model:
                    color = "#A855F7"
                    mode = f"Local Ollama · {local_model}"
                    icon = "🟣"
                    detail = "localhost:11434"
                else:
                    color = "#F59E0B"
                    mode = f"Ollama Cloud · {settings.OLLAMA_MODEL}"
                    icon = "🟡"
                    detail = settings.OLLAMA_HOST
                st.markdown(
                    f'{icon} **{label}:** <span style="color:{color}">{mode}</span><br>'
                    f'<span style="font-size:0.7rem;color:#64748B">{detail}</span>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # ── Chunk Source ─────────────────────────────────────────────
        st.markdown("### Chunk Source")
        st.session_state.chunk_source = st.radio(
            "Source", ["ChromaDB", "Manual text"],
            index=0 if st.session_state.chunk_source == "ChromaDB" else 1,
            label_visibility="collapsed",
        )

        if st.session_state.chunk_source == "ChromaDB":
            chunks = _load_all_chunks()
            all_books = sorted({c["book"] for c in chunks if c["book"]})
            all_topics = sorted({c["topic"] for c in chunks if c["topic"]})

            st.caption(f"{len(chunks)} total chunks in collection")

            st.session_state.filter_book = st.selectbox(
                "Filter by book", ["All"] + all_books, key="sb_filter_book",
            )
            st.session_state.filter_topic = st.selectbox(
                "Filter by topic", ["All"] + all_topics, key="sb_filter_topic",
            )
            st.session_state.filter_min_len = st.slider(
                "Min chunk length (chars)", 50, 1000, st.session_state.filter_min_len,
            )

        st.divider()

        # ── Variation Set Selector ───────────────────────────────────
        st.markdown("### Variation Set")
        set_names = list(VARIATION_SETS.keys()) + ["Custom"]
        current_name = st.session_state.variation_set_name
        if current_name not in set_names:
            current_name = set_names[0]

        selected_set = st.selectbox(
            "Predefined set", set_names,
            index=set_names.index(current_name),
            key="sb_variation_set",
        )
        if selected_set != st.session_state.variation_set_name:
            st.session_state.variation_set_name = selected_set
            if selected_set != "Custom":
                st.session_state.variation_matrix = [
                    r.copy() for r in VARIATION_SETS[selected_set]
                ]
            st.rerun()

        st.divider()

        # ── Generation Settings ──────────────────────────────────────
        st.markdown("### Generation Settings")
        st.session_state.qg_max_tokens = st.slider("QG max new tokens", 50, 400, st.session_state.qg_max_tokens)
        st.session_state.dg_max_tokens = st.slider("DG max new tokens", 20, 200, st.session_state.dg_max_tokens)
        st.session_state.show_debug = st.toggle("Show debug panels by default", st.session_state.show_debug)

        st.divider()

        # ── Export ───────────────────────────────────────────────────
        if st.session_state.generated_results:
            st.markdown("### Export")
            export_data = []
            for i, r in enumerate(st.session_state.generated_results):
                mcq = r["mcq"]
                export_data.append({
                    "variation_index": i,
                    "row": r["row"],
                    "resolved_type": r["resolved_type"],
                    "selector_reason": r["selector_reason"],
                    "misconception_context": r["misconception_ctx"],
                    "question": mcq.question if mcq else None,
                    "correct_answer": mcq.correct_answer if mcq else None,
                    "options": [{"text": o.text, "is_correct": o.is_correct} for o in mcq.options] if mcq else [],
                    "explanation": mcq.explanation if mcq else None,
                    "distractor_scores": r.get("distractor_scores", []),
                    "raw_qg_output": r.get("raw_qg_output"),
                    "raw_dg_outputs": r.get("raw_dg_outputs", []),
                    "error": r["error"],
                    "elapsed_ms": r["elapsed_ms"],
                    "generation_mode": mcq.generation_mode if mcq else None,
                })
            json_str = json.dumps(export_data, indent=2, ensure_ascii=False)
            st.download_button(
                "📥 Export results as JSON",
                data=json_str.encode("utf-8"),
                file_name="mcq_test_results.json",
                mime="application/json",
            )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    _init_session_state()

    # Title
    st.markdown(
        '<h1 style="margin-bottom:0">🧠 PersonifAI — MCQ Generation Tester</h1>',
        unsafe_allow_html=True,
    )
    st.caption("Developer tool for testing personalized MCQ generation across signal combinations.")
    st.divider()

    # Import error banner
    if _import_errors:
        for err in _import_errors:
            st.error(f"**Import error:** {err}")
        if not MCQ_PIPELINE_OK:
            st.stop()

    # Sidebar
    _render_sidebar()

    settings = _get_mcq_settings() if MCQ_SETTINGS_OK else None
    embedder = _load_embedder() if ST_OK else None

    # ── Main layout: Chunk panel (left) | Variation editor (right) ───
    left_col, right_col = st.columns([1, 1], gap="large")

    chunk_text: str = ""
    chunk_topic: str = ""
    chunk_meta: str = ""

    with left_col:
        st.markdown("### 📄 Chunk Input")

        if st.session_state.chunk_source == "ChromaDB":
            all_chunks = _load_all_chunks()

            # Apply filters
            filtered = all_chunks
            if st.session_state.filter_book != "All":
                filtered = [c for c in filtered if c["book"] == st.session_state.filter_book]
            if st.session_state.filter_topic != "All":
                filtered = [c for c in filtered if c["topic"] == st.session_state.filter_topic]
            filtered = [c for c in filtered if len(c["text"]) >= st.session_state.filter_min_len]

            st.caption(f"{len(filtered)} chunks match current filters")

            # Search
            search = st.text_input("🔍 Search chunks", value=st.session_state.chunk_search, key="chunk_search_input")
            st.session_state.chunk_search = search

            if search:
                search_lower = search.lower()
                filtered = [
                    c for c in filtered
                    if search_lower in c["text"].lower()
                    or search_lower in c["topic"].lower()
                    or search_lower in c["book"].lower()
                ]

            if not filtered:
                st.warning("No chunks match the current filters.")
            else:
                # Chunk list
                def _chunk_label(c: dict) -> str:
                    preview = c["text"][:80].replace("\n", " ")
                    return f"[{c['topic'] or 'no topic'}] {preview}…"

                labels = [_chunk_label(c) for c in filtered]
                sel_idx = 0
                if st.session_state.selected_chunk:
                    try:
                        sel_idx = next(
                            i for i, c in enumerate(filtered)
                            if c["chunk_id"] == st.session_state.selected_chunk.get("chunk_id")
                        )
                    except StopIteration:
                        sel_idx = 0

                selected_idx = st.selectbox(
                    "Select chunk", range(len(filtered)),
                    format_func=lambda i: labels[i],
                    index=sel_idx,
                    key="chunk_selector",
                )
                selected_chunk = filtered[selected_idx]
                st.session_state.selected_chunk = selected_chunk
                chunk_text = selected_chunk["text"]
                chunk_topic = selected_chunk["topic"]

                # Display selected chunk
                st.markdown("**Selected chunk:**")
                st.markdown(
                    f'<div style="background:#0F172A;border:1px solid #1E293B;border-radius:8px;'
                    f'padding:12px;max-height:280px;overflow-y:auto;font-size:0.85rem;'
                    f'white-space:pre-wrap;font-family:monospace">{chunk_text}</div>',
                    unsafe_allow_html=True,
                )

                meta_parts = []
                if selected_chunk["book"]:
                    meta_parts.append(f"📚 {selected_chunk['book']}")
                if selected_chunk["topic"]:
                    meta_parts.append(f"🏷️ {selected_chunk['topic']}")
                if selected_chunk["difficulty"]:
                    meta_parts.append(f"📊 {selected_chunk['difficulty']}")
                if selected_chunk["page_start"]:
                    meta_parts.append(f"📄 pp. {selected_chunk['page_start']}–{selected_chunk['page_end']}")
                meta_parts.append(f"🔢 {len(chunk_text)} chars")
                st.caption(" · ".join(meta_parts))

        else:  # Manual
            st.session_state.manual_chunk_text = st.text_area(
                "Paste chunk text",
                value=st.session_state.manual_chunk_text,
                height=250,
                placeholder="Paste any text here to test MCQ generation on arbitrary content…",
                key="manual_text_input",
            )
            st.session_state.manual_chunk_topic = st.text_input(
                "Topic tag (optional)",
                value=st.session_state.manual_chunk_topic,
                placeholder="e.g. Binary Search Trees",
                key="manual_topic_input",
            )
            chunk_text = st.session_state.manual_chunk_text
            chunk_topic = st.session_state.manual_chunk_topic

    with right_col:
        st.markdown("### ⚙️ Variation Matrix")

        # Column headers
        hcols = st.columns([1.2, 1.2, 1.2, 1.2, 2.5, 0.4])
        for col, label in zip(hcols, ["Mastery", "Score Cat", "Type", "Misconception", "Custom context", ""]):
            col.markdown(f"<span style='font-size:0.75rem;color:#64748B'>{label}</span>", unsafe_allow_html=True)

        matrix = _render_variation_editor()

        st.markdown("")
        can_generate = bool(chunk_text.strip()) and bool(matrix) and settings is not None

        if not chunk_text.strip():
            st.info("Select or paste a chunk to enable generation.")

        generate_btn = st.button(
            "▶ Generate All Variations",
            type="primary",
            disabled=not can_generate,
            use_container_width=True,
        )

    # ── Generation ───────────────────────────────────────────────────
    if generate_btn and can_generate:
        st.session_state.generated_results = []
        st.divider()
        st.markdown("### 📊 Generated Questions")
        progress_bar = st.progress(0, text="Starting generation…")
        result_containers = [st.empty() for _ in matrix]

        for i, row in enumerate(matrix):
            progress_bar.progress(
                (i) / len(matrix),
                text=f"Generating variation {i + 1}/{len(matrix)}…",
            )
            with result_containers[i].container():
                with st.container(border=True):
                    with st.spinner(f"Generating #{i + 1}…"):
                        result = _generate_single_variation(
                            chunk_text=chunk_text,
                            topic=chunk_topic or "General",
                            row=row,
                            settings=settings,
                            embedder=embedder,
                            topic_performance={},
                            incorrectly_answered=[],
                            qg_max_tokens=st.session_state.qg_max_tokens,
                            dg_max_tokens=st.session_state.dg_max_tokens,
                        )
                    st.session_state.generated_results.append(result)
                    _render_result_card(i, result, st.session_state.show_debug)

        progress_bar.progress(1.0, text=f"✅ Done — {len(matrix)} variations generated.")

        # Summary
        ok = sum(1 for r in st.session_state.generated_results if r["mcq"] is not None)
        failed = len(st.session_state.generated_results) - ok
        total_ms = sum(r["elapsed_ms"] for r in st.session_state.generated_results)
        st.success(
            f"**{ok}/{len(matrix)} succeeded** · {failed} failed · "
            f"Total: {total_ms:,} ms · Avg: {total_ms // max(len(matrix), 1):,} ms/question"
        )

    elif st.session_state.generated_results and not generate_btn:
        # Show persisted results from previous run
        st.divider()
        st.markdown("### 📊 Generated Questions")
        st.caption("Results from previous generation run. Click 'Generate All Variations' to regenerate.")
        for i, result in enumerate(st.session_state.generated_results):
            with st.container(border=True):
                _render_result_card(i, result, st.session_state.show_debug)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__" or True:
    main()
