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
    RubricCriterion,
    RubricScore,
    SubmissionData,
)
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
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{DJANGO_API_URL}/progress/learning-profile/",
                headers={
                    "X-Student-ID": student_id,
                    "X-Service-Key": service_key,
                },
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("profile_data", {})
    except Exception as e:
        logger.warning("Could not fetch student profile: %s", e)
    return {}


async def _patch_recurrent_mistakes(student_id: str, mistakes: list[str]) -> None:
    """Record recurrent PROCESS mistakes through the SINGLE profile writer.

    No client-side read-modify-write: each mistake becomes a
    recurrent_process_mistake claim (source=problem_set) and the Django writer
    merges it additively (de-duping near-duplicates).
    """
    if not mistakes:
        return
    from services.profiler_service import post_profile_claims
    from schemas.profile import Claim
    claims = [
        Claim(field="recurrent_process_mistake", value=m, source="problem_set",
              evidence="recurred across >=2 problem-set questions", confidence=0.7)
        for m in mistakes if str(m).strip()
    ]
    await post_profile_claims(student_id, claims)


def _extract_relevant_profile_context(
    profile_data: dict,
    topic: str = "",
) -> str:
    """
    Extract a compact, prompt-ready profile summary from the v2 claims schema.
    HOW-to-learn only; COMPETENCE is owned by the mastery model (read elsewhere).
    """
    if not profile_data:
        return "No profile available"

    from schemas.profile import flatten_profile_for_readers
    flat = flatten_profile_for_readers(profile_data)

    parts = []
    if flat.get("preferred_modality"):
        parts.append(f"Learning style: {flat['preferred_modality']}")
    if flat.get("pace"):
        parts.append(f"Pace: {flat['pace']}")
    if flat.get("recommended_approaches"):
        parts.append(f"Effective approaches: {', '.join(flat['recommended_approaches'])}")
    if flat.get("recurrent_process_mistakes"):
        parts.append(f"Recurrent process mistakes: {', '.join(flat['recurrent_process_mistakes'][:5])}")
    if flat.get("unresolved_questions"):
        parts.append(
            f"Unresolved questions from previous sessions: "
            f"{', '.join(flat['unresolved_questions'][:5])}"
        )

    return "\n".join(parts) if parts else "No relevant profile data available"


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
- If unresolved_questions are provided and relevant to the session topic, \
design at least one question that directly addresses an unresolved question. \
This is the highest priority — a student's own open questions are the most \
valuable learning targets.
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
  - rubric: array of 3-5 RubricCriterion objects. Each criterion has:
      - id: "r1", "r2", "r3" etc.
      - category: exactly one of: "correctness", "logic", "edge_cases", "syntax_style", "requirements"
      - name: human-readable criterion name
      - weight: integer, all criteria weights must sum to exactly 100
      - checks: array of 2 to 4 RubricCheck objects. Each check has:
          - id: "r1c1", "r1c2" etc.
          - question: a yes/no question answerable by reading the source code text alone — no question may require executing the code.
            BAD: "Does the function return 5 when called with (2,3)?"
            GOOD: "Does the function return the result of adding a and b rather than a hardcoded value?"
            BAD: "Is the code correct?"
            GOOD: "Does the function use a return statement rather than only printing the result?"
          - weight: float, all check weights within one criterion must sum to exactly 1.0
      - concept_id: (optional) set to the concept ID string from AVAILABLE CONCEPTS if one matches, else omit/null.
      - result and evidence fields must NOT appear in generated output — they are added only at evaluation time
    All criterion weights must sum to exactly 100.
    All check weights within each criterion must sum to exactly 1.0.
    Always include at least "correctness" and "requirements" categories.
  - example_solution: one possible correct Python implementation (for student reference)
  - static_hint: exactly one string. A conceptual nudge only — no specific variable names, no implementation details, no code. Points toward the right thinking pattern without revealing approach or solution.
    BAD: "Use the + operator to add a and b then call print()"
    GOOD: "Think about what the function needs to communicate to the caller versus what it needs to show the user — these may require two separate actions"
    Maximum 2 sentences.
  - analogy_explanation: concept explained via an analogy suited to the student
  - difficulty: "easy" or "medium" or "hard"
  - target_weakness: which weakness from the profile this targets, or null
  - language: "python"
"""


# Mastery weighting (Batch 10a). A regenerated set is an easier variant — it must
# NUDGE mastery, never dominate or wipe the original set's evidence. Agreed hybrid:
# reduced-alpha-PER-SET (a distinct source + lower alpha). Switchable here — the
# considered alternative was a single global down-weighted fold with no per-set
# distinction (simpler, less precise).
ORIGINAL_MASTERY_ALPHA = 0.3
REGEN_MASTERY_ALPHA = 0.15


def mastery_weight_for_generation(generation_index: int) -> tuple[float, str]:
    """Return (alpha, source) for a submission against a given generation."""
    if generation_index and generation_index > 0:
        return REGEN_MASTERY_ALPHA, "problem_set_regen"
    return ORIGINAL_MASTERY_ALPHA, "problem_set"


async def _persist_problem_set(problem_set: ProblemSetData, *, regenerate: bool) -> None:
    """Durably record a generated set in Django (best-effort), and stamp the
    authoritative plan_version / generation_index back onto the in-memory object.

    The Django row is the durable, queryable record (survives restarts) and the
    regen counter / supersession live there. A storage failure must not fail
    generation — the file working-copy still serves the live session.
    """
    if not (problem_set.student_id and problem_set.course_id and problem_set.lesson_id):
        return
    try:
        import asyncio
        from services.plan_resolver import current_plan_version
        from services import artifact_client

        pv = await asyncio.to_thread(
            current_plan_version, str(problem_set.student_id), str(problem_set.course_id)
        )
        if pv is None:
            logger.info("problem_set: no plan_version — not recorded durably (ps=%s)",
                        problem_set.problem_set_id)
            return
        created = await artifact_client.create_problem_set(
            str(problem_set.student_id), str(problem_set.course_id), str(problem_set.lesson_id),
            plan_version=pv, ps_uid=problem_set.problem_set_id,
            content_json={"questions": [q.model_dump() for q in problem_set.questions]},
            regenerate=regenerate,
        )
        if created:
            problem_set.plan_version = created.get("plan_version", pv)
            problem_set.generation_index = created.get("generation_index", 0)
        elif regenerate:
            # The cap is normally pre-checked at the router; a None here on regen
            # means the durable write was rejected/failed — surface it.
            raise RuntimeError("regeneration was not recorded durably")
    except RuntimeError:
        raise
    except Exception:
        logger.warning("problem_set: durable persist failed (ps=%s)",
                       problem_set.problem_set_id, exc_info=True)


async def generate(request, regenerate: bool = False) -> ProblemSetData:
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

    # Extract structured profile context
    profile_data = await _fetch_student_profile(student_id)
    profile_context = _extract_relevant_profile_context(
        profile_data,
        topic=session_summary[:100] if session_summary else "",
    )
    unresolved_qs = profile_data.get("unresolved_questions", [])
    unresolved_block = chr(10).join(str(q) for q in unresolved_qs) if unresolved_qs else "None"

    # Fetch course concepts + student weak-concept list for targeting
    from services.mastery import (
        fetch_course_concepts, fetch_concept_mastery, top_weak_concepts, top_strong_concepts,
    )
    course_concepts: list[dict] = []
    weak_concept_block = ""
    strong_concept_block = ""
    concepts_block = ""
    if course_id:
        try:
            course_concepts = await fetch_course_concepts(course_id)
            concept_mastery = await fetch_concept_mastery(student_id)
            if concept_mastery:
                concept_label_map = {c["id"]: c["label"] for c in course_concepts}
                weak = top_weak_concepts(concept_mastery, n=3)
                weak_labeled = [
                    {**w, "label": concept_label_map.get(w["concept_id"], w["concept_id"])}
                    for w in weak
                ]
                if weak_labeled:
                    weak_concept_block = (
                        "\nWEAK CONCEPTS TO TARGET (prioritize in question selection and rubric criteria):\n"
                        + json.dumps(weak_labeled, indent=2)
                        + "\nInclude at least one question directly addressing the weakest concept above."
                    )
                # STRONG concepts back the system prompt's "push strengths harder"
                # instruction (previously had no data). From the mastery model.
                strong = top_strong_concepts(concept_mastery, n=3)
                strong_labeled = [
                    {**s, "label": concept_label_map.get(s["concept_id"], s["concept_id"])}
                    for s in strong
                ]
                if strong_labeled:
                    strong_concept_block = (
                        "\nSTRONG CONCEPTS (the student has mastered these — include at least one "
                        "harder/stretch question on the strongest concept to extend them):\n"
                        + json.dumps(strong_labeled, indent=2)
                    )
            if course_concepts:
                concepts_block = (
                    "\nAVAILABLE CONCEPTS FOR TAGGING (set concept_id in rubric criteria):\n"
                    + json.dumps(course_concepts, indent=2)
                    + "\nFor each rubric criterion, set concept_id to the ID of the most relevant concept above, or null."
                )
        except Exception as _ce:
            logger.warning("Could not fetch concepts/mastery for prompt: %s", _ce)

    user_prompt = f"""Analyze the session content below, then generate an appropriate number of coding questions (typically 2-8) that thoroughly cover the material.

SESSION SUMMARY:
{session_summary or 'No summary available'}

SLIDES CONTENT ({len(slides_content)} slides):
{slides_summary}

LAB EXERCISES ({len(lab_cells)} cells):
{lab_summary}

STUDENT PROFILE:
{profile_context}

UNRESOLVED QUESTIONS FROM PREVIOUS SESSIONS (address these if relevant):
{unresolved_block}
{weak_concept_block}
{strong_concept_block}
{concepts_block}
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
                        # Ensure static_hint exists
                        if not q.get("static_hint"):
                            q["static_hint"] = (
                                "Think carefully about what the problem is asking you to return "
                                "versus what it asks you to display."
                            )
                        # Remove legacy hints list if present
                        q.pop("hints", None)
                        # Ensure rubric exists with new structure
                        if "rubric" not in q or not q["rubric"]:
                            q["rubric"] = [
                                {
                                    "id": "r1",
                                    "category": "correctness",
                                    "name": "Correct output",
                                    "weight": 50,
                                    "checks": [
                                        {"id": "r1c1", "question": "Does the function produce the expected output?", "weight": 1.0}
                                    ]
                                },
                                {
                                    "id": "r2",
                                    "category": "requirements",
                                    "name": "Satisfies requirements",
                                    "weight": 50,
                                    "checks": [
                                        {"id": "r2c1", "question": "Does the function satisfy all stated requirements?", "weight": 1.0}
                                    ]
                                }
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

    # Defensive: drop any concept_id the LLM hallucinated that isn't a real
    # course concept, so mastery.py never writes a junk key into concept_mastery.
    if course_concepts:
        valid_concept_ids = {str(c["id"]) for c in course_concepts}
        dropped = 0
        for q in questions:
            for crit in q.rubric:
                if crit.concept_id and str(crit.concept_id) not in valid_concept_ids:
                    crit.concept_id = None
                    dropped += 1
        if dropped:
            logger.info("Dropped %d hallucinated concept_id(s) not in course concepts", dropped)

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
    # Durably record in Django first (stamps plan_version + generation_index),
    # then keep the file working-copy for the live in-session flow.
    await _persist_problem_set(problem_set, regenerate=regenerate)
    logger.info("Problem set saved: id=%s questions=%d gen=%d v%d",
                problem_set.problem_set_id, len(questions),
                problem_set.generation_index, problem_set.plan_version)
    return problem_set


# ── Evaluation ───────────────────────────────────────────────────


def _calculate_score(
    evaluated_criteria: list,
    hint_deductions: dict[str, float] | None = None,
) -> tuple[int, list[str]]:
    """
    evaluated_criteria: RubricCriterion objects/dicts with result+evidence
                        filled in per check
    hint_deductions: check_id -> total points already deducted from
                     dynamic hints. Pass None or {} if no hints used.
    Returns: (final_score_0_to_100, failed_evidence_strings)
    """
    if hint_deductions is None:
        hint_deductions = {}

    total = 0.0
    failed_evidence = []

    for criterion in evaluated_criteria:
        # handle both Pydantic model and dict
        crit = criterion if isinstance(criterion, dict) else criterion.model_dump()
        for check in crit.get("checks", []):
            check_contribution = crit["weight"] * check["weight"]
            if check.get("result") is True:
                earned = check_contribution
                earned -= hint_deductions.get(check["id"], 0.0)
                total += max(earned, 0.0)
            else:
                ev = check.get("evidence", "")
                if ev:
                    failed_evidence.append(
                        f"[{crit['category']} / {crit['name']}] {ev}"
                    )

    return (round(total), failed_evidence)


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
    from services import artifact_client
    raw_ps = await artifact_client.get_problem_set(student_id, problem_set_id)
    if not raw_ps or not raw_ps.get("content_json"):
        raise ValueError(f"Problem set {problem_set_id} not found")

    questions_data = raw_ps["content_json"].get("questions", [])
    question_data = next((q for q in questions_data if q.get("id") == question_id), None)
    if not question_data:
        raise ValueError(f"Question {question_id} not found in problem set")
    
    question = ProblemSetQuestion.model_validate(question_data)

    # Build binary-check evaluation prompts
    eval_system = """You are a code reviewer. You will be given a coding problem, the student's submitted code, and a rubric containing criteria with binary checks.

For each check in every criterion, you must fill in:
- result: true if the student's code satisfies this check when read as source text, false if it does not. You cannot execute the code — answer only from reading the source.
- evidence: if result is true, quote the exact line(s) from the submitted code that satisfy the check. If result is false, write one sentence naming the specific construct, statement, or logic that is absent or wrong — reference the actual submitted code where possible, not a generic statement.

Hard rules:
- Answer EVERY check in EVERY criterion without exception
- result must be exactly the boolean true or false — not a string, not null
- evidence must always be specific to this submission
- Do not add an overall score, grade, or any commentary outside the schema
- Return only the criteria array as JSON with result and evidence filled in on every check"""

    eval_user = f"""PROBLEM:
{question.problem_statement}

STUDENT CODE:
{code}

RUBRIC — fill in result and evidence for every check:
{json.dumps([c.model_dump() for c in question.rubric], indent=2)}"""

    # Call evaluator LLM (stronger model for robust grading)
    client = _get_eval_client()
    try:
        result = client.chat_json(
            messages=[
                {"role": "system", "content": eval_system},
                {"role": "user", "content": eval_user},
            ],
            temperature=0.1,  # low temp for consistent binary grading
            timeout_override=120,
        )
    except Exception as e:
        logger.error("Evaluation LLM failed: %s", e)
        result = []

    # Parse the evaluated rubric returned by the LLM
    # LLM returns the criteria array with result+evidence filled in
    evaluated_criteria_raw = result if isinstance(result, list) else result.get("criteria", result.get("rubric", []))

    # Reconstruct RubricCriterion objects with result+evidence applied
    evaluated_criteria = []
    for idx, orig_criterion in enumerate(question.rubric):
        crit_dict = orig_criterion.model_dump()
        llm_criterion = evaluated_criteria_raw[idx] if idx < len(evaluated_criteria_raw) else {}
        llm_checks = llm_criterion.get("checks", []) if isinstance(llm_criterion, dict) else []
        llm_check_map = {c["id"]: c for c in llm_checks if isinstance(c, dict)}

        for check in crit_dict["checks"]:
            llm_check = llm_check_map.get(check["id"], {})
            check["result"] = llm_check.get("result", False)
            check["evidence"] = llm_check.get("evidence", "")

        evaluated_criteria.append(crit_dict)

    # Load hint deductions from Django
    hint_tracking = raw_ps.get("hint_tracking") or {}
    hint_deductions = hint_tracking.get(question_id, {}).get("hint_deductions", {})

    # Score deterministically
    raw_score, failed_evidence = _calculate_score(evaluated_criteria, hint_deductions)

    # hint_penalty is now the sum of all check-level deductions already
    # applied inside _calculate_score — compute for reporting only
    hint_penalty = round(sum(hint_deductions.values()))
    final_score = raw_score  # deductions already applied inside _calculate_score

    # Build rubric breakdown from evaluated criteria — no LLM involvement
    rubric_scores = [
        RubricScore(
            criterion=crit["name"],
            category=crit["category"],
            earned=round(sum(
                crit["weight"] * check["weight"]
                for check in crit["checks"]
                if check.get("result") is True
            )),
            max=round(crit["weight"]),
            comment=(
                "; ".join(
                    check["evidence"]
                    for check in crit["checks"]
                    if check.get("result") is False and check.get("evidence")
                ) or "All checks passed"
            ),
        )
        for crit in evaluated_criteria
    ]

    # mistake_tags — deterministic from failed criterion categories
    mistake_tags = list(set(
        crit["category"]
        for crit in evaluated_criteria
        for check in crit["checks"]
        if check.get("result") is False
    ))

    # Feedback paragraph — one remaining LLM call
    if failed_evidence:
        feedback_prompt = (
            "A student submitted code with these specific issues:\n"
            + "\n".join(f"- {e}" for e in failed_evidence)
            + "\n\nWrite a 2-3 sentence constructive feedback paragraph "
            "summarizing what to focus on improving. Do not repeat the "
            "issues verbatim. Do not mention scores or grades. "
            "Return only the paragraph text, no JSON."
        )
        try:
            feedback = _get_eval_client().chat(
                messages=[{"role": "user", "content": feedback_prompt}],
                temperature=0.3,
                timeout_override=60,
            )
        except Exception:
            feedback = " ".join(failed_evidence[:2])  # fallback
    else:
        feedback = "Great work — all rubric checks passed."

    eval_result = EvaluationResult(
        raw_score=raw_score,
        hint_penalty=hint_penalty,
        final_score=final_score,
        passed=final_score >= 65,
        feedback=feedback,
        rubric_scores=rubric_scores,
        evaluated_rubric=[
            RubricCriterion.model_validate(c) for c in evaluated_criteria
        ],
        mistake_tags=mistake_tags,
        hint_to_show=None,
        example_solution=question.example_solution,
    )

    # Submission is saved durable via routers/problem_set.py calling artifact_client.append_attempt

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

STANDARD_CATEGORIES = {
    "correctness", "logic", "edge_cases", "syntax_style", "requirements"
}


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

    from services import artifact_client
    raw_ps = await artifact_client.get_problem_set(student_id, problem_set_id)
    if not raw_ps:
        return

    # Count mistake occurrences across all attempts in this problem set
    all_mistakes: list[str] = []
    for attempt in raw_ps.get("attempts", []):
        for crit in attempt.get("evaluated_rubric", []):
            for check in crit.get("checks", []):
                if check.get("result") is False:
                    all_mistakes.append(crit.get("category", "unknown"))

    # Find tags that appear 2+ times
    from collections import Counter
    counts = Counter(all_mistakes)

    # Direct category match first — no LLM needed
    recurrent = [
        tag for tag, count in counts.items()
        if count >= 2 and tag in new_mistake_tags
    ]

    # Also check if any standard category tag appears in profile weaknesses
    # by direct string match
    if not recurrent:
        from schemas.profile import flatten_profile_for_readers
        profile_data = await _fetch_student_profile(student_id)
        # Compare against known PROCESS mistakes (competence lives in mastery now).
        weaknesses = flatten_profile_for_readers(profile_data).get("recurrent_process_mistakes", [])
        weakness_text = " ".join(str(w) for w in weaknesses).lower()
        recurrent = [
            tag for tag in new_mistake_tags
            if tag.replace("_", " ") in weakness_text
            and counts.get(tag, 0) >= 2
        ]

        # Only use LLM semantic matching as last resort if still nothing found
        if not recurrent and weaknesses and new_mistake_tags:
            # existing semantic matching LLM call — kept as-is
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


# ── Dynamic hint generation ──────────────────────────────────────

HINT_PENALTY_PCT = 0.10  # hardcoded, never configurable


async def generate_dynamic_hint(
    problem_set_id: str,
    question_id: str,
    student_id: str,
    lesson_id: str,
    current_code: str,
    hint_number: int,
    evaluated_rubric: list | None,
) -> dict:
    """Generate a context-aware dynamic hint for hint_number 2 or 3."""
    from services import artifact_client
    raw_ps = await artifact_client.get_problem_set(student_id, problem_set_id)
    if not raw_ps or not raw_ps.get("content_json"):
        raise ValueError(f"Problem set {problem_set_id} not found")

    questions_data = raw_ps["content_json"].get("questions", [])
    question_data = next((q for q in questions_data if q.get("id") == question_id), None)
    if not question_data:
        raise ValueError(f"Question {question_id} not found in problem set")
    
    question = ProblemSetQuestion.model_validate(question_data)

    # Load existing hint deductions from Django
    hint_tracking = raw_ps.get("hint_tracking") or {}
    q_tracking = hint_tracking.get(question_id, {})
    existing_deductions = q_tracking.get("hint_deductions", {})
    already_targeted = set(existing_deductions.keys())

    # Determine evaluated rubric for finding failing checks
    eval_criteria = None
    if evaluated_rubric is not None:
        # Use the provided evaluated rubric directly
        eval_criteria = evaluated_rubric
    else:
        # DO NOT SAVE — read-only hint evaluation
        # Run lightweight binary check eval to find failing checks
        eval_system = """You are a code reviewer. You will be given a coding problem, the student's submitted code, and a rubric containing criteria with binary checks.

For each check in every criterion, you must fill in:
- result: true if the student's code satisfies this check when read as source text, false if it does not.
- evidence: if result is true, quote the exact line(s). If result is false, write one sentence naming what is absent or wrong.

Return only the criteria array as JSON with result and evidence filled in on every check."""

        eval_user = f"""PROBLEM:
{question.problem_statement}

STUDENT CODE:
{current_code if current_code.strip() else "[No code written yet]"}

RUBRIC — fill in result and evidence for every check:
{json.dumps([c.model_dump() for c in question.rubric], indent=2)}"""

        try:
            client = _get_eval_client()
            lightweight_result = client.chat_json(
                messages=[
                    {"role": "system", "content": eval_system},
                    {"role": "user", "content": eval_user},
                ],
                temperature=0.1,
                timeout_override=120,
            )
        except Exception as e:
            logger.warning("Lightweight hint eval failed: %s", e)
            lightweight_result = []

        # Parse into criteria dicts — DO NOT SAVE to store
        lightweight_raw = lightweight_result if isinstance(lightweight_result, list) else lightweight_result.get("criteria", lightweight_result.get("rubric", []))
        eval_criteria = []
        for idx, orig_criterion in enumerate(question.rubric):
            crit_dict = orig_criterion.model_dump()
            llm_criterion = lightweight_raw[idx] if idx < len(lightweight_raw) else {}
            llm_checks = llm_criterion.get("checks", []) if isinstance(llm_criterion, dict) else []
            llm_check_map = {c["id"]: c for c in llm_checks if isinstance(c, dict)}
            for check in crit_dict["checks"]:
                llm_check = llm_check_map.get(check["id"], {})
                check["result"] = llm_check.get("result", False)
                check["evidence"] = llm_check.get("evidence", "")
            eval_criteria.append(crit_dict)

    # Find target check — highest-impact failing check not already targeted
    target = None
    target_criterion = None
    target_check = None
    try:
        target = max(
            (
                (crit, check)
                for crit in eval_criteria
                for check in (crit.get("checks", []) if isinstance(crit, dict) else crit.checks)
                if (check.get("result") if isinstance(check, dict) else check.result) is False
                and (check.get("id") if isinstance(check, dict) else check.id) not in already_targeted
            ),
            key=lambda x: (
                (x[0].get("weight") if isinstance(x[0], dict) else x[0].weight)
                * (x[1].get("weight") if isinstance(x[1], dict) else x[1].weight)
            ),
            default=None,
        )
    except (ValueError, StopIteration):
        target = None

    if target is not None:
        tc, tk = target
        target_criterion = tc if isinstance(tc, dict) else tc.model_dump()
        target_check = tk if isinstance(tk, dict) else tk.model_dump() if hasattr(tk, "model_dump") else tk
    else:
        # No failing check found — return static hint
        return {
            "hint_content": question.static_hint,
            "targets_criterion_id": None,
            "targets_check_id": None,
            "penalty_applied": 0.0,
            "hint_deductions": existing_deductions,
        }

    # Generate hint text using generation client
    gen_client = _get_ollama_client()

    if hint_number == 2:
        # Hint 2 — indirect, temperature=0.3
        hint_prompt = f"""The student is working on this problem:
{question.problem_statement}

Their current code:
{current_code if current_code.strip() else "[No code written yet]"}

They are struggling with the {target_criterion["category"]} aspect of the solution.

Write a maximum 2-sentence hint that steers them toward fixing it without naming the solution, showing code, or quoting the rubric.
Return only the hint text."""

        try:
            hint_content = gen_client.chat(
                messages=[{"role": "user", "content": hint_prompt}],
                temperature=0.3,
                timeout_override=60,
            )
        except Exception:
            hint_content = question.static_hint
    else:
        # Hint 3 — direct, temperature=0.0
        evidence_line = f"\nEvidence: {target_check['evidence']}" if target_check.get("evidence") else ""
        hint_prompt = f"""The student is working on this problem:
{question.problem_statement}

Their current code:
{current_code if current_code.strip() else "[No code written yet]"}

They are failing this specific check:
{target_check["question"]}
{evidence_line}

Write a direct 2-3 sentence hint naming exactly what is wrong and what specific change to make. Reference their code if possible. Do not show the complete solution or corrected code blocks.
Return only the hint text."""

        try:
            hint_content = gen_client.chat(
                messages=[{"role": "user", "content": hint_prompt}],
                temperature=0.0,
                timeout_override=60,
            )
        except Exception:
            hint_content = f"Check your code for: {target_check['question']}"

    # Penalty calculation — FIXED values
    check_contribution = target_criterion["weight"] * target_check["weight"]
    penalty = check_contribution * HINT_PENALTY_PCT
    if hint_number == 3:
        penalty *= 2  # hint 3 = 20% of check contribution

    check_id = target_check["id"]
    existing_deductions[check_id] = existing_deductions.get(check_id, 0.0) + penalty

    # Persist hint deduction immediately via patch
    if question_id not in hint_tracking:
        hint_tracking[question_id] = {"hint_deductions": {}, "dynamic_hints_revealed": []}
    hint_tracking[question_id]["hint_deductions"] = existing_deductions
    hint_tracking[question_id]["dynamic_hints_revealed"].append({
        "hint_number": hint_number,
        "content": hint_content,
        "targets_check_id": check_id,
        "penalty_applied": penalty,
    })
    
    await artifact_client.patch_hint_tracking(student_id, problem_set_id, hint_tracking)

    return {
        "hint_content": hint_content,
        "targets_criterion_id": target_criterion.get("id"),
        "targets_check_id": check_id,
        "penalty_applied": round(penalty, 2),
        "hint_deductions": existing_deductions,
    }
