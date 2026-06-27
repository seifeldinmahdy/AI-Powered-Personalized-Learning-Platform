"""
Profiler Service — claims-based learning-profile updates + emotion fusion.

Three profilers (session / lab / problem_set) each emit STRUCTURED CLAIMS
validated against the v2 schema (schemas/profile.py) and send them to the ONE
server-side writer (Django /progress/profile/apply). No profiler rewrites the
profile or merges client-side; collisions resolve by provenance + confidence.

Authority hierarchy (authority ∝ evidence quality):
  - Mastery model (separate) owns ALL concept-competence. Profilers never assert it.
  - problem_set (medium): PROCESS signals from graded work.
  - session (medium): engagement/emotion/pace/unresolved from the DURABLE log.
  - lab (junior, most conservative): positive-action-only; ignores unasked
    questions entirely; declines below an evidence floor; everything low-confidence.
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

from schemas.profile import (  # noqa: E402
    validate_claims, NON_INFERENCE_FIELDS, LAB_MAX_CONFIDENCE,
)

# ── OllamaClient (shared LLM backend) ──
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore  # noqa: E402

DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")

_ollama_client: OllamaClient | None = None


def _get_ollama_client() -> OllamaClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST"),
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=120,
        )
    return _ollama_client


def _clean_llm_json(text: str) -> str:
    """Strip markdown fences and any non-JSON text around the JSON object."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()
    first = text.find("{")
    if first > 0:
        text = text[first:]
    last = text.rfind("}")
    if last >= 0 and last < len(text) - 1:
        text = text[: last + 1]
    return text


def _parse_llm_json(text: str, context: str = "LLM") -> dict:
    cleaned = _clean_llm_json(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("[%s] JSON parse failed: %s", context, e)
        raise


# ── Shared claims contract (baked into every profiler prompt) ────────

_CLAIMS_CONTRACT = """\
Return ONLY raw JSON: {"claims": [ {"field": ..., "value": ..., "evidence": ..., "confidence": 0.0-1.0}, ... ]}.
ALLOWED fields (and NOTHING else): pace, preferred_modality, engagement,
emotional_tendencies, recurrent_process_mistake, unresolved_question,
recommended_approach, neutral_context.

HARD RULES:
- NEVER claim concept competence (what the student knows / is weak at / strong at /
  topics of difficulty or strength). That is owned by a separate mastery model.
  There is no field for it; do not invent one.
- recurrent_process_mistake = a SPECIFIC behavioural pattern ("off-by-one in loop
  bounds", "forgets to handle empty input"), never a rubric category or topic name.
- Each claim must cite concrete evidence in its "evidence" field.
- confidence reflects how strongly the evidence supports the claim.
"""

SESSION_CLAIMS_SYSTEM = (
    "You are an educational psychologist analysing a tutoring session log "
    "(per-slide: dominant/observed emotions, time spent, questions the student "
    "asked, tutor responses). Produce claims about HOW the student learns: pace, "
    "preferred_modality, engagement, emotional_tendencies, unresolved_question "
    "(the student's OWN questions), recommended_approach.\n"
    "The emotion label 'uncertain' means the recognizer could not classify the "
    "face — treat it as MISSING DATA, never as student confusion.\n\n"
    + _CLAIMS_CONTRACT +
    '\nAlso return a "summary" string: one concise paragraph (max 5 sentences), a '
    "note from one teacher to another on how to teach this student."
)

PROBLEM_SET_CLAIMS_SYSTEM = (
    "You are a learning analyst reading a student's GRADED problem-set results "
    "(per-question rubric breakdown, hint usage, scores, mistake tags). This is "
    "high-confidence objective behavioural data. Produce PROCESS claims only: "
    "recurrent_process_mistake (specific behaviours, not rubric categories), "
    "recommended_approach, pace, engagement.\n\n"
    + _CLAIMS_CONTRACT
)

LAB_CLAIMS_SYSTEM = (
    "You are a CONSERVATIVE junior learning analyst reading a lab session. Only "
    "POSITIVE actions are evidence: notes the student WROTE, questions the student "
    "ASKED, code RUN, tasks ATTEMPTED.\n"
    "CRITICAL: suggested questions the student did NOT ask are NOT evidence — you "
    "are not even shown them. Absence of action is never a trait, strength, "
    "weakness, or inference.\n"
    "unresolved_question may ONLY come from the student's OWN notes containing a "
    "question mark or 'how/why/what if'. Everything you emit is LOW confidence "
    f"(≤ {LAB_MAX_CONFIDENCE}).\n\n"
    + _CLAIMS_CONTRACT
)


# ── Audit log (best-effort) ──────────────────────────────────────────

_AUDIT_DIR = Path(__file__).resolve().parent.parent / "data" / "profile_audit"


def _use_pg_audit() -> bool:
    """Whether the shared Supabase/Postgres audit backend is selected.

    Explicit opt-in (default = local JSON files), reversible via env:
    ``PROFILE_AUDIT_BACKEND=supabase`` / ``postgres`` / ``pg``. Reuses the
    SUPABASE_DB_URL of the corpus/plan/context stores.
    """
    return os.getenv("PROFILE_AUDIT_BACKEND", "").strip().lower() in (
        "supabase", "postgres", "pg", "pgvector"
    )


_pg_audit_store = None


def _get_pg_audit_store():
    global _pg_audit_store
    if _pg_audit_store is None:
        from services.pg_profile_audit_store import PgProfileAuditStore
        _pg_audit_store = PgProfileAuditStore()
    return _pg_audit_store


def _write_audit_entry(student_id, session_id, session_type, claims, summary=""):
    # Serialize claims once (Pydantic models → dicts) for whichever backend.
    serial_claims = [c.model_dump() if hasattr(c, "model_dump") else c for c in claims]

    if _use_pg_audit():
        try:
            _get_pg_audit_store().write_entry(
                str(student_id), str(session_id), session_type,
                serial_claims, (summary or "")[:300],
            )
        except Exception as e:
            logger.warning("Audit log (pg) write failed for student %s: %s", student_id, e)
        return

    try:
        safe_id = str(student_id).replace("/", "_").replace("\\", "_").replace(":", "_")
        audit_dir = _AUDIT_DIR / safe_id
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / "audit.json"
        entries = []
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
            "summary_written": (summary or "")[:300],
            "claims": serial_claims,
        })
        if len(entries) > 500:
            entries = entries[-500:]
        audit_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("Audit log write failed for student %s: %s", student_id, e)


def get_audit_log(student_id: str, limit: int = 20) -> list[dict]:
    if _use_pg_audit():
        try:
            return _get_pg_audit_store().get_log(str(student_id), limit=limit)
        except Exception:
            return []
    try:
        safe_id = str(student_id).replace("/", "_").replace("\\", "_").replace(":", "_")
        audit_path = _AUDIT_DIR / safe_id / "audit.json"
        if not audit_path.exists():
            return []
        entries = json.loads(audit_path.read_text(encoding="utf-8"))
        return entries[-limit:] if isinstance(entries, list) else []
    except Exception:
        return []


# ── The single writer client (all profilers go through here) ─────────

async def post_profile_claims(student_id, claims, summary=None, summary_source=None) -> bool:
    """Send validated claims to the ONE server-side writer (/progress/profile/apply).

    No client-side merge/overwrite — the Django writer applies them additively
    with provenance-based resolution under a row lock.

    Returns True iff the derived profile was DURABLY written (HTTP 200/201) — or
    there was nothing to persist. Returns False on a failed/errored write. This
    confirmation is the gate for purging the raw session events (step 2): raw
    events are only deleted once their derived value is known to be in Django.
    """
    payload_claims = [c.model_dump() if hasattr(c, "model_dump") else c for c in (claims or [])]
    if not payload_claims and summary is None:
        return True  # nothing to persist → vacuously confirmed
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    body: dict = {"claims": payload_claims}
    if summary is not None:
        body["summary"] = summary
        body["summary_source"] = summary_source
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{DJANGO_API_URL}/progress/profile/apply/",
                json=body,
                headers={"X-Student-ID": str(student_id), "X-Service-Key": service_key},
            )
            if resp.status_code in (200, 201):
                return True
            logger.warning("profile/apply returned %d for student %s", resp.status_code, student_id)
            return False
    except Exception as e:
        logger.warning("Could not POST profile claims for student %s: %s", student_id, e)
        return False


# ── Emotion fusion (unchanged) ───────────────────────────────────────

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
    """Resolve conflicting FER and SER emotions. Returns { fused_emotion, reasoning }."""
    api_key = os.getenv("OLLAMA_API_KEY", "")
    if not api_key:
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
        return client.chat_json(
            messages=[
                {"role": "system", "content": FUSION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            timeout_override=30,
        )
    except json.JSONDecodeError:
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "LLM returned invalid JSON — used FER"}
        return {"fused_emotion": ser_emotion, "reasoning": "LLM returned invalid JSON — used SER"}
    except Exception as e:
        logger.warning("Emotion fusion LLM failed, falling back to confidence: %s", e)
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "LLM failed — used FER"}
        return {"fused_emotion": ser_emotion, "reasoning": "LLM failed — used SER"}


# ── Django profile fetch (read-only context for prompts) ─────────────

async def _fetch_student_profile(student_id: str) -> dict:
    """Fetch the student's profile_data from Django (read-only, for prompt context)."""
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{DJANGO_API_URL}/progress/learning-profile/",
                headers={"X-Student-ID": str(student_id), "X-Service-Key": service_key},
            )
            if response.status_code == 200:
                return response.json().get("profile_data", {})
    except Exception as e:
        logger.warning("profiler: could not fetch student profile: %s", e)
    return {}


# ── Session profiler: consolidate from the DURABLE log (idempotent) ──

def _consolidate_log_by_slide(events: list[dict]) -> list[dict]:
    """Group durable session events into one entry per slide for the LLM."""
    import collections
    slides: dict[int, dict] = {}

    def _init(idx):
        return {"slide_index": idx, "slide_title": "", "slide_content": "",
                "all_emotions": [], "student_questions": [], "tutor_responses": [],
                "notable_events": [], "time_spent_seconds": 0.0}

    for ev in events:
        p = ev.get("payload", {})
        etype = ev.get("event_type")
        idx = int(p.get("slide_index", 0) or 0)
        entry = slides.setdefault(idx, _init(idx))
        if p.get("slide_title") and not entry["slide_title"]:
            entry["slide_title"] = p["slide_title"]
        if p.get("slide_content") and not entry["slide_content"]:
            entry["slide_content"] = p["slide_content"]
        if etype == "emotion":
            fused = p.get("fused_emotion")
            if fused:
                entry["all_emotions"].append(fused)
            qt = p.get("question_transcript")
            if qt:
                entry["student_questions"].append(qt)
        elif etype == "tutor_event":
            text = p.get("learnpal_response_summary") or p.get("text", "")
            if text:
                entry["tutor_responses"].append(text)
            et = p.get("event_type", "")
            if et and et != "passive":
                entry["notable_events"].append(et)
            qt = p.get("question_transcript")
            if qt:
                entry["student_questions"].append(qt)
        elif etype == "time_spent":
            for k, v in (p.get("updates") or {}).items():
                if str(k) == str(idx):
                    entry["time_spent_seconds"] += float(v)

    for entry in slides.values():
        if entry["all_emotions"]:
            entry["dominant_emotion"] = collections.Counter(entry["all_emotions"]).most_common(1)[0][0]
        else:
            entry["dominant_emotion"] = "neutral"

    result = [e for e in slides.values()
              if e["all_emotions"] or e["student_questions"] or e["tutor_responses"]]
    result.sort(key=lambda e: e["slide_index"])
    return result


def _consolidate_checkpoints(events: list[dict]) -> list[dict]:
    """Compact summary of in-session MCQ checkpoints for the profiler prompt.

    Checkpoint events aren't slide-indexed, so they fall outside the per-slide
    consolidation. A low score or a long ``missed`` list signals concepts the
    student couldn't recall under testing — strong evidence for difficulty
    claims the session profiler would otherwise never see.
    """
    out: list[dict] = []
    for ev in events:
        if ev.get("event_type") != "checkpoint":
            continue
        p = ev.get("payload", {})
        out.append({
            "checkpoint_index": p.get("checkpoint_index"),
            "score": p.get("score"),
            "correct": p.get("correct_count"),
            "total": p.get("total_count"),
            "missed": [
                {"topic": m.get("topic", ""), "question": m.get("question", ""),
                 "correct_answer": m.get("correct_answer", "")}
                for m in (p.get("mistakes") or [])
            ],
        })
    return out


async def run_session_profiler(session_id: str, student_id: str, lesson_title: str = "") -> dict:
    """Consolidate a session's DURABLE log into claims (idempotent).

    Reads UNCONSUMED events from the durable log, produces session claims +
    summary, applies them via the single writer, then marks the events consumed.
    Safe to call from both the explicit session-end and the sweeper: a re-run
    finds no unconsumed events and applies nothing (no duplicates).
    """
    from services.session_event_log import get_session_event_log
    elog = get_session_event_log()
    events = elog.read_unconsumed(session_id)
    if not events:
        logger.info("session profiler: no unconsumed events for session %s", session_id)
        return {"claims": 0, "consumed": 0}

    # Abandoned-session sweep passes no student_id — derive it from the events
    # (each carries the student it belongs to) so the consolidation isn't lost.
    if not student_id:
        student_id = next((e.get("student_id") for e in events if e.get("student_id")), "")

    max_id = max(e["id"] for e in events)
    by_slide = _consolidate_log_by_slide(events)
    checkpoints = _consolidate_checkpoints(events)

    claims = []
    summary = None
    if (by_slide or checkpoints) and os.getenv("OLLAMA_API_KEY", ""):
        user_prompt = (
            f"Lesson: {lesson_title}\n\nSESSION LOG (per slide):\n"
            f"{json.dumps(by_slide, indent=2)}"
        )
        if checkpoints:
            user_prompt += (
                "\n\nIN-SESSION MCQ CHECKPOINTS (a low score or items under "
                "'missed' = concepts the student struggled to recall under "
                "testing — weigh these for topics_of_difficulty claims):\n"
                f"{json.dumps(checkpoints, indent=2)}"
            )
        try:
            client = _get_ollama_client()
            raw = client.chat_json(
                messages=[
                    {"role": "system", "content": SESSION_CLAIMS_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3, timeout_override=120,
            )
            claims = validate_claims(raw.get("claims", []), source="session")
            summary = raw.get("summary") or None
        except Exception as e:
            logger.error("session profiler LLM failed for session %s: %s", session_id, e)

    confirmed = await post_profile_claims(
        student_id, claims, summary=summary, summary_source="session"
    )
    _write_audit_entry(student_id, session_id, "session", claims, summary or "")

    # Idempotency marker: consume what we just folded.
    elog.mark_consumed(session_id, max_id)
    # Retention boundary. Default (flag OFF): purge only RAW emotion — the
    # derived low-confidence claim is kept, no biometric retained (Batch 11b).
    # Step 2 (flag ON) AND only once the Django profile write is CONFIRMED:
    # purge ALL of the session's consumed events (slide/tutor too), since their
    # derived value is now durably in Django and they would otherwise accumulate.
    # If the write is NOT confirmed we still drop raw emotion but KEEP the rest,
    # so nothing is deleted before its value is known to have landed.
    from services.session_event_log import purge_on_consolidation
    try:
        if purge_on_consolidation() and confirmed:
            purged = elog.purge_consumed_session(session_id)
            if purged:
                logger.info("session profiler: purged %d consumed rows session=%s", purged, session_id)
        else:
            purged = elog.purge_consumed_emotion(session_id)
            if purged:
                logger.info("session profiler: purged %d raw emotion rows session=%s", purged, session_id)
    except Exception:
        logger.warning("session profiler: consumed purge failed session=%s", session_id)
    logger.info("session profiler: session=%s claims=%d consumed<=%d confirmed=%s",
                session_id, len(claims), max_id, confirmed)
    return {"claims": len(claims), "consumed": max_id}


async def purge_emotion_retention(ttl_seconds: int) -> dict:
    """Retention sweep for ABANDONED sessions (Batch 11b).

    CONSOLIDATE BEFORE PURGE — so an abandoned session never loses its partial
    profile to the retention purge:
      1. Consolidate sessions with unconsumed events older than the TTL (runs the
         profiler → writes the derived claim → purges that session's raw emotion).
      2. TTL backstop: delete any remaining CONSUMED emotion older than the cutoff.
    The backstop only touches consumed rows, so it can never race the profiler.
    """
    from datetime import datetime, timedelta, timezone as _tz
    elog = get_session_event_log()
    cutoff = (datetime.now(_tz.utc) - timedelta(seconds=int(ttl_seconds))).isoformat()

    consolidated = 0
    for sid in elog.sessions_with_unconsumed(older_than_iso=cutoff):
        try:
            await run_session_profiler(sid, student_id="", lesson_title="")
            consolidated += 1
        except Exception:
            logger.warning("retention sweep: consolidation failed session=%s", sid)
    # TTL backstop. Default (flag OFF): emotion-only (current behavior). Step 2
    # (flag ON): drop ALL consumed events older than the cutoff. Only consumed
    # rows are eligible either way, so this can never race the profiler.
    from services.session_event_log import purge_on_consolidation
    if purge_on_consolidation():
        purged = elog.purge_consumed_older_than(cutoff)
    else:
        purged = elog.purge_emotion_older_than(cutoff)
    logger.info("retention sweep: consolidated=%d purged=%d", consolidated, purged)
    return {"consolidated": consolidated, "purged": purged}


# ── Lab profiler: positive-action-only, evidence floor, low confidence ──

def _positive_signal_score(lab_data: dict) -> tuple[int, int]:
    """Return (positive_signal_count, available_unasked_count) from lab data.

    Positive signal = written notes + ASKED questions. Unasked questions are NOT
    counted as signal (and never fed to the LLM).
    """
    positive = 0
    unasked = 0
    positive += len(lab_data.get("general_notes", []) or [])
    for cell in lab_data.get("cells", []):
        positive += len([n for n in (cell.get("student_notes") or []) if (n.get("content") or "").strip()])
        for q in cell.get("suggested_questions", []) or []:
            if q.get("was_asked"):
                positive += 1
            else:
                unasked += 1
        if cell.get("completed") or cell.get("attempted"):
            positive += 1
    return positive, unasked


async def run_lab_profiler(student_id: str, lab_id: str, course_id: str, lesson_id: str) -> dict:
    """Lab profiler — junior/conservative. Positive actions only; declines on no signal."""
    # Read the DURABLE lab artifact from Django (StudentArtifact type=lab); the
    # on-disk lab_store was retired with the artifact-backbone migration.
    from services.lab_service import _get_lab_artifact
    artifact = await _get_lab_artifact(str(student_id), str(course_id), str(lesson_id))
    content_json = (artifact or {}).get("content_json") if artifact else None
    if not content_json:
        logger.warning(
            "Lab profiler: no lab artifact for student=%s course=%s lesson=%s",
            student_id, course_id, lesson_id,
        )
        return {"claims": 0, "declined": True}
    lab = content_json.get("lab", {}) or {}
    lab_data = {
        "general_notes": lab.get("general_notes", []) or [],
        "cells": lab.get("cells", []) or [],
    }

    positive, unasked = _positive_signal_score(lab_data)

    # EVIDENCE FLOOR: near-zero positive signal → decline rather than hallucinate.
    if positive == 0:
        logger.info("Lab profiler: evidence floor — no positive signal for lab %s; declining.", lab_id)
        return {"claims": 0, "declined": True}

    # Build the prompt with POSITIVE actions ONLY — unasked questions are stripped.
    def _fmt_notes(notes):
        out = [f"  - {n.get('content','').strip()}" for n in (notes or []) if (n.get("content") or "").strip()]
        return "\n".join(out) if out else "  (none)"

    cells_summary = []
    for cell in lab_data.get("cells", []):
        asked = [q.get("question", "") for q in cell.get("suggested_questions", []) or [] if q.get("was_asked")]
        cells_summary.append(
            f"Cell: {cell.get('title','Untitled')} (type: {cell.get('cell_type','unknown')})\n"
            f"Notes:\n{_fmt_notes(cell.get('student_notes'))}\n"
            f"Questions the student ASKED:\n"
            + ("\n".join(f"  - {q}" for q in asked) if asked else "  (none)")
        )

    user_prompt = (
        "LAB POSITIVE SIGNAL ONLY (unasked suggested questions are intentionally omitted).\n\n"
        f"General notes written by the student:\n{_fmt_notes(lab_data.get('general_notes'))}\n\n"
        f"Per-cell:\n{chr(10).join(cells_summary)}\n\n"
        "Produce low-confidence claims from these POSITIVE actions only."
    )

    claims = []
    if os.getenv("OLLAMA_API_KEY", ""):
        try:
            client = _get_ollama_client()
            raw = client.chat_json(
                messages=[
                    {"role": "system", "content": LAB_CLAIMS_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2, timeout_override=120,
            )
            claims = validate_claims(raw.get("claims", []), source="lab")
        except Exception as e:
            logger.error("Lab profiler LLM failed for lab %s: %s", lab_id, e)
            return {"claims": 0, "error": True}

    # Drop any inference the model tried to draw that references unasked questions
    # (defense-in-depth beyond stripping them from the prompt): keep only fields
    # in remit; neutral_context for the available-but-unasked count is the only
    # place ignores may be MENTIONED — never as a trait.
    from schemas.profile import Claim
    if unasked:
        claims.append(Claim(
            field="neutral_context",
            value=f"{unasked} suggested question(s) were available but not asked (no inference drawn).",
            source="lab", evidence="lab suggested-question availability",
            confidence=0.1,
        ))

    await post_profile_claims(student_id, claims)
    _write_audit_entry(student_id, lab_id, "lab", claims, "")
    logger.info("Lab profiler: lab=%s positive=%d unasked=%d claims=%d", lab_id, positive, unasked, len(claims))
    return {"claims": len(claims), "positive_signal": positive}


# ── Problem-set profiler: PROCESS claims from graded work ────────────

async def run_problem_set_profiler(student_id: str, problem_set_id: str, lesson_id: str) -> dict:
    """Problem-set profiler — process signals from graded work (no competence)."""
    # Read the DURABLE problem set + append-only attempts from Django; the on-disk
    # problem_set_store was retired with the artifact-backbone migration.
    from services import artifact_client
    from collections import Counter

    raw_ps = await artifact_client.get_problem_set(str(student_id), problem_set_id)
    if not raw_ps:
        logger.warning("Problem set profiler: no problem set id=%s", problem_set_id)
        return {"claims": 0}

    content = raw_ps.get("content_json") or {}
    questions = content.get("questions", []) or []
    # Latest attempt per question (attempts are chronologically ordered).
    latest_attempt: dict[str, dict] = {}
    for att in raw_ps.get("attempts", []) or []:
        qid = att.get("question_id")
        if qid:
            latest_attempt[qid] = att

    questions_summary = []
    all_mistake_tags = []
    hint_3 = 0
    for question in questions:
        qid = question.get("id", "") if isinstance(question, dict) else getattr(question, "id", "")
        att = latest_attempt.get(qid)
        if not att:
            continue
        evaluated = att.get("evaluated_rubric", []) or []
        final_score = att.get("score", 0)
        hints_used = att.get("hints_used", 0)
        # Derive process signals from the stored binary rubric — the SAME
        # derivation evaluate_submission uses (failed-check categories + their
        # evidence). The attempt row stores the evaluated rubric, not these.
        mistake_tags = sorted({
            crit.get("category", "")
            for crit in evaluated
            for check in (crit.get("checks", []) or [])
            if check.get("result") is False and crit.get("category")
        })
        failed_evidence = [
            check.get("evidence", "")
            for crit in evaluated
            for check in (crit.get("checks", []) or [])
            if check.get("result") is False and check.get("evidence")
        ][:3]
        all_mistake_tags.extend(mistake_tags)
        if hints_used >= 3:
            hint_3 += 1
        questions_summary.append({
            "final_score": final_score, "hints_used": hints_used,
            "mistake_tags": mistake_tags,
            "failed_evidence": failed_evidence,
        })

    if not questions_summary:
        logger.warning("Problem set profiler: no submissions for %s", problem_set_id)
        return {"claims": 0}

    recurrent = [t for t, c in Counter(all_mistake_tags).items() if c >= 2]
    avg = round(sum(q["final_score"] for q in questions_summary) / len(questions_summary))

    user_prompt = (
        f"PROBLEM SET RESULTS: {len(questions_summary)} questions, avg score {avg}.\n"
        f"Recurrent mistake tags (≥2 questions): {recurrent}\n"
        f"Questions needing the most direct hint: {hint_3}\n\n"
        f"Per-question:\n{json.dumps(questions_summary, indent=2)}\n\n"
        "Produce PROCESS claims (recurrent_process_mistake, recommended_approach, "
        "pace, engagement). No concept competence."
    )

    claims = []
    if os.getenv("OLLAMA_API_KEY", ""):
        try:
            client = _get_ollama_client()
            raw = client.chat_json(
                messages=[
                    {"role": "system", "content": PROBLEM_SET_CLAIMS_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2, timeout_override=120,
            )
            claims = validate_claims(raw.get("claims", []), source="problem_set")
        except Exception as e:
            logger.error("Problem set profiler LLM failed for %s: %s", problem_set_id, e)
            return {"claims": 0, "error": True}

    await post_profile_claims(student_id, claims)
    _write_audit_entry(student_id, problem_set_id, "problem_set", claims, "")
    logger.info("Problem set profiler: ps=%s claims=%d", problem_set_id, len(claims))
    return {"claims": len(claims)}
