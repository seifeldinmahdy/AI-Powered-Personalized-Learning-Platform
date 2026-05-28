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
import uuid
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
    ledger_store = get_evidence_ledger_store()

    # ── Evidence extraction (BEFORE existing profiler LLM call) ──
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
    # Assign IDs and save to ledger
    for item in evidence_items:
        item["id"] = f"ev_{student_id_str}_{uuid.uuid4().hex[:8]}"
        item["session_id"] = session_id or f"session_{student_id}"
        item["session_type"] = "tutor_session"
    ledger_store.append_evidence(student_id_str, evidence_items)

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

        # ── Validation (AFTER existing profiler LLM call) ──
        proposed_profile = result.get("profile_data", {})
        current_profile = existing_profile_data or {}

        validated_profile, validated_records, pending_records = \
            await _validate_proposed_updates(
                student_id=student_id_str,
                proposed_updates=proposed_profile,
                current_profile=current_profile,
                session_id=session_id or f"session_{student_id}",
                session_type="tutor_session",
            )

        # Save ledger records
        for record in validated_records:
            ledger_store.add_validated_update(student_id_str, record)
        for record in pending_records:
            ledger_store.add_pending_observation(student_id_str, record)

        # Return ONLY the validated profile (not the raw proposed_profile)
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

# Minimum number of independent evidence items (by weighted confidence)
# required before the validator is called for a proposed change.
EVIDENCE_THRESHOLDS = {
    "learning_style_signals": 2,
    "topics_of_difficulty": 2,
    "topics_of_strength": 2,
    "recommended_approaches": 1,
    "engagement_patterns": 2,
    "notable_intentions": 1,
    "emotional_tendencies": 3,
    "unresolved_questions": 1,
    "profile_summary": 0,  # always rewrite — no threshold
}

# Confidence weight for counting evidence toward threshold
CONFIDENCE_WEIGHTS = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}


def _evidence_weight(evidence_items: list[dict]) -> float:
    """Sum the confidence weights of a list of evidence items."""
    return sum(
        CONFIDENCE_WEIGHTS.get(item.get("confidence", "low"), 0.3)
        for item in evidence_items
    )


# ── Evidence extractor (pre-profiler first pass) ────────────────

EVIDENCE_EXTRACTOR_SYSTEM = """\
You are a behavioral observation recorder. You will be given data from a 
student learning session. Your job is to extract factual behavioral 
observations — things the student actually did or said — that could be 
relevant to understanding how they learn.

CRITICAL RULES:
- Record FACTS only. Never interpret or label.
- BAD: "Student is a visual learner"
- GOOD: "Student said 'can you show me this with a diagram' after a 
  text-only explanation of recursion"
- BAD: "Student struggles with abstract concepts"  
- GOOD: "Student asked for re-explanation 3 times during the abstract 
  datastructures section"
- Each observation must be a single specific event or pattern, 
  not a general summary
- Only record observations that are clearly evidenced in the data — 
  do not infer or speculate
- Assign confidence based on explicitness:
    high: student explicitly stated something ("I learn better with visuals")
    medium: clear behavioral pattern (consistently faster on hands-on tasks)
    low: weak or ambiguous signal (single instance, could be coincidence)
- For unusual or unexpected behaviors, record them exactly as observed — 
  do not try to fit them into known learning patterns
- supports_labels should be your best guess at which profile fields this 
  observation might be relevant to — these are suggestions only, the 
  profiler decides the actual labels

Return ONLY a valid JSON array of observation objects. No markdown, 
no preamble, no explanation.

Each object:
{
  "raw_observation": str,
  "supports_labels": list[str],
  "confidence": str,
  "source": str,
  "approximate_timestamp": str
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
            questions_text = "\n".join(
                f"  [{'ASKED' if q.get('was_asked') else 'NOT ASKED'}] {q.get('question', '')}"
                for q in questions
            ) or "  No questions"
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

    return f"SESSION TYPE: {session_type}\nDATA: {json.dumps(raw_data)}"


async def _extract_evidence(
    session_id: str,
    session_type: str,
    raw_data: dict,
) -> list[dict]:
    """
    First pass: extract raw behavioral observations from session data.
    Returns a list of evidence items — facts only, no interpretations.
    Uses the generation client at temperature=0.1.
    """
    try:
        client = _get_ollama_client()
        user_msg = _build_extractor_user_message(session_type, raw_data)

        result = client.chat_json(
            messages=[
                {"role": "system", "content": EVIDENCE_EXTRACTOR_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            timeout_override=90,
        )

        # chat_json returns a dict; the extractor should return a list
        # Handle both cases: result might be {"observations": [...]} or [...]
        if isinstance(result, list):
            observations = result
        elif isinstance(result, dict):
            # Try common wrapper keys
            for key in ("observations", "items", "evidence", "data"):
                if key in result and isinstance(result[key], list):
                    observations = result[key]
                    break
            else:
                logger.warning(
                    "Evidence extractor returned dict without list key: %s",
                    list(result.keys()),
                )
                observations = []
        else:
            observations = []

        # Validate and normalize each observation
        valid = []
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            if not obs.get("raw_observation"):
                continue
            valid.append({
                "raw_observation": str(obs["raw_observation"]),
                "supports_labels": obs.get("supports_labels", []),
                "confidence": obs.get("confidence", "low"),
                "source": obs.get("source", "unknown"),
                "timestamp": obs.get("approximate_timestamp", ""),
                "used_in_profile_update": False,
            })

        logger.info(
            "evidence_extracted session_id=%s type=%s count=%d",
            session_id, session_type, len(valid),
        )
        return valid

    except Exception as e:
        logger.warning(
            "Evidence extraction failed (continuing with empty): %s", e
        )
        return []


# ── Validator (post-profiler third pass) ────────────────────────

VALIDATOR_SYSTEM = """\
You are a strict evidence evaluator for a student learning profile system. 
You will be given a proposed update to a student's profile and the evidence 
that supposedly supports it.

Your job: decide YES or NO — does the provided evidence sufficiently justify 
this specific profile update?

EVALUATION RULES:
- Common, well-understood learning science labels (visual learner, 
  hands-on preference, struggles with abstraction): require clear and 
  direct behavioral evidence. Indirect signals are acceptable if there 
  are multiple of them.
- Unusual or highly specific labels (anything you would not find in a 
  standard learning styles framework): apply STRICTER scrutiny. Unusual 
  conclusions require stronger and more explicit evidence because there 
  is no common knowledge baseline to support inference.
- A single piece of evidence is almost never sufficient unless it is 
  an explicit direct statement from the student ("I learn better when...")
- Evidence from multiple independent sources (transcript + lab notes + 
  task completion) is stronger than multiple pieces from the same source
- If the evidence is ambiguous, answer NO
- If the proposed value is already in the current profile, answer YES 
  automatically — do not block reinforcement of existing beliefs

Return ONLY valid JSON:
{
  "decision": "YES" or "NO",
  "reasoning": "One or two sentences explaining your decision, 
                citing specific evidence items",
  "evidence_ids_used": ["ev_001", "ev_002"]
}
"""


def _build_validator_message(
    change: dict,
    supporting_evidence: list[dict],
    current_profile: dict,
) -> str:
    evidence_text = "\n".join(
        f"- [{e['confidence'].upper()}] [{e.get('source', 'unknown')}] "
        f"{e['raw_observation']} (id: {e['id']})"
        for e in supporting_evidence
    ) or "No supporting evidence found"

    return f"""PROPOSED PROFILE UPDATE:
Field: {change['field']}
Proposed value to add: "{change['proposed_value']}"
Change type: {change['change_type']}

CURRENT PROFILE VALUE FOR THIS FIELD:
{json.dumps(change['current_value'], indent=2)}

SUPPORTING EVIDENCE FROM LEDGER:
{evidence_text}

Does the evidence justify adding "{change['proposed_value']}" 
to {change['field']}?"""


def _diff_profile_updates(
    current: dict,
    proposed: dict,
) -> list[dict]:
    """
    Compare proposed profile_data against current profile_data.
    Return a list of proposed changes.
    """
    changes = []
    for field, proposed_value in proposed.items():
        current_value = current.get(field)

        if isinstance(proposed_value, list) and isinstance(current_value, list):
            # Find new items
            new_items = [v for v in proposed_value if v not in current_value]
            for item in new_items:
                changes.append({
                    "field": field,
                    "change_type": "append",
                    "proposed_value": item,
                    "current_value": current_value,
                })
        elif isinstance(proposed_value, str) and field == "profile_summary":
            changes.append({
                "field": field,
                "change_type": "rewrite",
                "proposed_value": proposed_value,
                "current_value": current_value or "",
            })
        elif isinstance(proposed_value, dict):
            # For engagement_patterns, emotional_tendencies etc.
            for subkey, subval in proposed_value.items():
                if isinstance(subval, list):
                    current_subval = (current_value or {}).get(subkey, [])
                    new_subitems = [v for v in subval if v not in current_subval]
                    for item in new_subitems:
                        changes.append({
                            "field": f"{field}.{subkey}",
                            "change_type": "append",
                            "proposed_value": item,
                            "current_value": current_subval,
                        })
                else:
                    if subval != (current_value or {}).get(subkey):
                        changes.append({
                            "field": f"{field}.{subkey}",
                            "change_type": "update",
                            "proposed_value": subval,
                            "current_value": (current_value or {}).get(subkey),
                        })
    return changes


def _apply_change_to_profile(profile: dict, change: dict) -> None:
    """Apply a validated change to the profile dict in place."""
    field = change["field"]
    value = change["proposed_value"]

    if "." in field:
        # Nested field like "engagement_patterns.high"
        parent, child = field.split(".", 1)
        if parent not in profile:
            profile[parent] = {}
        if isinstance(profile[parent].get(child), list):
            if value not in profile[parent][child]:
                profile[parent][child].append(value)
        else:
            profile[parent][child] = value
    elif isinstance(profile.get(field), list):
        if value not in profile[field]:
            profile[field].append(value)
    else:
        profile[field] = value


async def _validate_proposed_updates(
    student_id: str,
    proposed_updates: dict,
    current_profile: dict,
    session_id: str,
    session_type: str,
) -> tuple[dict, list[dict], list[dict]]:
    """
    Validates each proposed change against the evidence ledger.

    Returns:
        validated_profile: dict — only validated changes, safe to write
        validated_update_records: list — records to add to validated_updates
        pending_records: list — records to add to pending_observations
    """
    from services.evidence_ledger_store import get_evidence_ledger_store

    ledger_store = get_evidence_ledger_store()

    # Start with current profile as baseline
    validated_profile = json.loads(json.dumps(current_profile)) if current_profile else {}
    validated_update_records: list[dict] = []
    pending_records: list[dict] = []

    # ── 4d: Check pending observations that may now have enough evidence ──
    try:
        ready_pending = ledger_store.get_pending_ready_for_validation(
            student_id, EVIDENCE_THRESHOLDS
        )
        for pending in ready_pending:
            supporting_evidence = ledger_store.get_evidence_for_labels(
                student_id,
                labels=[pending["proposed_label"], pending["proposed_field"]],
            )
            change_for_pending = {
                "field": pending["proposed_field"],
                "change_type": "append",
                "proposed_value": pending["proposed_label"],
                "current_value": current_profile.get(
                    pending["proposed_field"].split(".")[0], []
                ),
            }
            try:
                client = _get_ollama_client()
                validator_result = client.chat_json(
                    messages=[
                        {"role": "system", "content": VALIDATOR_SYSTEM},
                        {"role": "user", "content": _build_validator_message(
                            change_for_pending, supporting_evidence, current_profile
                        )},
                    ],
                    temperature=0.0,
                    timeout_override=60,
                )
                decision = validator_result.get("decision", "NO").upper()
                reasoning = validator_result.get("reasoning", "")
                evidence_ids_used = validator_result.get("evidence_ids_used", [])

                if decision == "YES":
                    validated_update_records.append({
                        "session_id": session_id,
                        "session_type": session_type,
                        "field": pending["proposed_field"],
                        "value_added": pending["proposed_label"],
                        "evidence_ids": evidence_ids_used,
                        "validator_reasoning": reasoning,
                        "written_at": datetime.utcnow().isoformat(),
                    })
                    _apply_change_to_profile(validated_profile, change_for_pending)
                    # Remove from pending
                    ledger_store.remove_pending_by_label(
                        student_id, pending["proposed_label"]
                    )
                    logger.info(
                        "pending_validated student=%s label=%s",
                        student_id, pending["proposed_label"],
                    )
                else:
                    # Still not enough — bump sessions_observed, leave in pending
                    logger.info(
                        "pending_still_rejected student=%s label=%s reason=%s",
                        student_id, pending["proposed_label"], reasoning,
                    )
            except Exception as e:
                logger.warning(
                    "Validator failed for pending label=%s: %s",
                    pending.get("proposed_label"), e,
                )
    except Exception as e:
        logger.warning("Failed to check pending observations: %s", e)

    # ── 4a: Diff the proposed update against current profile ──
    proposed_changes = _diff_profile_updates(current_profile, proposed_updates)

    if not proposed_changes:
        logger.info("No profile changes detected for student=%s", student_id)
        return validated_profile, validated_update_records, pending_records

    # ── 4b–4c: For each proposed change, check evidence threshold ──
    for change in proposed_changes:
        if change["field"] == "profile_summary":
            # Always allow profile_summary rewrite
            validated_profile["profile_summary"] = change["proposed_value"]
            continue

        # Find evidence that supports this proposed value
        supporting_evidence = ledger_store.get_evidence_for_labels(
            student_id,
            labels=[change["proposed_value"], change["field"]],
        )

        # Check threshold using confidence weights
        weight = _evidence_weight(supporting_evidence)
        field_base = change["field"].split(".")[0]
        threshold = EVIDENCE_THRESHOLDS.get(field_base, 2)

        if weight < threshold:
            # Below threshold — add to pending, skip validator
            pending_records.append({
                "proposed_label": change["proposed_value"],
                "proposed_field": change["field"],
                "proposed_value": change["proposed_value"],
                "evidence_ids": [e["id"] for e in supporting_evidence],
                "validator_reasoning": (
                    f"Insufficient evidence: weight {weight:.1f} < "
                    f"threshold {threshold}. "
                    f"Needs {threshold - weight:.1f} more weight."
                ),
                "sessions_observed": 1,
                "first_seen": datetime.utcnow().isoformat(),
            })
            logger.info(
                "change_pending student=%s field=%s value=%s weight=%.1f threshold=%d",
                student_id, change["field"], change["proposed_value"],
                weight, threshold,
            )
            continue

        # Above threshold — send to validator LLM
        try:
            client = _get_ollama_client()
            validator_result = client.chat_json(
                messages=[
                    {"role": "system", "content": VALIDATOR_SYSTEM},
                    {"role": "user", "content": _build_validator_message(
                        change, supporting_evidence, current_profile
                    )},
                ],
                temperature=0.0,
                timeout_override=60,
            )

            decision = validator_result.get("decision", "NO").upper()
            reasoning = validator_result.get("reasoning", "")
            evidence_ids_used = validator_result.get("evidence_ids_used", [])

            if decision == "YES":
                validated_update_records.append({
                    "session_id": session_id,
                    "session_type": session_type,
                    "field": change["field"],
                    "value_added": change["proposed_value"],
                    "evidence_ids": evidence_ids_used,
                    "validator_reasoning": reasoning,
                    "written_at": datetime.utcnow().isoformat(),
                })
                _apply_change_to_profile(validated_profile, change)
                logger.info(
                    "change_validated student=%s field=%s value=%s",
                    student_id, change["field"], change["proposed_value"],
                )
            else:
                pending_records.append({
                    "proposed_label": change["proposed_value"],
                    "proposed_field": change["field"],
                    "proposed_value": change["proposed_value"],
                    "evidence_ids": [e["id"] for e in supporting_evidence],
                    "validator_reasoning": reasoning,
                    "sessions_observed": 1,
                    "first_seen": datetime.utcnow().isoformat(),
                })
                logger.info(
                    "change_rejected student=%s field=%s value=%s reason=%s",
                    student_id, change["field"], change["proposed_value"],
                    reasoning,
                )
        except Exception as e:
            # Validator failed — default to NO
            logger.warning(
                "Validator LLM failed for field=%s: %s — defaulting to NO",
                change["field"], e,
            )
            pending_records.append({
                "proposed_label": change["proposed_value"],
                "proposed_field": change["field"],
                "proposed_value": change["proposed_value"],
                "evidence_ids": [e["id"] for e in supporting_evidence],
                "validator_reasoning": f"Validator LLM error: {e}",
                "sessions_observed": 1,
                "first_seen": datetime.utcnow().isoformat(),
            })

    logger.info(
        "validation_complete student=%s validated=%d pending=%d",
        student_id, len(validated_update_records), len(pending_records),
    )
    return validated_profile, validated_update_records, pending_records


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
    from services.evidence_ledger_store import get_evidence_ledger_store

    lab_store = get_coding_lab_store()
    ledger_store = get_evidence_ledger_store()

    # Get everything the profiler needs — this method includes timestamps
    lab_data = lab_store.get_lab_notes_for_profiler(lab_id)

    if not lab_data:
        logger.warning("Lab profiler: no lab data found for lab_id=%s", lab_id)
        return {}

    # ── Evidence extraction (BEFORE existing profiler LLM call) ──
    evidence_items = await _extract_evidence(
        session_id=lab_id,
        session_type="lab_session",
        raw_data=lab_data,
    )
    for item in evidence_items:
        item["id"] = f"ev_{student_id}_{uuid.uuid4().hex[:8]}"
        item["session_id"] = lab_id
        item["session_type"] = "lab_session"
    ledger_store.append_evidence(student_id, evidence_items)

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
- Return ONLY the updated profile_data JSON object"""

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

        # ── Validation (AFTER existing profiler LLM call) ──
        validated_profile, validated_records, pending_records = \
            await _validate_proposed_updates(
                student_id=student_id,
                proposed_updates=updated_profile,
                current_profile=current_profile,
                session_id=lab_id,
                session_type="lab_session",
            )

        # Save ledger records
        for record in validated_records:
            ledger_store.add_validated_update(student_id, record)
        for record in pending_records:
            ledger_store.add_pending_observation(student_id, record)

        # Patch Django profile with ONLY the validated profile
        await _patch_student_profile(student_id, validated_profile)

        return validated_profile

    except Exception as e:
        logger.error("Lab profiler failed for lab_id=%s: %s", lab_id, e)
        return current_profile

