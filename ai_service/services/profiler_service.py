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
2. A timestamped log of the student's emotional states and spoken intentions during a new lesson, correlated with slides and subtopics

Your job is to synthesize the existing profile with the new session's data and produce an UPDATED profile.
The updated profile must be a REWRITE — not an append. It should be compact and useful.
Prioritize patterns that appear across multiple sessions. Let single-session signals inform but not dominate.

Return a raw JSON object only. No markdown. No backticks. No explanation. No text before or after the JSON.

The JSON must have exactly these fields:
{
  "profile_summary": "A single concise paragraph (max 5 sentences) written as a note from one teacher to another describing how to teach this student effectively.",
  "profile_data": {
    "learning_style_signals": ["list of observed learning preferences"],
    "engagement_patterns": { "high": ["contexts where student is most engaged"], "low": ["contexts where student disengages"] },
    "emotional_tendencies": { "description": "...", "notable_patterns": [] },
    "notable_intentions": ["list of requested adjustments like pace preferences, off-topic frequency, etc."],
    "recommended_approaches": ["specific teaching strategies that work for this student"],
    "topics_of_difficulty": ["concepts or styles the student struggles with"],
    "topics_of_strength": ["concepts or styles the student grasps easily"]
  }
}
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

Question topics targeted at known weaknesses:
- If a question targeted a known weakness and student passed → consider 
  moving that weakness to topics_of_strength or removing it from difficulty
- If targeted weakness question was failed → reinforce in topics_of_difficulty

OUTPUT RULES:
- Update ONLY fields where you have clear evidence from the submission data
- For list fields: APPEND new findings — do not replace existing values
- For profile_summary: REWRITE the full paragraph incorporating problem 
  set performance into the existing profile knowledge
- For recurrent_mistakes: append any mistake tags seen 2+ times
- Do NOT touch emotional_tendencies or engagement_patterns — problem set 
  data does not carry emotional signal
- Do NOT clear or overwrite any existing profile field — only enrich it
- Return ONLY valid JSON matching the profile_data schema exactly
- This profiler updates the same profile as the session and lab profilers
"""


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
    from services.evidence_ledger_store import get_evidence_ledger_store

    api_key = os.getenv("OLLAMA_API_KEY", "")
    if not api_key:
        logger.warning("OLLAMA_API_KEY not set — returning empty profile update")
        return {
            "profile_summary": existing_profile_summary or "No profile yet.",
            "profile_data": existing_profile_data or _empty_profile_data(),
        }

    student_id_str = str(student_id)

    # ── Pass 1: Evidence extraction (in-memory only, not persisted to ledger) ──
    raw_session_data = {
        "session_log": session_log,
        "transcript": json.dumps(session_log, indent=2),
        "additional_context": f"Lesson: {lesson_title}",
    }
    evidence_items = await _extract_evidence(
        session_id=session_id or f"session_{student_id}",
        session_type="tutor_session",
        raw_data=raw_session_data,
    )
    qualifying_count = len(evidence_items)
    logger.info(
        "Session profiler: %d qualifying observations extracted",
        qualifying_count,
    )

    # ── Existing profiler LLM call (UNCHANGED) ──
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
        f"NEW SESSION EMOTION LOG ({len(session_log)} events):\n"
        f"{json.dumps(session_log, indent=2)}\n\n"
        f"IMPORTANT — PROPOSED CHANGES TRACKING:\n"
        f"Return the updated profile_data JSON with one additional key:\n"
        f'"_proposed_changes": [\n'
        f'    {{\n'
        f'        "field": "learning_style_signals",\n'
        f'        "value": "prefers hands-on activities",\n'
        f'        "justification": "Student explicitly asked about edge cases during task — direct behavioral evidence",\n'
        f'        "evidence_count": 1,\n'
        f'        "confidence": "high"\n'
        f'    }}\n'
        f']\n'
        f"The _proposed_changes array must list EVERY change you are proposing "
        f"compared to the existing profile. For list fields, list each new item "
        f"separately. For profile_summary, list it as a single 'rewrite' entry.\n"
        f"This key is stripped before writing to the database — it is for validation only."
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

        # ── Pass 3: Validation (AFTER existing profiler LLM call) ──
        proposed_profile = result.get("profile_data", {})
        current_profile = existing_profile_data or {}

        validated_profile = await _validate_proposed_updates(
            student_id=student_id_str,
            proposed_updates=proposed_profile,
            current_profile=current_profile,
            session_id=session_id or f"session_{student_id}",
            session_type="tutor_session",
            qualifying_observation_count=qualifying_count,
        )

        # Preserve profile_summary from the profiler (threshold=0, always passes)
        if "profile_summary" not in validated_profile and "profile_summary" in result:
            validated_profile["profile_summary"] = result["profile_summary"]

        result["profile_data"] = validated_profile
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
        "recommended_approaches": [],
        "topics_of_difficulty": [],
        "topics_of_strength": [],
        "unresolved_questions": [],
    }


# ── Evidence-based validation layer ─────────────────────────────
# These constants and functions wrap around the existing profiler
# passes. They do NOT replace any existing LLM call or prompt.

# Minimum number of QUALIFYING observations needed before the validator
# runs for a proposed change to this field.
# A qualifying observation is one from a positive action source —
# never from absence of action.
EVIDENCE_THRESHOLDS = {
    "learning_style_signals": 2,
    "topics_of_difficulty": 2,
    "topics_of_strength": 2,
    "recommended_approaches": 1,
    "engagement_patterns": 2,
    "notable_intentions": 1,
    "emotional_tendencies": 3,
    "unresolved_questions": 1,
    "profile_summary": 0,    # always rewrite, no threshold
    "recurrent_mistakes": 1,
}

# Sources that count as qualifying positive-action observations.
# Any observation whose source is NOT in this set is discarded.
# "did not ask" observations are discarded at extraction time,
# but this is a second safety net.
QUALIFYING_SOURCES = {
    "transcript",           # student said something explicitly
    "lab_notes",            # student wrote a note
    "task_completion",      # student completed or failed a task cell
    "suggested_questions",  # student CLICKED a suggested question (was_asked=True only)
    "submission",           # problem set submission result
    "hint_usage",           # student used hint 3 (genuine struggle signal)
    "explicit_statement",   # student directly stated a preference
}

# Sources that are low-signal and only count toward emotional_tendencies
LOW_SIGNAL_SOURCES = {
    "emotion_detection",    # FER/SER — only valid for emotional_tendencies field
}


# ── Evidence extractor (pre-profiler first pass) ────────────────

EVIDENCE_EXTRACTOR_SYSTEM = """\
You are a behavioral observation recorder for a student learning system.
You will be given data from a learning session. Your job is to extract 
qualifying behavioral observations — things the student ACTIVELY DID.

CRITICAL RULE — WHAT TO RECORD AND WHAT TO DISCARD:

RECORD these (positive actions):
- Student explicitly said or wrote something (quote it directly)
- Student asked a question (they clicked it or typed it)
- Student wrote a note (what did they write and about what)
- Student completed or attempted a task (what was the task)
- Student scored above or below a threshold on an objective assessment
- Student used a hint (especially hint level 3 — direct hint — signals 
  genuine struggle)
- Student explicitly stated a preference ("I prefer", "can you slow down",
  "can you show me visually", etc.)

DISCARD these (absence of action — never record):
- Student did NOT ask a question
- Student did NOT click something
- Student did NOT write a note
- Student IGNORED something
- Anything phrased as "student did not" or "student failed to"

Absence of action is almost always ambiguous and must never be recorded.
A student who doesn't click a suggested question about visual analogies 
might be confident, might not have read it, or might not be interested — 
you cannot know which.

CONFIDENCE LEVELS:
- high: student explicitly stated something, or objective score/completion data
- medium: clear behavioral pattern from an action they took
- low: single ambiguous instance of an action (use sparingly)

SOURCES — use exactly one of these strings:
- "transcript" — student said something during the session
- "lab_notes" — student wrote a note in the lab
- "task_completion" — student completed or attempted a task cell
- "suggested_questions" — student clicked a suggested question
- "submission" — objective problem set score or rubric result
- "hint_usage" — student requested a hint (level matters)
- "explicit_statement" — student directly stated a preference
- "emotion_detection" — FER/SER reading (LOW SIGNAL — only use for 
  emotional_tendencies, never for learning style or topic difficulty)

Return ONLY a valid JSON array. No markdown, no preamble.
If there are no qualifying observations, return an empty array [].

Each object:
{
  "raw_observation": str,    // what the student ACTIVELY did, quoted directly
  "supports_labels": list,   // which profile fields this might inform
  "confidence": str,         // "high", "medium", or "low"
  "source": str,             // exactly one of the source strings above
  "approximate_timestamp": str  // ISO string if available, "" if not
}
"""


def _build_extractor_user_message(
    session_type: str,
    raw_data: dict,
) -> str:
    if session_type == "tutor_session":
        return f"""SESSION TYPE: Tutor session

TRANSCRIPT/LOGS:
{raw_data.get("transcript", json.dumps(raw_data.get("session_log", []), indent=2))}

ADDITIONAL CONTEXT:
{raw_data.get("additional_context", "None")}

Extract all behavioral observations from this session data."""

    elif session_type == "lab_session":
        cells_text = ""
        for cell in raw_data.get("cells", []):
            notes = cell.get("student_notes", [])
            questions = cell.get("suggested_questions", [])
            notes_text = "\n".join(
                f"  [{n.get('timestamp', '')}] {n.get('content', '')}"
                for n in notes
            ) or "  No notes"
            # Only include questions the student actually clicked
            asked_questions = [
                f"  [ASKED] {q.get('question', '')}"
                for q in questions
                if q.get("was_asked")
            ]
            questions_text = "\n".join(asked_questions) or "  No questions asked"
            cells_text += (
                f"\nCell: {cell.get('title', 'Untitled')} "
                f"(type: {cell.get('cell_type', '')})\n"
                f"Notes:\n{notes_text}\n"
                f"Suggested questions:\n{questions_text}\n"
            )

        general_notes = "\n".join(
            f"[{n.get('timestamp', '')}] {n.get('content', '')}"
            for n in raw_data.get("general_notes", [])
        ) or "None"

        return f"""SESSION TYPE: Lab session

GENERAL NOTES:
{general_notes}

PER-CELL DATA:
{cells_text}

Extract all behavioral observations from this lab data."""

    elif session_type == "problem_set":
        qs = raw_data.get("questions", [])
        questions_text = ""
        for q in qs:
            cat_results = q.get("category_results", {})
            cat_parts = []
            for cat, r in cat_results.items():
                if r.get("all_passed"):
                    cat_parts.append(f"{cat}: pass")
                else:
                    p = r.get("passed", 0)
                    t = r.get("total", 0)
                    cat_parts.append(f"{cat}: {p}/{t} checks")
            cat_summary = ", ".join(cat_parts)
            questions_text += (
                f"\nTopic: {q.get('topic', '')}\n"
                f"Score: {q.get('final_score', 0)}/100 | Hints used: {q.get('hints_used', 0)}\n"
                f"Rubric categories: {cat_summary}\n"
                f"Mistake tags: {', '.join(q.get('mistake_tags', [])) or 'none'}\n"
                f"Failed evidence: {'; '.join(q.get('failed_evidence', [])) or 'none'}\n"
            )

        return f"""SESSION TYPE: Problem set results

SUMMARY:
- Total questions: {raw_data.get('total_questions', 0)}
- Average score: {raw_data.get('average_score', 0)}
- Recurrent mistakes: {', '.join(raw_data.get('recurrent_mistakes_in_set', [])) or 'none'}
- Topics needing most help (hint 3 used): {', '.join(raw_data.get('hint_3_topics', [])) or 'none'}
- Topics showing confidence (no hints, high score): {', '.join(raw_data.get('no_hint_high_score_topics', [])) or 'none'}

PER-QUESTION DATA:
{questions_text}

Extract behavioral observations from this objective submission data. 
Rubric category failures and hint 3 usage are high-confidence signals. 
Single-question patterns are medium confidence."""

    return f"SESSION TYPE: {session_type}\nDATA: {json.dumps(raw_data)}"


async def _extract_evidence(
    session_id: str,
    session_type: str,
    raw_data: dict,
) -> list[dict]:
    """
    Extract qualifying behavioral observations from session data.
    Returns only positive-action observations — never absence-of-action.
    Uses _get_ollama_client() at temperature=0.1.
    """
    user_message = _build_extractor_user_message(session_type, raw_data)

    try:
        client = _get_ollama_client()
        result = client.chat_json(
            messages=[
                {"role": "system", "content": EVIDENCE_EXTRACTOR_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            timeout_override=60,
        )

        # Result should be a list
        if isinstance(result, list):
            observations = result
        elif isinstance(result, dict) and "observations" in result:
            observations = result["observations"]
        else:
            logger.warning("Evidence extractor returned unexpected shape: %s", type(result))
            return []

        # Filter: discard any observation that slipped through the prompt
        # filter and is phrased as absence of action
        absence_phrases = [
            "did not ask", "did not click", "did not write",
            "did not complete", "failed to", "never asked",
            "ignored", "skipped", "did not interact",
        ]
        filtered = []
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            raw = obs.get("raw_observation", "").lower()
            if any(phrase in raw for phrase in absence_phrases):
                logger.debug(
                    "Discarding absence-of-action observation: %s",
                    obs.get("raw_observation", "")[:80],
                )
                continue
            # Discard emotion_detection observations for non-emotional fields
            source = obs.get("source", "")
            supports = obs.get("supports_labels", [])
            if source == "emotion_detection":
                # Only keep if it supports emotional_tendencies
                if not any("emotion" in str(s).lower() for s in supports):
                    continue
            filtered.append(obs)

        logger.info(
            "Evidence extractor: %d raw observations, %d after filtering",
            len(observations), len(filtered),
        )
        return filtered

    except Exception as e:
        logger.warning("Evidence extraction failed: %s", e)
        return []


# ── Validator (post-profiler third pass) ────────────────────────


def _apply_single_change(profile: dict, field: str, value: str) -> None:
    """Apply a single validated change to the profile dict in place."""
    if "." in field:
        parent, child = field.split(".", 1)
        if parent not in profile:
            profile[parent] = {}
        target = profile[parent]
        if isinstance(target, dict):
            if isinstance(target.get(child), list):
                if value not in target[child]:
                    target[child].append(value)
            else:
                target[child] = value
    elif isinstance(profile.get(field), list):
        if value not in profile[field]:
            profile[field].append(value)
    elif field in profile or field in EVIDENCE_THRESHOLDS:
        profile[field] = value


def _diff_profile_updates(current: dict, proposed: dict) -> list[dict]:
    """
    Fallback: compute proposed changes by diffing current vs proposed.
    Used when profiler LLM did not include _proposed_changes.
    Returns list of change dicts with empty justification.
    """
    changes = []
    for field, proposed_value in proposed.items():
        if field.startswith("_"):
            continue
        current_value = current.get(field)

        if isinstance(proposed_value, list) and isinstance(current_value, list):
            for item in proposed_value:
                if item not in current_value:
                    changes.append({
                        "field": field,
                        "value": str(item),
                        "justification": "inferred from profiler output (no explicit justification)",
                        "evidence_count": 1,
                        "confidence": "medium",
                    })
        elif isinstance(proposed_value, str) and field == "profile_summary":
            changes.append({
                "field": "profile_summary",
                "value": proposed_value,
                "justification": "profile_summary rewrite",
                "evidence_count": 999,
                "confidence": "high",
            })
        elif isinstance(proposed_value, dict):
            cv = current_value or {}
            for subkey, subval in proposed_value.items():
                if isinstance(subval, list):
                    current_subval = cv.get(subkey, [])
                    for item in subval:
                        if item not in current_subval:
                            changes.append({
                                "field": f"{field}.{subkey}",
                                "value": str(item),
                                "justification": "inferred from profiler output",
                                "evidence_count": 1,
                                "confidence": "medium",
                            })
    return changes


async def _run_validator(
    field: str,
    value: str,
    justification: str,
    times_seen: int,
    current_profile: dict,
) -> tuple[bool, str]:
    """
    Binary validator: should this value be added to this profile field?
    Returns (approved: bool, reasoning: str)
    Uses temperature=0.0 for consistency.
    """
    prompt = f"""A student learning profile system wants to add the following:

Field: {field}
Value to add: "{value}"
Times this pattern has been observed: {times_seen}
Justification from the profiler: "{justification}"

Current profile context:
{json.dumps({k: v for k, v in current_profile.items()
             if k not in ("profile_summary", "_proposed_changes")},
            indent=2)}

Should this value be added to {field}?

Rules for your decision:
- Common learning labels (visual learner, hands-on preference, struggles \
with abstraction): approve if justification cites a clear behavioral \
observation, even if times_seen is 1 for threshold=1 fields
- Unusual or highly specific labels: require stronger justification — \
if you would not find this in a standard learning framework, be stricter
- If value contradicts existing profile entries strongly, reject and \
explain why
- If the justification is vague ("student seemed to prefer this") without \
a specific behavioral observation, reject
- If the justification cites a specific action (asked a question, wrote \
a note, scored below threshold), approve

Return ONLY valid JSON:
{{
  "decision": "YES" or "NO",
  "reasoning": "one sentence citing the specific evidence or explaining rejection"
}}"""

    try:
        client = _get_ollama_client()
        result = client.chat_json(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            timeout_override=45,
        )
        decision = str(result.get("decision", "NO")).upper().strip()
        reasoning = result.get("reasoning", "")
        return (decision == "YES", reasoning)
    except Exception as e:
        logger.warning("Validator failed: %s", e)
        # Default to NO on failure — do not write unvalidated data
        return (False, f"validator error: {e}")


async def _validate_proposed_updates(
    student_id: str,
    proposed_updates: dict,
    current_profile: dict,
    session_id: str,
    session_type: str,
    qualifying_observation_count: int = 0,
) -> dict:
    """
    Validates proposed profile changes before writing to Django.

    Uses proposed_changes from the profiler output (with justifications)
    instead of trying to link evidence IDs post-hoc.

    Returns: validated_profile dict (safe to write to Django)
    Side effects: writes to evidence ledger (validated_updates and pending)
    """
    from services.evidence_ledger_store import get_evidence_ledger_store

    ledger_store = get_evidence_ledger_store()

    # Extract proposed changes list from profiler output
    proposed_changes = proposed_updates.pop("_proposed_changes", [])

    if not proposed_changes:
        # Profiler didn't include _proposed_changes —
        # fall back to diff-based detection
        proposed_changes = _diff_profile_updates(current_profile, proposed_updates)

    # Start with current profile as base
    # We will only add validated changes on top of it
    validated_profile = {k: v for k, v in current_profile.items()}

    # Check pending items that have now reached threshold
    ready_pending = ledger_store.get_pending_ready(student_id)
    for pending_item in ready_pending:
        # Run validator on this pending item
        approved, reasoning = await _run_validator(
            field=pending_item["field"],
            value=pending_item["value"],
            justification=pending_item["last_justification"],
            times_seen=pending_item["times_seen"],
            current_profile=current_profile,
        )
        if approved:
            _apply_single_change(
                validated_profile, pending_item["field"], pending_item["value"]
            )
            ledger_store.record_validated_update(
                student_id=student_id,
                field=pending_item["field"],
                value=pending_item["value"],
                session_id=session_id,
                session_type=session_type,
                justification=(
                    f"Graduated from pending after "
                    f"{pending_item['times_seen']} sessions: {reasoning}"
                ),
                evidence_summary=(
                    f"Seen {pending_item['times_seen']} times, "
                    f"threshold {pending_item['threshold']}"
                ),
            )
        ledger_store.remove_pending(
            student_id, pending_item["field"], pending_item["value"]
        )

    # Process new proposed changes
    for change in proposed_changes:
        field = change.get("field", "")
        value = str(change.get("value", ""))
        justification = change.get("justification", "")
        evidence_count = int(change.get("evidence_count", 0))

        if not field or not value:
            continue

        # profile_summary always passes through
        if field == "profile_summary":
            validated_profile["profile_summary"] = value
            ledger_store.record_validated_update(
                student_id=student_id,
                field="profile_summary",
                value="[rewritten]",
                session_id=session_id,
                session_type=session_type,
                justification="profile_summary always rewritten each session",
                evidence_summary="automatic",
            )
            continue

        # Check if value already in profile — always allow reinforcement
        field_base = field.split(".")[0]
        current_val = current_profile.get(field_base)
        already_present = False
        if isinstance(current_val, list) and value in current_val:
            already_present = True
        if already_present:
            # Already in profile — no need to re-validate, skip
            continue

        # Get threshold for this field
        threshold = EVIDENCE_THRESHOLDS.get(field_base, 2)

        if threshold == 0:
            # No threshold required
            _apply_single_change(validated_profile, field, value)
            ledger_store.record_validated_update(
                student_id, field, value, session_id, session_type,
                justification, f"no threshold required for {field}"
            )
            continue

        # Check if evidence_count meets threshold
        if evidence_count >= threshold:
            # Run validator
            approved, reasoning = await _run_validator(
                field=field,
                value=value,
                justification=justification,
                times_seen=evidence_count,
                current_profile=current_profile,
            )
            if approved:
                _apply_single_change(validated_profile, field, value)
                ledger_store.record_validated_update(
                    student_id, field, value, session_id, session_type,
                    justification, f"validator approved: {reasoning}"
                )
            else:
                # Validator rejected — put in pending with count reset to 1
                ledger_store.increment_pending(
                    student_id, field, value, threshold,
                    session_id, f"validator rejected: {reasoning}"
                )
        else:
            # Below threshold — increment pending counter
            ledger_store.increment_pending(
                student_id, field, value, threshold,
                session_id, justification
            )

    return validated_profile



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
- Questions the student asked (was_asked=true): topics of genuine interest or confusion
- Questions the student never asked across multiple cells on the same topic: 
  either strong confidence or active avoidance
- If a student asked 0 questions total: either very confident or disengaged

From task completion:
- Cells marked completed indicate the student attempted the task
- Incomplete task cells suggest difficulty or time constraints

OUTPUT RULES:
- Update ONLY the fields where you have clear evidence from the lab data
- For list fields (topics_of_difficulty, topics_of_strength, etc.): 
  APPEND new findings — do not replace existing values
- For profile_summary: REWRITE the full paragraph incorporating both 
  existing profile knowledge and new lab findings
- For unresolved_questions: populate with questions extracted from notes 
  (notes containing "?" or "how", "why", "what if") plus suggested 
  questions that were never asked and relate to a topic the student showed difficulty with
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

    # ── Pass 1: Evidence extraction (in-memory only, not persisted) ──
    evidence_items = await _extract_evidence(
        session_id=lab_id,
        session_type="lab_session",
        raw_data=lab_data,
    )
    qualifying_count = len(evidence_items)
    logger.info(
        "Lab profiler: %d qualifying observations extracted",
        qualifying_count,
    )

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
- POPULATE unresolved_questions from notes containing questions \
and unasked questions on difficult topics
- Return ONLY the updated profile_data JSON object

IMPORTANT — PROPOSED CHANGES TRACKING:
Return the updated profile_data JSON with one additional key:
"_proposed_changes": [
    {{
        "field": "learning_style_signals",
        "value": "prefers hands-on activities",
        "justification": "Student wrote detailed notes during task cell — direct behavioral evidence",
        "evidence_count": 1,
        "confidence": "high"
    }}
]
The _proposed_changes array must list EVERY change you are proposing \
compared to the existing profile. For list fields, list each new item \
separately. For profile_summary, list it as a single 'rewrite' entry.
This key is stripped before writing to the database — it is for validation only."""

    # ── Existing lab profiler LLM call (UNCHANGED) ──
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

        # ── Pass 3: Validation (AFTER existing profiler LLM call) ──
        validated_profile = await _validate_proposed_updates(
            student_id=student_id,
            proposed_updates=updated_profile,
            current_profile=current_profile,
            session_id=lab_id,
            session_type="lab_session",
            qualifying_observation_count=qualifying_count,
        )

        # Recover profile_summary if validator did not write it
        # (profile_summary lives outside profile_data and never passes
        # through _validate_proposed_updates — must be recovered explicitly)
        if "profile_summary" not in validated_profile:
            ps = updated_profile.get("profile_summary") or current_profile.get("profile_summary", "")
            if ps:
                validated_profile["profile_summary"] = ps

        # Patch Django profile with ONLY the validated profile
        await _patch_student_profile(student_id, validated_profile)

        return validated_profile

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
    Uses the same evidence extraction + validation pipeline as other profilers.
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

    # Build structured submission summary for the evidence extractor
    # and profiler prompt
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

    # Build raw data dict for evidence extractor
    raw_data = {
        "questions": questions_summary,
        "recurrent_mistakes_in_set": recurrent_in_set,
        "hint_3_topics": hint_3_topics,
        "no_hint_high_score_topics": no_hint_high_score_topics,
        "total_questions": len(questions_summary),
        "average_score": round(
            sum(q["final_score"] for q in questions_summary) / len(questions_summary)
        ) if questions_summary else 0,
    }

    # ── Pass 1: Evidence extraction (in-memory only) ──
    evidence_items = await _extract_evidence(
        session_id=problem_set_id,
        session_type="problem_set",
        raw_data=raw_data,
    )
    qualifying_count = len(evidence_items)
    logger.info(
        "Problem set profiler: %d qualifying observations extracted",
        qualifying_count,
    )

    # ── Pass 2: Profiler LLM ──
    current_profile = await _fetch_student_profile(student_id)

    user_prompt = f"""CURRENT STUDENT PROFILE:
{json.dumps(current_profile, indent=2)}

PROBLEM SET SUBMISSION DATA:
Total questions: {raw_data['total_questions']}
Average score: {raw_data['average_score']}
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
"_proposed_changes": [
    {{
        "field": "topics_of_difficulty",
        "value": "edge case handling",
        "justification": "Student failed edge_cases rubric category in 3/4 questions — high-confidence pattern",
        "evidence_count": 3,
        "confidence": "high"
    }}
]
The _proposed_changes array must list EVERY change you are proposing \
compared to the existing profile. For list fields, list each new item \
separately. For profile_summary, list it as a single 'rewrite' entry.
This key is stripped before writing to the database — it is for validation only."""

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

    # ── Pass 3: Validation ──
    validated_profile = await _validate_proposed_updates(
        student_id=student_id,
        proposed_updates=proposed_profile,
        current_profile=current_profile,
        session_id=problem_set_id,
        session_type="problem_set",
        qualifying_observation_count=qualifying_count,
    )

    # Recover profile_summary if validator did not write it
    if "profile_summary" not in validated_profile:
        ps = proposed_profile.get("profile_summary") or current_profile.get("profile_summary", "")
        if ps:
            validated_profile["profile_summary"] = ps

    # Write validated profile to Django
    if validated_profile:
        await _patch_student_profile(student_id, validated_profile)

    return validated_profile

