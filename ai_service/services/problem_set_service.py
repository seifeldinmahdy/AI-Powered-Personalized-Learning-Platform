"""
Problem Set Service — generates session-grounded, profile-driven coding problem sets.

After a lab session, this service:
1. Pulls context from SharedSessionStore (slides, lab cells, session summary)
2. Fetches the student's learning profile from Django
3. Generates a personalized multi-question problem set via OllamaClient
4. Evaluates submissions with hint penalty scoring
5. Detects recurrent mistakes and patches the student profile
"""

from __future__ import annotations

import os
import sys
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── OllamaClient ──
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore

from schemas.problem_set import (
    ProblemSetQuestion,
    ProblemSetData,
    EvaluationResult,
    RubricScore,
    SubmissionData,
)
from services.problem_set_store import get_problem_set_store
from services.session_store import get_session_store

logger = logging.getLogger(__name__)

_ollama_client: OllamaClient | None = None
_eval_client: OllamaClient | None = None

DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")


def _get_ollama_client() -> OllamaClient:
    """Generation client — uses the configured model (e.g. qwen3-coder)."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_MODEL", "qwen3-coder-next:cloud"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=180,
        )
    return _ollama_client


def _get_eval_client() -> OllamaClient:
    """Evaluation client — uses a stronger model for robust grading."""
    global _eval_client
    if _eval_client is None:
        _eval_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_EVAL_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=120,
        )
    return _eval_client


def _summarize_slides(slides_content: list) -> str:
    """Summarize slides to first 300 chars each."""
    summaries = []
    for i, slide in enumerate(slides_content[:20]):  # cap at 20 slides
        text = ""
        if isinstance(slide, dict):
            title = slide.get("title", "")
            body = slide.get("content", "") or slide.get("body_content", "")
            code = slide.get("code", "")
            text = f"{title}: {body}"
            if code:
                text += f"\nCode: {code[:200]}"
        elif isinstance(slide, str):
            text = slide
        summaries.append(f"Slide {i + 1}: {text[:300]}")
    return "\n".join(summaries)


def _summarize_lab_cells(lab_cells: list) -> str:
    """Summarize lab cells for the prompt."""
    summaries = []
    for cell in lab_cells:
        if isinstance(cell, dict):
            cell_type = cell.get("cell_type", "unknown")
            title = cell.get("title", "")
            narrative = cell.get("narrative", "")[:150] if cell.get("narrative") else ""
            code = cell.get("code", cell.get("starter_code", ""))[:200] if cell.get("code") or cell.get("starter_code") else ""
            summaries.append(f"[{cell_type}] {title}: {narrative} {code}".strip())
    return "\n".join(summaries)


async def _fetch_student_profile(student_id: str) -> dict:
    """Fetch the student's learning profile from Django."""
    try:
        # We need an auth token — for service-to-service calls we
        # pass the student_id directly.  The Django endpoint requires auth,
        # so we fall back to querying the profile via the admin-level
        # or we handle gracefully.
        # For now, return empty dict if we can't fetch.
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{DJANGO_API_URL}/progress/learning-profile/",
                headers={"X-Student-ID": student_id},
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("profile_data", {})
    except Exception as e:
        logger.warning("Could not fetch student profile: %s", e)
    return {}


async def _patch_recurrent_mistakes(student_id: str, mistakes: list[str]) -> None:
    """Patch the student's profile_data.recurrent_mistakes on Django."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch current profile
            resp = await client.get(
                f"{DJANGO_API_URL}/progress/learning-profile/",
                headers={"X-Student-ID": student_id},
            )
            if resp.status_code != 200:
                return

            current_data = resp.json()
            profile_data = current_data.get("profile_data", {})
            existing = profile_data.get("recurrent_mistakes", [])
            updated = list(set(existing + mistakes))
            profile_data["recurrent_mistakes"] = updated

            await client.patch(
                f"{DJANGO_API_URL}/progress/learning-profile/",
                json={"profile_data": profile_data},
                headers={"X-Student-ID": student_id},
            )
    except Exception as e:
        logger.warning("Could not patch recurrent mistakes: %s", e)


# ── Generation ───────────────────────────────────────────────────

PROBLEM_SET_SYSTEM = """\
You are an expert CS instructor designing a personalized post-session problem set.

Your job is to ANALYZE the session content (slides + lab exercises) and the student's learning profile, then DECIDE:
1. How many questions to generate (typically 2-8, proportional to the breadth of topics covered)
2. What topics each question should cover (grounded in the actual session content)
3. The difficulty of each question (easy / medium / hard) — bias toward the student's weak areas
4. The framing style for each question — adapt to the student's learning style (e.g. story-driven for visual learners, direct problem statements for analytical learners)
5. A rubric of 3-5 weighted evaluation criteria per question (weights must sum to 100)

CRITICAL RULES:
- Every question MUST be directly grounded in the slides and lab content provided. No generic textbook or LeetCode-style problems.
- If the student has known weaknesses, create questions that specifically target those areas.
- If the student has strengths, include at least one question that pushes them to a harder level on those topics.
- Each question must include exactly 3 progressive hints (vague → specific → near-solution).
- Include an analogy_explanation per question that explains the core concept in a way that matches the student's profile.
- Include an example_solution: ONE possible correct implementation. This is for student reference only — evaluation is rubric-based, not diffing against this solution.
- DO NOT rely on the example_solution for grading. The rubric is the sole basis for evaluation.

Output ONLY a valid JSON array of question objects. No markdown fences, no preamble, no explanation.
Each question object must have these exact fields:
  - id: a unique UUID string
  - topic: the specific topic this question covers
  - title: a short descriptive title
  - scenario_framing: the story/analogy/context introduction
  - problem_statement: the actual coding task description
  - starter_code: Python starter code with function signature and TODO
  - rubric: array of 3-5 objects, each with {"name": "...", "description": "...", "weight": N} where weights sum to 100
  - example_solution: one possible correct Python implementation (for student reference)
  - hints: array of exactly 3 strings [vague_hint, specific_hint, near_solution_hint]
  - analogy_explanation: concept explained via an analogy suited to the student
  - difficulty: "easy" or "medium" or "hard"
  - target_weakness: which weakness from the profile this targets, or null
  - language: "python"
"""


async def generate(request) -> ProblemSetData:
    """Generate a problem set grounded in session + lab context.

    Context priority:
      1. Slides and lab cells sent directly in the request (from frontend)
      2. In-memory SharedSessionStore (live session data)
      3. Persisted coding lab from disk (survives restarts)
    """
    from schemas.problem_set import ProblemSetGenerateRequest
    if not isinstance(request, ProblemSetGenerateRequest):
        # backward compat — wrap raw args
        request = ProblemSetGenerateRequest(
            session_id=request if isinstance(request, str) else "",
            student_id="", course_id="", lesson_id="",
        )

    store = get_problem_set_store()
    session_store = get_session_store()

    session_id = request.session_id
    student_id = request.student_id
    course_id = request.course_id
    lesson_id = request.lesson_id

    # ── 1. Use slides/lab cells from request (frontend-provided) ──
    slides_content: list = []
    lab_cells: list = []
    session_summary: str = ""
    profile_summary: str = request.student_profile_summary or ""

    if request.slides:
        slides_content = [s.model_dump() for s in request.slides]
        logger.info("Using %d slides from request payload", len(slides_content))

    if request.lab_cells:
        lab_cells = [c.model_dump() for c in request.lab_cells]
        logger.info("Using %d lab cells from request payload", len(lab_cells))

    if request.lesson_title:
        session_summary = f"Lesson: {request.lesson_title}"

    # ── 2. Enrich from SharedSessionStore (in-memory live session) ──
    session_ctx = session_store.get_session(session_id) if session_id else None
    if session_ctx:
        live = session_ctx.live
        if live:
            if not session_summary:
                session_summary = live.running_summary or ""
            if not slides_content:
                slides_content = live.current_slides if hasattr(live, "current_slides") and live.current_slides else []
            if not lab_cells:
                lab_cells = live.lab_cells if hasattr(live, "lab_cells") and live.lab_cells else []

        if session_ctx.profile:
            prof = session_ctx.profile
            if not profile_summary and hasattr(prof, "student_profile_summary") and prof.student_profile_summary:
                profile_summary = prof.student_profile_summary

    # ── 3. Fallback: load persisted coding lab from disk ──
    if not slides_content and not lab_cells:
        logger.info("No context from request or session — falling back to persisted lab data")
        try:
            from services.lab_store import get_coding_lab_store
            lab_store_disk = get_coding_lab_store()
            lab_id = lab_store_disk.lab_id(student_id, course_id, lesson_id)
            saved_lab = lab_store_disk.load(lab_id)
            if saved_lab:
                for cell in (saved_lab.cells or []):
                    cell_dict = cell.model_dump() if hasattr(cell, 'model_dump') else cell
                    lab_cells.append(cell_dict)
                if not session_summary:
                    session_summary = f"Coding lab: {saved_lab.title or 'Untitled'}"
                logger.info("Loaded %d lab cells from disk for lab_id=%s", len(lab_cells), lab_id)
            else:
                logger.warning("No persisted lab found for lab_id=%s", lab_id)
        except Exception as e:
            logger.warning("Failed to load lab from disk: %s", e)

    # Build prompt — let the LLM decide everything
    slides_summary = _summarize_slides(slides_content) if slides_content else "No slides available"
    lab_summary = _summarize_lab_cells(lab_cells) if lab_cells else "No lab cells available"

    # Guard: if we truly have nothing, log a clear warning
    if not slides_content and not lab_cells:
        logger.warning("No session slides or lab content available — LLM will generate with minimal context")

    user_prompt = f"""Analyze the session content below, then generate an appropriate number of coding questions (typically 2-8) that thoroughly cover the material.

SESSION SUMMARY:
{session_summary or 'No summary available'}

SLIDES CONTENT ({len(slides_content)} slides):
{slides_summary}

LAB EXERCISES ({len(lab_cells)} cells):
{lab_summary}

STUDENT PROFILE:
{profile_summary or 'No profile available'}

Based on the breadth and depth of the material above, decide how many questions are needed and what each should cover. Output ONLY a JSON array of question objects."""

    # Call LLM with retries
    client = _get_ollama_client()
    questions: list[ProblemSetQuestion] = []

    for attempt in range(3):
        try:
            raw = client.chat_json(
                messages=[
                    {"role": "system", "content": PROBLEM_SET_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                timeout_override=180,
            )

            # Log raw response for debugging
            raw_preview = str(raw)[:500] if raw is not None else "None"
            logger.info("LLM raw response (type=%s): %s", type(raw).__name__, raw_preview)

            # Handle both array and object responses
            if isinstance(raw, list):
                q_list = raw
            elif isinstance(raw, dict) and "questions" in raw:
                q_list = raw["questions"]
            elif isinstance(raw, dict):
                # Check if it's a single question or a wrapper
                if any(k in raw for k in ("topic", "title", "problem_statement")):
                    q_list = [raw]
                else:
                    # Might be wrapped in some other key
                    for key, val in raw.items():
                        if isinstance(val, list) and len(val) > 0:
                            logger.info("Found question array under key '%s' with %d items", key, len(val))
                            q_list = val
                            break
                    else:
                        q_list = [raw]
            else:
                raise ValueError(f"Unexpected LLM response type: {type(raw)}")

            logger.info("LLM returned %d raw question(s) on attempt %d", len(q_list), attempt + 1)

            for i, q in enumerate(q_list):
                if isinstance(q, dict):
                    try:
                        # Ensure id
                        if "id" not in q or not q["id"]:
                            q["id"] = str(uuid.uuid4())
                        # Ensure hints length
                        hints = q.get("hints", [])
                        while len(hints) < 3:
                            hints.append("Think about the problem structure.")
                        q["hints"] = hints[:3]
                        # Ensure rubric exists
                        if "rubric" not in q or not q["rubric"]:
                            q["rubric"] = [
                                {"name": "Correctness", "description": "Code produces correct output", "weight": 50},
                                {"name": "Code Quality", "description": "Clean, readable code", "weight": 30},
                                {"name": "Edge Cases", "description": "Handles edge cases", "weight": 20},
                            ]
                        questions.append(ProblemSetQuestion.model_validate(q))
                    except Exception as parse_err:
                        logger.warning("Failed to parse question %d: %s — raw keys: %s", i, parse_err, list(q.keys()))
                else:
                    logger.warning("Skipping non-dict question item at index %d: %s", i, type(q))

            if questions:
                logger.info("Successfully parsed %d questions", len(questions))
                break
            else:
                logger.warning("Attempt %d: LLM returned data but 0 questions parsed", attempt + 1)
        except Exception as e:
            logger.warning("Problem set generation attempt %d failed: %s", attempt + 1, e)
            if attempt == 2:
                raise RuntimeError(f"Problem set generation failed after 3 attempts: {e}")

    # Don't save empty problem sets
    if not questions:
        raise RuntimeError("Problem set generation produced 0 questions after 3 attempts")

    # Build and save
    problem_set = ProblemSetData(
        problem_set_id=str(uuid.uuid4()),
        student_id=student_id,
        lesson_id=lesson_id,
        course_id=course_id,
        generated_at=datetime.utcnow().isoformat(),
        questions=questions,
        submissions={},
    )
    store.save(problem_set)
    logger.info("Problem set saved: id=%s questions=%d", problem_set.problem_set_id, len(questions))
    return problem_set


# ── Evaluation ───────────────────────────────────────────────────

async def evaluate_submission(
    problem_set_id: str,
    question_id: str,
    student_id: str,
    lesson_id: str,
    code: str,
    language: str,
    hints_used: int,
) -> EvaluationResult:
    """Evaluate a student's code submission against the question's rubric."""
    store = get_problem_set_store()
    problem_set = store.load(student_id, lesson_id, problem_set_id)
    if not problem_set:
        raise ValueError(f"Problem set {problem_set_id} not found")

    # Find the question
    question = next((q for q in problem_set.questions if q.id == question_id), None)
    if not question:
        raise ValueError(f"Question {question_id} not found in problem set")

    # Build rubric text for the evaluator
    rubric_lines = []
    for rc in question.rubric:
        rubric_lines.append(f"- {rc.name} (weight: {rc.weight}%): {rc.description}")
    rubric_text = "\n".join(rubric_lines) or "No rubric available — score holistically."

    # Call evaluator LLM (stronger model for robust grading)
    client = _get_eval_client()
    eval_prompt = f"""You are a strict, objective code grader. Evaluate the student's submission ONLY against the rubric criteria below.

IMPORTANT RULES:
- Score EACH criterion independently on a 0-100 scale
- Base your scores ONLY on the rubric criteria descriptions — not on any other subjective measure
- A criterion scores 0 if the code does not address it at all
- A criterion scores 100 if it fully satisfies the description
- Be fair: there are many valid approaches. Do not penalize correct alternative implementations.

PROBLEM STATEMENT:
{question.problem_statement}

RUBRIC CRITERIA (evaluate each independently):
{rubric_text}

STUDENT CODE:
{code}

Return a JSON object with:
- criteria: array of objects, one per rubric criterion, each with:
    - criterion: the criterion name (must EXACTLY match rubric names)
    - score: integer 0-100 for this criterion
    - comment: one sentence explaining the score
- feedback: overall constructive explanation (2-3 sentences)
- mistake_tags: array of short labels for mistakes found (e.g. "off-by-one", "wrong base case", "missing edge case"), empty array if none
- hint_to_show: one relevant hint if the code has issues, or null if correct

Return ONLY valid JSON. No markdown fences."""

    try:
        result = client.chat_json(
            messages=[{"role": "user", "content": eval_prompt}],
            temperature=0.1,  # lower temp for consistent grading
            timeout_override=120,
        )
    except Exception as e:
        logger.error("Evaluation LLM failed: %s", e)
        result = {
            "criteria": [],
            "feedback": f"Evaluation failed: {e}",
            "mistake_tags": [],
            "hint_to_show": None,
        }

    # Parse per-criterion scores
    rubric_scores: list[RubricScore] = []
    raw_criteria = result.get("criteria", [])
    for rc_data in raw_criteria:
        if isinstance(rc_data, dict):
            rubric_scores.append(RubricScore(
                criterion=rc_data.get("criterion", "Unknown"),
                score=max(0, min(100, int(rc_data.get("score", 0)))),
                comment=rc_data.get("comment", ""),
            ))

    # Compute weighted score from rubric
    if rubric_scores and question.rubric:
        weight_map = {rc.name: rc.weight for rc in question.rubric}
        total_weight = sum(weight_map.values()) or 100
        weighted_sum = 0
        for rs in rubric_scores:
            w = weight_map.get(rs.criterion, 0)
            weighted_sum += rs.score * w
        raw_score = round(weighted_sum / total_weight)
    else:
        # Fallback: use raw_score if LLM returned it
        raw_score = max(0, min(100, int(result.get("raw_score", 50))))

    hint_penalty = min(hints_used, 3) * 5
    final_score = max(0, raw_score - hint_penalty)

    eval_result = EvaluationResult(
        raw_score=raw_score,
        hint_penalty=hint_penalty,
        final_score=final_score,
        passed=final_score >= 65,
        feedback=result.get("feedback", ""),
        rubric_scores=rubric_scores,
        mistake_tags=result.get("mistake_tags", []),
        hint_to_show=result.get("hint_to_show"),
        example_solution=question.example_solution,
    )

    # Save submission
    submission = SubmissionData(
        code=code,
        hints_used=hints_used,
        submitted_at=datetime.utcnow().isoformat(),
        result=eval_result,
    )
    store.save_submission(student_id, lesson_id, problem_set_id, question_id, submission)

    # Run recurrent mistake detection (async, best-effort)
    try:
        await _detect_recurrent_mistakes(
            student_id, lesson_id, problem_set_id, question_id,
            eval_result.mistake_tags,
        )
    except Exception as e:
        logger.warning("Recurrent mistake detection failed: %s", e)

    return eval_result


# ── Recurrent mistake detection ──────────────────────────────────

async def _detect_recurrent_mistakes(
    student_id: str,
    lesson_id: str,
    problem_set_id: str,
    question_id: str,
    new_mistake_tags: list[str],
) -> None:
    """Compare mistake tags against profile weaknesses and flag recurrent ones."""
    if not new_mistake_tags:
        return

    store = get_problem_set_store()
    problem_set = store.load(student_id, lesson_id, problem_set_id)
    if not problem_set:
        return

    # Count mistake occurrences across all submissions in this problem set
    all_mistakes: list[str] = []
    for sub in problem_set.submissions.values():
        all_mistakes.extend(sub.result.mistake_tags)

    # Find tags that appear 2+ times
    from collections import Counter
    counts = Counter(all_mistakes)
    recurrent = [tag for tag, count in counts.items() if count >= 2 and tag in new_mistake_tags]

    if not recurrent:
        # Try semantic matching with profile weaknesses
        profile_data = await _fetch_student_profile(student_id)
        weaknesses = profile_data.get("weaknesses", profile_data.get("topics_of_difficulty", []))
        if weaknesses and new_mistake_tags:
            try:
                client = _get_ollama_client()
                match_result = client.chat_json(
                    messages=[{"role": "user", "content": (
                        f"Given these student weaknesses: {json.dumps(weaknesses)}\n"
                        f"And these mistake tags from a coding submission: {json.dumps(new_mistake_tags)}\n"
                        f"Which mistake tags are semantically related to the weaknesses?\n"
                        f"Return JSON: {{\"matched\": [\"tag1\", \"tag2\"]}}"
                    )}],
                    temperature=0.1,
                    timeout_override=30,
                )
                matched = match_result.get("matched", [])
                recurrent.extend(matched)
            except Exception:
                pass  # Semantic matching is best-effort

    if recurrent:
        await _patch_recurrent_mistakes(student_id, recurrent)
