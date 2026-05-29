"""
Profiler Service — LLM-powered session analysis and emotion fusion.

Uses OllamaClient for:
  • Cross-session profile rewriting (persistent student profile)
  • Real-time emotion fusion when FER and SER conflict
  • Evidence extraction (pre-profiler pass)
  • Proposed-update validation (post-profiler pass)
"""

import os
import sys
import re
import json
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

import httpx

from schemas.student_context import UnifiedStudentContext
from dotenv import load_dotenv

# Search for .env
_this_dir = Path(__file__).resolve().parent
for _candidate in [
    _this_dir / ".env",
    _this_dir.parent / ".env",
    _this_dir.parent.parent / ".env",
]:
    if _candidate.exists():
        load_dotenv(_candidate)
        break
else:
    load_dotenv()

logger = logging.getLogger(__name__)

# ── OllamaClient (shared LLM backend) ──
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore

_ollama_client: OllamaClient | None = None

def _get_ollama_client() -> OllamaClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=120,
        )
    return _ollama_client


def _clean_llm_json(text: str) -> str:
    """
    Strip markdown fences, leading/trailing whitespace, and any non-JSON
    text the LLM may have wrapped around the JSON object.
    """
    text = text.strip()

    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    # If there's text before the first '{', strip it
    first_brace = text.find("{")
    if first_brace > 0:
        text = text[first_brace:]

    # If there's text after the last '}', strip it
    last_brace = text.rfind("}")
    if last_brace >= 0 and last_brace < len(text) - 1:
        text = text[: last_brace + 1]

    return text


def _parse_llm_json(text: str, context: str = "LLM") -> dict:
    """
    Parse LLM output as JSON with robust cleanup and logging on failure.
    """
    cleaned = _clean_llm_json(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(
            f"[{context}] JSON parse failed: {e}\n"
            f"--- RAW LLM OUTPUT START ---\n{text}\n--- RAW LLM OUTPUT END ---\n"
            f"--- CLEANED TEXT START ---\n{cleaned}\n--- CLEANED TEXT END ---"
        )
        raise


# ── Cross-session profile rewriter (System B) ───────────────────

PROFILE_REWRITER_SYSTEM = """\
You are an educational psychologist AI that maintains a concise, evolving profile of a student's learning style and emotional patterns.

You will receive:
1. The student's existing profile (may be empty if this is their first session)
2. A new session log grouped by slide. Each entry represents one slide and has these fields:
   - slide_index: the position of the slide in the lesson
   - slide_title: the title of the slide
   - slide_content: the full text content of the slide
   - time_spent_seconds: how long the student spent on this slide
   - dominant_emotion: the most frequent fused emotion on this slide
   - all_emotions: list of all fused emotions recorded on this slide
   - student_questions: questions the student asked on this slide
   - tutor_responses: what the tutor said on this slide
   - notable_events: any non-passive events on this slide

Use the slide_content field to understand WHY the student reacted a certain way, not just THAT they reacted. For example:
- Was the student consistently more engaged on slides with code examples vs slides with only text?
- Did confusion correlate with abstract theory slides?
- Did positive emotions correlate with visual-heavy slides?
- Did time_spent_seconds spike on slides covering certain topic types?

CRITICAL — EMOTION LABEL INTERPRETATION:
The emotion labels in all_emotions and dominant_emotion come from an automated 
Facial Expression Recognition (FER) and Speech Emotion Recognition (SER) system.
The label "uncertain" means the RECOGNITION SYSTEM could not confidently classify 
the student's expression — it does NOT mean the student feels uncertain or confused.
Treat "uncertain" entries as missing data. Do not use them as evidence of student 
confusion, hesitation, or any emotional state. Simply ignore them.

Your job is to synthesize the existing profile with the new session data and produce an UPDATED profile.
The updated profile must be a REWRITE — not an append. It should be compact and useful.
Prioritize patterns that appear across multiple slides or sessions over single-slide signals.

Return a raw JSON object only. No markdown. No backticks. No explanation. No text before or after the JSON.

The JSON must have exactly these fields:
{
  "profile_summary": "A single concise paragraph max 5 sentences written as a note from one teacher to another describing how to teach this student effectively.",
  "profile_data": {
    "learning_style_signals": [],
    "engagement_patterns": {"high": [], "low": []},
    "emotional_tendencies": {"description": "", "notable_patterns": []},
    "notable_intentions": [],
    "recommended_approaches": [],
    "topics_of_difficulty": [],
    "topics_of_strength": [],
    "unresolved_questions": [],
    "recurrent_mistakes": []
  },
  "_changes_made": [
    {
      "field": "topics_of_difficulty",
      "action": "added",
      "value": "recursion",
      "reason": "Student showed confused emotion across 3 slides covering recursion, and asked two clarifying questions about base cases"
    }
  ]
}

The _changes_made array must cover every meaningful change compared to the existing profile — additions, removals, rewrites, and notable decisions to keep something unchanged.
This key is stripped before writing to the database — it is for audit purposes only.
"""


PROBLEM_SET_PROFILER_SYSTEM = """\
You are a learning analyst. You will be given a student's complete problem 
set results including per-question rubric breakdowns, hint usage, scores, 
and mistake patterns.

This is objective behavioral data — not conversation or subjective inference. 
Treat it as high-confidence signal.

WHAT TO ANALYZE:

Rubric category failures (correctness, logic, edge_cases, syntax_style, 
requirements):
- Consistent failure in a category across multiple questions → strong 
  signal for topics_of_difficulty
- Consistent passing in a category → consider for topics_of_strength 
  only if it appears across 3+ questions

Hint usage patterns:
- Student requested hint 3 (most direct) on multiple questions → 
  significant struggle signal for that question's topic
- Student requested no hints and scored above 80 → confidence signal 
  for that topic
- Student requested hint 2 but not hint 3 → moderate struggle, was 
  able to self-correct

Score trajectory:
- Scores improving across questions on same topic → learning in progress, 
  note in recommended_approaches that spaced repetition is working
- Scores flat or declining → topic needs different approach

Recurrent mistakes:
- Mistake tags appearing across 2+ questions → strong topics_of_difficulty 
  signal, also consider for recurrent_mistakes field
- IMPORTANT: recurrent_mistakes must contain SPECIFIC behavioral patterns, 
  not rubric category names. "correctness" or "logic" are rubric categories, 
  not mistakes. A recurrent mistake is something like "off-by-one errors in 
  loop bounds", "forgets to handle empty input", "confuses == with =", or 
  "does not validate user input before processing". If the data only has 
  rubric category names (correctness, requirements, edge_cases, logic, 
  syntax_style), use them to inform topics_of_difficulty instead — do NOT 
  copy them into recurrent_mistakes

Question topics targeted at known weaknesses:
- If a question targeted a known weakness and student passed → consider 
  moving that weakness to topics_of_strength or removing it from difficulty
- If targeted weakness question was failed → reinforce in topics_of_difficulty

OUTPUT RULES:
- Update ONLY fields where you have clear evidence from the submission data
- For list fields: APPEND new findings — do not replace existing values
- For profile_summary: REWRITE the full paragraph incorporating problem 
  set performance into the existing profile knowledge
- For recurrent_mistakes: append only SPECIFIC behavioral mistake patterns 
  (e.g. "forgets null checks", "off-by-one in loops"). Never add rubric 
  category names like "correctness", "logic", "edge_cases", "requirements" 
  — those belong in topics_of_difficulty, not recurrent_mistakes
- Do NOT touch emotional_tendencies or engagement_patterns — problem set 
  data does not carry emotional signal
- Do NOT clear or overwrite any existing profile field — only enrich it
- Return ONLY valid JSON matching the profile_data schema exactly
- This profiler updates the same profile as the session and lab profilers
"""


# ── Audit log ────────────────────────────────────────────────────

_AUDIT_DIR = Path(__file__).resolve().parent.parent / "data" / "profile_audit"


def _write_audit_entry(
    student_id: str,
    session_id: str,
    session_type: str,
    changes_made: list[dict],
    profile_summary: str,
) -> None:
    """Best-effort audit log — one file per student, never one file per call."""
    try:
        safe_id = student_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        audit_dir = _AUDIT_DIR / safe_id
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / "audit.json"

        entries: list[dict] = []
        if audit_path.exists():
            try:
                entries = json.loads(audit_path.read_text(encoding="utf-8"))
                if not isinstance(entries, list):
                    entries = []
            except Exception:
                entries = []

        entries.append({
            "written_at": datetime.utcnow().isoformat() + "Z",
            "session_id": session_id,
            "session_type": session_type,
            "profile_summary_written": profile_summary[:300],
            "changes": changes_made,
        })

        # Cap at 500 entries
        if len(entries) > 500:
            entries = entries[-500:]

        audit_path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Audit log write failed for student %s: %s", student_id, e)


def get_audit_log(student_id: str, limit: int = 20) -> list[dict]:
    """Load audit log for a student. Returns last `limit` entries."""
    try:
        safe_id = student_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        audit_path = _AUDIT_DIR / safe_id / "audit.json"
        if not audit_path.exists():
            return []
        entries = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            return []
        return entries[-limit:]
    except Exception:
        return []


async def update_profile(
    student_id: int,
    lesson_title: str,
    session_log: list[dict],
    existing_profile_summary: str = "",
    existing_profile_data: dict | None = None,
    student_context: Optional[UnifiedStudentContext] = None,
    session_id: str = "",
) -> dict:
    """
    Rewrite the student's persistent learning profile by synthesizing
    the existing profile with new session data.

    Returns { profile_summary: str, profile_data: dict }.
    """
    api_key = os.getenv("OLLAMA_API_KEY", "")
    if not api_key:
        logger.warning("OLLAMA_API_KEY not set — returning empty profile update")
        return {
            "profile_summary": existing_profile_summary or "No profile yet.",
            "profile_data": existing_profile_data or _empty_profile_data(),
        }

    # ── Build user prompt ──
    existing_data_str = json.dumps(existing_profile_data or {}, indent=2)

    context_str = ""
    if student_context:
        context_str = (
            f"STUDENT CONTEXT (Global):\n"
            f"Mastery Level: {student_context.profile.mastery_level}\n"
            f"Language Proficiency: {student_context.profile.language_proficiency}\n"
            f"Strengths: {', '.join(student_context.profile.strengths) if student_context.profile.strengths else 'None recorded'}\n"
            f"Weaknesses: {', '.join(student_context.profile.weaknesses) if student_context.profile.weaknesses else 'None recorded'}\n"
            f"Incorrectly Answered: {', '.join(student_context.profile.incorrectly_answered) if student_context.profile.incorrectly_answered else 'None recorded'}\n\n"
        )

    user_prompt = (
        f"Student ID: {student_id}\n"
        f"{context_str}"
        f"Lesson just completed: {lesson_title}\n\n"
        f"EXISTING PROFILE SUMMARY:\n"
        f"{existing_profile_summary or '(first session — no existing profile)'}\n\n"
        f"EXISTING PROFILE DATA:\n"
        f"{existing_data_str}\n\n"
        f"NEW SESSION LOG ({len(session_log)} entries):\n"
        f"{json.dumps(session_log, indent=2)}"
    )

    try:
        client = _get_ollama_client()
        result = client.chat_json(
            messages=[
                {"role": "system", "content": PROFILE_REWRITER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            timeout_override=120,
        )

        # Validate expected keys
        if "profile_summary" not in result:
            result["profile_summary"] = existing_profile_summary or ""
        if "profile_data" not in result:
            result["profile_data"] = existing_profile_data or _empty_profile_data()

        # Guard: preserve unresolved_questions — session profiler must not clear them
        if existing_profile_data and "unresolved_questions" in existing_profile_data:
            pd = result.get("profile_data", {})
            if "unresolved_questions" not in pd or not pd["unresolved_questions"]:
                pd["unresolved_questions"] = existing_profile_data["unresolved_questions"]
                result["profile_data"] = pd

        # Extract and strip _changes_made before returning
        changes_made = result.get("profile_data", {}).pop("_changes_made", [])
        if not changes_made:
            changes_made = result.pop("_changes_made", [])

        # Write audit log
        _write_audit_entry(
            str(student_id),
            session_id or f"session_{student_id}",
            "tutor_session",
            changes_made,
            result.get("profile_summary", ""),
        )

        return result

    except json.JSONDecodeError:
        return {
            "profile_summary": existing_profile_summary or "Profile update failed — LLM returned invalid JSON.",
            "profile_data": existing_profile_data or _empty_profile_data(),
        }
    except Exception as e:
        logger.error(f"Profile rewriter failed: {e}")
        raise


def _empty_profile_data() -> dict:
    """Return the default empty profile_data structure."""
    return {
        "learning_style_signals": [],
        "engagement_patterns": {"high": [], "low": []},
        "emotional_tendencies": {"description": "", "notable_patterns": []},
        "notable_intentions": [],
        "recommended_approaches": [],
        "topics_of_difficulty": [],
        "topics_of_strength": [],
        "unresolved_questions": [],
        "recurrent_mistakes": [],
    }


# ── Emotion fusion ───────────────────────────────────────────────

FUSION_SYSTEM = """\
You are an emotion analysis expert. Given facial expression recognition (FER) and speech emotion recognition (SER) results for the same moment, determine the student's true emotional state.

Return a raw JSON object only. No markdown. No backticks. No explanation. No text before or after the JSON.

The JSON must have exactly these fields: { "fused_emotion": "<emotion>", "reasoning": "<one sentence>" }
"""


async def fuse_emotions(
    fer_emotion: str,
    fer_confidence: float,
    ser_emotion: str,
    ser_confidence: float,
    slide_index: int = 0,
    slide_title: str = "",
    subtopic: str = "",
) -> dict:
    """
    Use OllamaClient LLM to resolve conflicting FER and SER emotions.
    Returns { fused_emotion, reasoning }.
    """
    api_key = os.getenv("OLLAMA_API_KEY", "")
    if not api_key:
        # Fallback: higher confidence wins
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "No API key — used FER (higher confidence)"}
        return {"fused_emotion": ser_emotion, "reasoning": "No API key — used SER (higher confidence)"}

    user_prompt = (
        f"FER detected: {fer_emotion} (confidence: {fer_confidence:.2f})\n"
        f"SER detected: {ser_emotion} (confidence: {ser_confidence:.2f})\n"
        f"Context: student is watching slide {slide_index}"
    )
    if slide_title:
        user_prompt += f' titled "{slide_title}"'
    if subtopic:
        user_prompt += f' during a lesson on "{subtopic}"'
    user_prompt += ".\nWhich emotion better represents the student's true state?"

    try:
        client = _get_ollama_client()
        result = client.chat_json(
            messages=[
                {"role": "system", "content": FUSION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            timeout_override=30,
        )
        return result
    except json.JSONDecodeError:
        logger.warning("Emotion fusion: JSON parse failed, falling back to confidence")
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "LLM returned invalid JSON — used FER (higher confidence)"}
        return {"fused_emotion": ser_emotion, "reasoning": "LLM returned invalid JSON — used SER (higher confidence)"}
    except Exception as e:
        logger.warning(f"Emotion fusion LLM failed, falling back to confidence: {e}")
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "LLM failed — used FER (higher confidence)"}
        return {"fused_emotion": ser_emotion, "reasoning": "LLM failed — used SER (higher confidence)"}


# ── Lab profiler ─────────────────────────────────────────────────

DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")

LAB_PROFILER_SYSTEM = """\
You are an expert learning analyst. You will be given data from a student's 
lab session: their written notes, which questions they chose to ask versus 
ignore, and their task completion data.

Your job is to update the student's existing learning profile based ONLY 
on what you observe in the lab data. Do not speculate beyond the evidence.

SIGNALS TO ANALYZE:

From student notes:
- Notes written early in a cell suggest the explanation confused them immediately
- Notes written after a task cell suggest reflection or lingering questions
- Notes that contain question marks are likely unresolved confusions
- Notes that are very short ("ok", "got it") suggest the student is comfortable
- Notes that are long and detailed suggest deep engagement or significant confusion

From suggested questions:
- Each cell shows which questions the student CHOSE to ask (was_asked=true) 
  and which were available but not chosen
- Analyze the ASKED questions for learning pattern signal: what topics 
  do they cluster around? Do they reveal curiosity about edge cases, 
  conceptual depth, practical application, or something else?
- Use this to inform learning_style_signals and topics_of_difficulty — 
  a student who consistently asks about edge cases learns differently 
  from one who asks about real-world applications
- Do NOT treat unasked questions as unresolved questions — a student 
  who skips a suggested question may be confident, uninterested, or 
  simply did not read it. Absence of action is ambiguous.

From task completion:
- Cells marked completed indicate the student attempted the task
- Incomplete task cells suggest difficulty or time constraints

OUTPUT RULES:
- Update ONLY the fields where you have clear evidence from the lab data
- For list fields (topics_of_difficulty, topics_of_strength, etc.): 
  APPEND new findings — do not replace existing values
- For profile_summary: REWRITE the full paragraph incorporating both 
  existing profile knowledge and new lab findings
- For unresolved_questions: populate ONLY from the student's own notes 
  that contain question marks or explicit confusion ("how", "why", 
  "what if"). Never add suggested questions that the student did not 
  ask — those are not the student's unresolved questions
- Do NOT touch engagement_patterns or emotional_tendencies unless 
  you have strong explicit evidence in the notes
- Do NOT clear or overwrite any existing profile field — only enrich it
- Return ONLY valid JSON matching the profile_data schema exactly

IMPORTANT: The session profiler has already run before this lab. 
Your job is to ADD to what it found, not replace it.
"""


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
        logger.warning("profiler: could not fetch student profile: %s", e)
    return {}


async def _patch_student_profile(student_id: str, profile_data: dict) -> None:
    """Patch the student's profile_data on Django."""
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.patch(
                f"{DJANGO_API_URL}/progress/learning-profile/update/",
                json={"profile_data": profile_data},
                headers={
                    "X-Student-ID": student_id,
                    "X-Service-Key": service_key,
                },
            )
    except Exception as e:
        logger.warning("profiler: could not patch student profile: %s", e)


async def run_lab_profiler(
    student_id: str,
    lab_id: str,
    course_id: str,
    lesson_id: str,
) -> dict:
    """
    Runs after the student completes/exits a lab.
    Analyzes lab notes, suggested question interaction, and task completion.
    Updates the same profile JSON as the session profiler.
    Does NOT re-analyze the session transcript.
    Returns the updated profile_data dict.
    """
    from services.lab_store import get_coding_lab_store

    lab_store = get_coding_lab_store()

    # Get everything the profiler needs — this method includes timestamps
    lab_data = lab_store.get_lab_notes_for_profiler(lab_id)

    if not lab_data:
        logger.warning("Lab profiler: no lab data found for lab_id=%s", lab_id)
        return {}

    # Fetch current profile to merge into
    current_profile = await _fetch_student_profile(student_id)

    # Format lab data for the prompt
    def _format_notes_for_profiler(notes: list[dict]) -> str:
        if not notes:
            return "No notes written"
        formatted = []
        for note in notes:
            ts = note.get("timestamp", "")
            content = note.get("content", "").strip()
            if content:
                formatted.append(f"  - [{ts}] {content}")
        return "\n".join(formatted) if formatted else "No notes written"

    cells_summary = []
    for cell in lab_data.get("cells", []):
        questions_summary = []
        for q in cell.get("suggested_questions", []):
            status = "ASKED" if q.get("was_asked") else "not asked"
            questions_summary.append(f"  [{status}] {q.get('question', '')}")

        cells_summary.append(
            f"Cell: {cell.get('title', 'Untitled')} "
            f"(type: {cell.get('cell_type', 'unknown')})\n"
            f"Notes:\n"
            f"{_format_notes_for_profiler(cell.get('student_notes', []))}\n"
            f"Suggested questions:\n"
            f"{chr(10).join(questions_summary) if questions_summary else '  None generated'}\n"
        )

    general_notes_text = _format_notes_for_profiler(
        lab_data.get("general_notes", [])
    )

    user_prompt = f"""CURRENT STUDENT PROFILE:
{json.dumps(current_profile, indent=2)}

LAB SESSION DATA:

General notes written by student:
{general_notes_text}

Per-cell data:
{chr(10).join(cells_summary)}

Based on this lab data, update the student profile. Remember:
- APPEND to list fields, never replace
- REWRITE profile_summary to incorporate lab findings
- POPULATE unresolved_questions ONLY from the student's own notes \
that contain question marks — never from unasked suggested questions
- Return ONLY the updated profile_data JSON object

IMPORTANT — PROPOSED CHANGES TRACKING:
Return the updated profile_data JSON with one additional key:
"_changes_made": [
    {{
        "field": "learning_style_signals",
        "action": "added",
        "value": "prefers hands-on activities",
        "reason": "Student wrote detailed notes during task cell — direct behavioral evidence"
    }}
]
The _changes_made array must list EVERY change you are proposing \
compared to the existing profile. For list fields, list each new item \
separately. For profile_summary, list it as a single 'rewrite' entry.
This key is stripped before writing to the database — it is for audit purposes only."""

    # ── Lab profiler LLM call ──
    try:
        client = _get_ollama_client()
        updated_profile = client.chat_json(
            messages=[
                {"role": "system", "content": LAB_PROFILER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            timeout_override=120,
        )

        # Ensure unresolved_questions field exists
        if "unresolved_questions" not in updated_profile:
            updated_profile["unresolved_questions"] = []

        # Extract and strip _changes_made before writing
        changes_made = updated_profile.pop("_changes_made", [])

        # Write audit log
        _write_audit_entry(
            student_id, lab_id, "lab_session",
            changes_made,
            updated_profile.get("profile_summary", ""),
        )

        # Patch Django profile
        await _patch_student_profile(student_id, updated_profile)

        return updated_profile

    except Exception as e:
        logger.error("Lab profiler failed for lab_id=%s: %s", lab_id, e)
        return current_profile


async def run_problem_set_profiler(
    student_id: str,
    problem_set_id: str,
    lesson_id: str,
) -> dict:
    """
    Runs when the student reaches the problem set summary screen
    (after viewing all results and solutions).
    Analyzes objective submission data to update the student profile.
    Returns the updated profile_data dict.
    """
    from services.problem_set_store import get_problem_set_store
    from collections import Counter

    ps_store = get_problem_set_store()

    # Load the full problem set with all submissions
    problem_set = ps_store.load(student_id, lesson_id, problem_set_id)
    if not problem_set:
        logger.warning(
            "Problem set profiler: no problem set found id=%s", problem_set_id
        )
        return {}

    # Build structured submission summary for the profiler prompt
    questions_summary = []
    all_mistake_tags = []
    hint_3_topics = []
    no_hint_high_score_topics = []

    for question in (problem_set.questions or []):
        qid = question.id if hasattr(question, "id") else question.get("id", "")
        qtopic = question.topic if hasattr(question, "topic") else question.get("topic", "")
        qtarget = (
            question.target_weakness
            if hasattr(question, "target_weakness")
            else question.get("target_weakness")
        )

        # Find submission for this question
        submissions = problem_set.submissions or {}
        sub = submissions.get(qid)
        if not sub:
            continue

        # Handle both Pydantic model and dict
        sub_dict = sub.model_dump() if hasattr(sub, "model_dump") else sub
        result = sub_dict.get("result", {})
        hints_used = sub_dict.get("hints_used", 0)
        hint_deductions = sub_dict.get("hint_deductions", {})
        final_score = result.get("final_score", result.get("score", 0))
        mistake_tags = result.get("mistake_tags", [])
        failed_evidence = result.get("failed_evidence", [])
        evaluated_rubric = result.get("evaluated_rubric", [])

        all_mistake_tags.extend(mistake_tags)

        # Track hint 3 usage
        if hints_used >= 3 or any(v > 0.10 * 40 for v in hint_deductions.values()):
            hint_3_topics.append(qtopic)

        if hints_used == 0 and final_score >= 80:
            no_hint_high_score_topics.append(qtopic)

        # Build rubric category breakdown
        category_results = {}
        for crit in evaluated_rubric:
            if isinstance(crit, dict):
                cat = crit.get("category", "unknown")
                checks = crit.get("checks", [])
                passed = sum(1 for c in checks if c.get("result") is True)
                total = len(checks)
                category_results[cat] = {
                    "passed": passed,
                    "total": total,
                    "all_passed": passed == total,
                }

        questions_summary.append({
            "topic": qtopic,
            "target_weakness": qtarget,
            "final_score": final_score,
            "hints_used": hints_used,
            "mistake_tags": mistake_tags,
            "failed_evidence": failed_evidence[:3],  # cap for prompt length
            "category_results": category_results,
        })

    if not questions_summary:
        logger.warning(
            "Problem set profiler: no submissions found for problem set %s",
            problem_set_id
        )
        return {}

    # Count recurrent mistakes
    mistake_counts = Counter(all_mistake_tags)
    recurrent_in_set = [tag for tag, count in mistake_counts.items() if count >= 2]

    # Build summary data for the prompt
    total_questions = len(questions_summary)
    average_score = round(
        sum(q["final_score"] for q in questions_summary) / total_questions
    ) if questions_summary else 0

    # ── Profiler LLM ──
    current_profile = await _fetch_student_profile(student_id)

    user_prompt = f"""CURRENT STUDENT PROFILE:
{json.dumps(current_profile, indent=2)}

PROBLEM SET SUBMISSION DATA:
Total questions: {total_questions}
Average score: {average_score}
Recurrent mistakes across questions: {recurrent_in_set}
Topics where student needed most direct hint (hint 3): {hint_3_topics}
Topics where student scored 80+ with no hints: {no_hint_high_score_topics}

Per-question breakdown:
{json.dumps(questions_summary, indent=2)}

Based on this objective submission data, update the student profile.
Remember:
- APPEND to list fields, never replace
- REWRITE profile_summary incorporating problem set performance
- High-confidence data: rubric category failures and hint 3 usage
- Medium-confidence data: single-question score patterns
- Return ONLY the updated profile_data JSON object

IMPORTANT — PROPOSED CHANGES TRACKING:
Return the updated profile_data JSON with one additional key:
"_changes_made": [
    {{
        "field": "topics_of_difficulty",
        "action": "added",
        "value": "edge case handling",
        "reason": "Student failed edge_cases rubric category in 3/4 questions — high-confidence pattern"
    }}
]
The _changes_made array must list EVERY change you are proposing \
compared to the existing profile. For list fields, list each new item \
separately. For profile_summary, list it as a single 'rewrite' entry.
This key is stripped before writing to the database — it is for audit purposes only."""

    try:
        client = _get_ollama_client()
        proposed_profile = client.chat_json(
            messages=[
                {"role": "system", "content": PROBLEM_SET_PROFILER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            timeout_override=120,
        )
    except Exception as e:
        logger.error(
            "Problem set profiler LLM failed for ps_id=%s: %s",
            problem_set_id, e
        )
        return current_profile

    # Extract and strip _changes_made before writing
    changes_made = proposed_profile.pop("_changes_made", [])

    # Write audit log
    _write_audit_entry(
        student_id, problem_set_id, "problem_set",
        changes_made,
        proposed_profile.get("profile_summary", current_profile.get("profile_summary", "")),
    )

    # Write profile to Django
    if proposed_profile:
        await _patch_student_profile(student_id, proposed_profile)

    return proposed_profile

