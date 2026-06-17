"""
OllamaClient-powered coding lab generation.

The generator intentionally runs in two steps:
1. Build a checklist from session context, tutor transcript, slides, and profile.
2. Generate a notebook-style lab that satisfies that checklist.
"""

from __future__ import annotations

import datetime as _dt
import base64
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

from dotenv import load_dotenv

from schemas.coding import (
    CodingLab,
    CodingLabGenerateRequest,
    CodingLabGenerateResponse,
    CodingLabRunResponse,
    LabCell,
    LabChecklistItem,
)
from services.lab_store import get_coding_lab_store
from services.session_store import get_session_store

logger = logging.getLogger(__name__)

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
            host=os.getenv("OLLAMA_HOST"),
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=120,
        )
    return _ollama_client


DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text).strip()

    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last >= first:
        return text[first : last + 1]
    return text


def _chat_json(messages: list[dict[str, str]], temperature: float, max_tokens: int) -> dict:
    api_key = os.getenv("OLLAMA_API_KEY", "")
    if not api_key:
        raise RuntimeError("OLLAMA_API_KEY is not configured")

    client = _get_ollama_client()
    try:
        return client.chat_json(
            messages=messages,
            temperature=temperature,
            timeout_override=180,
        )
    except Exception as exc:
        logger.warning("lab_model_failed error=%s", exc)
        raise


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
        logger.warning("lab_service: could not fetch student profile: %s", e)
    return {}


def _extract_relevant_profile_context(
    profile_data: dict,
    topic: str = "",
) -> str:
    """
    Extract a compact, prompt-ready profile summary from the v2 claims schema.
    HOW-to-learn only (pace, modality, approaches, unresolved questions).
    COMPETENCE (what the student struggles with) is owned by the mastery model
    and is NOT read from the profile here.
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


def _generate_suggested_questions(
    cells: list,
    topic: str,
    profile_context: str,
) -> list:
    """
    For each cell, generate up to 3 relevant questions a student might have.
    Returns the cells list with suggested_questions populated.
    """
    system = (
        "You are an expert CS instructor anticipating student questions.\n"
        "For each lab cell provided, generate exactly 3 questions that a student "
        "working through this material would likely want to ask.\n\n"
        "Question types to include per cell (mix them):\n"
        "- Conceptual: \"Why does X work this way?\"\n"
        "- Practical: \"When would I actually use this in real code?\"\n"
        "- Clarifying: \"What happens if I do Y instead of Z?\"\n"
        "- Edge case: \"What if the input is empty/zero/negative?\"\n"
        "- Connection: \"How does this relate to [concept from earlier cell]?\"\n\n"
        "Rules:\n"
        "- Questions must be specific to THIS cell's content — not generic\n"
        "- Do not generate questions that are already answered by the cell text\n"
        "- If the student profile shows difficulty with certain topics, include "
        "questions that directly address those confusion points for relevant cells\n"
        "- Return ONLY valid JSON — no markdown fences, no preamble\n\n"
        'Output format:\n'
        '[\n  {"cell_id": "the cell id", "questions": ["question 1", ...]},\n  ...\n]'
    )
    cells_summary = []
    for cell in cells:
        cell_dict = cell.model_dump() if hasattr(cell, "model_dump") else cell
        cells_summary.append({
            "cell_id": cell_dict.get("id", ""),
            "cell_type": cell_dict.get("cell_type", ""),
            "title": cell_dict.get("title", ""),
            "content_summary": (cell_dict.get("narrative") or "")[:200],
        })

    user = (
        f"TOPIC: {topic}\n\n"
        f"STUDENT PROFILE CONTEXT:\n{profile_context}\n\n"
        f"CELLS:\n{json.dumps(cells_summary, indent=2)}"
    )

    try:
        client = _get_ollama_client()
        raw = client.chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
            timeout_override=120,
        )
        # raw could be a list directly or wrapped
        if isinstance(raw, dict) and not isinstance(raw, list):
            # Try to find the list in the dict
            for key, val in raw.items():
                if isinstance(val, list):
                    raw = val
                    break
            else:
                raw = []
        if not isinstance(raw, list):
            raw = []

        # Match by cell_id and populate
        q_map: dict[str, list[str]] = {}
        for entry in raw:
            if isinstance(entry, dict):
                cid = entry.get("cell_id", "")
                qs = entry.get("questions", [])
                if cid and isinstance(qs, list):
                    q_map[cid] = [str(q) for q in qs[:3]]

        for cell in cells:
            cell_id = cell.id if hasattr(cell, "id") else cell.get("id", "")
            questions = q_map.get(cell_id, [])
            sq = [{"question": q, "was_asked": False} for q in questions]
            if hasattr(cell, "suggested_questions"):
                cell.suggested_questions = sq
            elif isinstance(cell, dict):
                cell["suggested_questions"] = sq

        logger.info("suggested_questions_generated cells=%d questions_mapped=%d", len(cells), len(q_map))
    except Exception as exc:
        logger.warning("suggested_questions_failed: %s — continuing with empty questions", exc)

    return cells


def _session_context(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {}
    try:
        data = get_session_store().get_session(session_id)
        if data is None:
            return {}
        return {
            "current_topic": data.live.current_topic,
            "current_subtopic": data.live.current_subtopic,
            "running_summary": data.live.running_summary,
            "tutor_transcript": data.live.tutor_transcript[-10:],
            "visited_slides": data.live.visited_slides,
            "emotion_signals": data.live.emotion_signals[-8:],
            "student_profile_summary": data.profile.student_profile_summary,
        }
    except Exception as exc:
        logger.warning("lab_session_context_unavailable session_id=%s error=%s", session_id, exc)
        return {}


def _slides_summary(request: CodingLabGenerateRequest) -> list[dict[str, str]]:
    summary = []
    for slide in request.slides[:10]:
        content = slide.content.strip()
        if len(content) > 900:
            content = content[:900] + "..."
        summary.append({
            "title": slide.title.strip(),
            "content": content,
            "code": slide.code.strip()[:900],
        })
    return summary


def _fallback_checklist(request: CodingLabGenerateRequest, session: dict[str, Any]) -> list[LabChecklistItem]:
    topic = request.lesson_title or session.get("current_topic") or "the lesson"
    return [
        LabChecklistItem(id="C1", item=f"Review the core idea of {topic} in plain language.", reason="Connect the lab to the completed lesson."),
        LabChecklistItem(id="C2", item="Include one runnable Python example with comments.", reason="Bridge concept understanding to syntax."),
        LabChecklistItem(id="C3", item="Add at least two hands-on tasks that require editing code.", reason="Make the student practice implementation before assessment."),
        LabChecklistItem(id="C4", item="Provide progressive tips for each task.", reason="Let the tutor help without giving away the full answer."),
    ]


def _fallback_lab(request: CodingLabGenerateRequest, checklist: list[LabChecklistItem]) -> CodingLab:
    title = request.lesson_title or "Session Lab"
    return CodingLab(
        title=f"{title}: Coding Lab",
        intro=(
            "This lab turns the session ideas into Python practice. Read each "
            "cell, run through the example mentally, then complete the tasks."
        ),
        estimated_minutes=15,
        tutor_opening="I will walk through the lab one cell at a time, then I want you to try the tasks yourself.",
        cells=[
            LabCell(
                id="cell-1",
                cell_type="explanation",
                title="Concept recap",
                narrative=f"In the session, you studied {title}. The goal now is to turn that idea into code you can write from memory.",
                tutor_script=f"Start here: connect {title} to a concrete Python pattern before writing new code.",
                tips=["Focus on the input, the transformation, and the output."],
            ),
            LabCell(
                id="cell-2",
                cell_type="code",
                title="Worked example",
                narrative="Use a small function and a test call to see the pattern clearly.",
                code='def describe_value(value):\n    """Return a short label for a value."""\n    if value > 0:\n        return "positive"\n    if value < 0:\n        return "negative"\n    return "zero"\n\nprint(describe_value(3))',
                expected_output="positive",
                tutor_script="Notice the function shape: define, decide with conditionals, return one clear result.",
                tips=["Trace the example with one input before changing it."],
            ),
            LabCell(
                id="task-1",
                cell_type="task",
                title="Task 1: Complete the function",
                task_prompt=f"Write a small function that demonstrates one idea from {title}.",
                starter_code='def practice_concept(items):\n    """Return a useful result from items."""\n    # TODO: implement this using the session idea\n    pass',
                success_criteria=[
                    "The function returns a value instead of printing only.",
                    "The code uses a loop, conditional, or expression from the session.",
                    "You can explain why your implementation works.",
                ],
                tutor_script="Try this one yourself. Keep the function small and make the return value obvious.",
                tips=[
                    "Start by writing the expected input and output in a comment.",
                    "Solve the simplest case first.",
                    "Test with at least two different inputs.",
                ],
            ),
            LabCell(
                id="task-2",
                cell_type="task",
                title="Task 2: Add a second test case",
                task_prompt="Add a second example call that proves your function handles a different case.",
                starter_code="# Add your second test call here\n# print(practice_concept(...))",
                success_criteria=[
                    "The test uses a different input shape or edge case.",
                    "The expected result is clear.",
                ],
                tutor_script="Good practice means testing the idea, not just writing it once.",
                tips=[
                    "Try an empty list, a zero value, or a repeated item if it fits.",
                    "Say the expected answer before running or checking the code.",
                ],
            ),
        ],
        completion_message="Nice work. You practiced the concept and syntax, so now the coding question can test implementation.",
    )


def _build_payload(request: CodingLabGenerateRequest, session: dict[str, Any]) -> dict[str, Any]:
    return {
        "lesson_title": request.lesson_title,
        "student_profile_summary": request.student_profile_summary or session.get("student_profile_summary", ""),
        "session_context": session,
        "slides": _slides_summary(request),
    }


def _generate_checklist(
    request: CodingLabGenerateRequest,
    session: dict[str, Any],
    profile_context: str = "",
) -> list[LabChecklistItem]:
    system = (
        "You design personalized programming labs after an AI tutoring session. "
        "Return raw JSON only. Build a checklist the lab MUST satisfy before it is generated."
    )
    # Personalize the lab's BACKBONE, not just the cells: the checklist must
    # reflect the student's remediation/strength targets and learning style.
    profile_block = ""
    if profile_context and profile_context != "No profile available":
        profile_block = (
            f"\n\nSTUDENT PROFILE (personalize the checklist to it):\n{profile_context}\n"
            "- Add a checklist item for each REMEDIATION TARGET (extra practice on weak concepts).\n"
            "- Add a stretch checklist item for the STRENGTH TARGETS.\n"
            "- Reflect the student's learning style and effective approaches in the items."
        )
    user = (
        "Create a checklist for a coding lab using this session data. "
        "The checklist must cover concept recap, syntax practice, implementation tasks, "
        "student personalization, and tutor tips.\n\n"
        f"{json.dumps(_build_payload(request, session), indent=2)}"
        f"{profile_block}\n\n"
        'Return exactly: {"checklist":[{"id":"C1","item":"...","reason":"..."}]}'
    )
    data = _chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.25,
        max_tokens=900,
    )
    items = data.get("checklist", [])
    if not isinstance(items, list) or not items:
        raise ValueError("Checklist generation returned no checklist")
    return [LabChecklistItem.model_validate(item) for item in items[:8]]


def _generate_lab(
    request: CodingLabGenerateRequest,
    session: dict[str, Any],
    checklist: list[LabChecklistItem],
    profile_context: str = "",
) -> CodingLab:
    system = (
        "You generate notebook-style Python coding labs for beginners. "
        "Return raw JSON only. The lab must satisfy every checklist item. "
        "Use short explanations, concrete code, and hands-on tasks. "
        "Do not include markdown fences."
    )
    schema = {
        "title": "string",
        "intro": "string",
        "estimated_minutes": 15,
        "tutor_opening": "string",
        "cells": [
            {
                "id": "cell-1",
                "cell_type": "explanation | code | task",
                "title": "string",
                "narrative": "string",
                "code": "Python code for worked examples only",
                "expected_output": "optional expected output",
                "task_prompt": "task instructions for task cells",
                "starter_code": "starter Python code for task cells",
                "success_criteria": ["criteria"],
                "tutor_script": "what the floating tutor says for this cell",
                "tips": ["progressive hints"],
            }
        ],
        "completion_message": "string",
    }

    # Profile injection block
    profile_block = ""
    if profile_context and profile_context != "No profile available":
        profile_block = (
            f"\n\nSTUDENT PROFILE:\n{profile_context}\n\n"
            "Use this profile to:\n"
            "- Adapt explanation cell language to match the student's learning style signals\n"
            "- Add more detailed explanation + a dedicated remediation cell for the REMEDIATION TARGETS listed above\n"
            "- Use faster pacing and a harder stretch task for the STRENGTH TARGETS listed above\n"
            "- Apply the recommended_approaches when deciding how to structure explanations\n"
            "- If unresolved_questions is non-empty and relevant to this lab topic, "
            "address them explicitly in explanation cells"
        )

    user = (
        "Generate the highly polished, premium coding lab now.\n\n"
        "Rules:\n"
        "- Create a visually engaging flow: explanation cells, followed by 'code' (demonstration) cells, followed by 'task' (exercise) cells.\n"
        "- Code cells (`cell_type: \"code\"`) are strictly for demonstration. Students CANNOT edit them. Provide a clear, correct example.\n"
        "- Task cells (`cell_type: \"task\"`) are exercises where students write code. Provide starter code and tasks.\n"
        "- Include exactly 5 to 7 cells total. At least 2 cells must be task cells with starter_code and tips.\n"
        "- Worked examples and task starters must be valid Python code.\n"
        "- Personalize difficulty and wording using the student profile.\n"
        "- The tutor_script should explain each cell dynamically. For 'code' cells, explain the demonstration. For 'task' cells, nudge the student to attempt the exercise.\n\n"
        f"Checklist:\n{json.dumps([item.model_dump() for item in checklist], indent=2)}\n\n"
        f"Session data:\n{json.dumps(_build_payload(request, session), indent=2)}"
        f"{profile_block}\n\n"
        f"Return exactly this JSON shape:\n{json.dumps(schema, indent=2)}"
    )
    data = _chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.55,
        max_tokens=3600,
    )
    return CodingLab.model_validate(data)


async def generate_coding_lab(request: CodingLabGenerateRequest) -> CodingLabGenerateResponse:
    store = get_coding_lab_store()
    lab_id = store.lab_id(request.student_id, request.course_id, request.lesson_id)

    if not request.force_regenerate:
        cached = store.load(lab_id)
        if cached is not None:
            cached.cached = True
            return cached

    session = _session_context(request.session_id)

    # Fetch student profile for personalization
    profile_context = ""
    try:
        profile_data = await _fetch_student_profile(request.student_id)
        topic = request.lesson_title or session.get("current_topic", "")
        profile_context = _extract_relevant_profile_context(profile_data, topic=topic)

        # Append weak/strong-concept targets derived from concept_mastery (the
        # MASTERY MODEL — competence is read here to BUILD content, and is NOT
        # added back into the qualitative profile context above).
        course_id = getattr(request, "course_id", "") or ""
        if course_id:
            from services.mastery import (
                fetch_concept_mastery, fetch_course_concepts,
                top_weak_concepts, top_strong_concepts,
            )
            try:
                cm = await fetch_concept_mastery(request.student_id)
                if cm:
                    concepts = await fetch_course_concepts(course_id)
                    label_map = {c["id"]: c["label"] for c in concepts}
                    weak = top_weak_concepts(cm, n=3)
                    if weak:
                        labels = [label_map.get(w["concept_id"], w["concept_id"]) for w in weak]
                        profile_context += (
                            f"\nREMEDIATION TARGETS: {', '.join(labels)}. "
                            "Include one dedicated remediation coding cell addressing the weakest concept."
                        )
                    strong = top_strong_concepts(cm, n=3)
                    if strong:
                        s_labels = [label_map.get(s["concept_id"], s["concept_id"]) for s in strong]
                        profile_context += (
                            f"\nSTRENGTH TARGETS: {', '.join(s_labels)}. "
                            "Include one harder/stretch task on the strongest concept to extend the student."
                        )
            except Exception as _we:
                logger.debug("Could not fetch weak/strong concepts for lab: %s", _we)
    except Exception as exc:
        logger.warning("lab_profile_fetch_failed: %s — continuing without profile", exc)

    try:
        checklist = _generate_checklist(request, session, profile_context=profile_context)
    except Exception as exc:
        logger.warning("lab_checklist_fallback lab_id=%s error=%s", lab_id, exc)
        checklist = _fallback_checklist(request, session)

    try:
        lab = _generate_lab(request, session, checklist, profile_context=profile_context)
    except Exception as exc:
        logger.warning("lab_generation_fallback lab_id=%s error=%s", lab_id, exc)
        lab = _fallback_lab(request, checklist)

    # Generate suggested questions per cell (separate LLM pass)
    topic = request.lesson_title or session.get("current_topic", "the lesson")
    _generate_suggested_questions(lab.cells, topic, profile_context)

    response = CodingLabGenerateResponse(
        lab_id=lab_id,
        cached=False,
        generated_at=_dt.datetime.utcnow().isoformat() + "Z",
        checklist=checklist,
        lab=lab,
    )
    store.save(response)
    await persist_lab(request.student_id, request.course_id, request.lesson_id,
                      response.model_dump(), status="generated")
    return response


async def persist_lab(student_id: str, course_id: str, lesson_id: str,
                      content_json: dict, *, status: str = "generated") -> None:
    """Durably record a lab as StudentArtifact(type=lab), best-effort.

    Called at generation (full content) and at completion (final state incl. all
    notes). Keyed by plan_version so a pathway regeneration never serves stale
    labs. A storage failure must not fail the lab flow — the file working-copy
    still serves the live session. (Notes added mid-lab are flushed durably at
    completion; the read-path migration off files is a later stage.)
    """
    if not (student_id and course_id and lesson_id):
        return
    try:
        import asyncio
        from services.plan_resolver import current_plan_version
        from services import artifact_client

        pv = await asyncio.to_thread(current_plan_version, str(student_id), str(course_id))
        if pv is None:
            logger.info("lab: no plan_version — not recorded durably (lesson=%s)", lesson_id)
            return
        lesson_key = int(lesson_id) if str(lesson_id).isdigit() else lesson_id
        await artifact_client.upsert_artifact(
            str(student_id), str(course_id), "lab",
            plan_version=pv, lesson_id=lesson_key,
            content_json=content_json, status=status,
        )
    except Exception:
        logger.warning("lab: durable persist failed (lesson=%s)", lesson_id, exc_info=True)


def _build_cell_context(cell: LabCell) -> dict[str, Any]:
    return {
        "id": cell.id,
        "cell_type": cell.cell_type,
        "title": cell.title,
        "narrative": cell.narrative,
        "code": cell.code,
        "expected_output": cell.expected_output,
        "task_prompt": cell.task_prompt,
        "starter_code": cell.starter_code,
        "success_criteria": cell.success_criteria,
        "prepared_tutor_script": cell.tutor_script,
        "tips": cell.tips,
    }


async def explain_lab_cell(
    lab_title: str,
    cell: LabCell,
    mode: str = "explain",
    student_profile_summary: str = "",
    session_id: str | None = None,
) -> dict:
    """Generate spoken tutor narration for one lab cell.

    This endpoint does not require an active tutor session. If a session_id is
    available, it uses SharedSessionStore as extra context; otherwise it still
    generates and speaks from the lab cell itself.
    """
    session = _session_context(session_id)
    fallback = cell.tutor_script or cell.narrative or cell.task_prompt or "Let's work through this lab cell."

    try:
        system = (
            "You are LearnPal, a friendly and premium programming tutor inside a notebook-style coding lab. "
            "Speak naturally. Keep the answer short enough for audio. "
            "CRITICAL RULES: \n"
            "1. If the cell_type is 'code', this is a DEMONSTRATION cell. The student CANNOT edit it. Do NOT ask them to edit, modify, or complete it. Just explain how it works.\n"
            "2. If the cell_type is 'task', this is an EXERCISE cell. Encourage them to complete it and write the code.\n"
            "3. For tips, guide the student without giving away the full solution. "
            "Return raw JSON only."
        )
        user = (
            f"Mode: {mode}\n"
            f"Lab title: {lab_title}\n"
            f"Student profile summary: {student_profile_summary or session.get('student_profile_summary', '')}\n"
            f"Session context: {json.dumps(session, indent=2)}\n"
            f"Cell: {json.dumps(_build_cell_context(cell), indent=2)}\n\n"
            'Return exactly: {"text":"spoken tutor narration"}'
        )
        data = _chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.45,
            max_tokens=420,
        )
        text = str(data.get("text") or fallback).strip()
    except Exception as exc:
        logger.warning("lab_explain_generation_fallback cell=%s error=%s", cell.id, exc)
        text = fallback

    audio_base64 = None
    blendshapes = None
    try:
        from services.tts_service import get_tts_service

        tts = get_tts_service()
        audio = await tts.synthesize(
            text=text,
            voice="en-US-GuyNeural",
            rate="+0%",
            pitch="+0Hz",
        )
        audio_base64 = base64.b64encode(audio["audio_bytes"]).decode("utf-8")
    except Exception as exc:
        logger.warning("lab_explain_tts_failed cell=%s error=%s", cell.id, exc)

    try:
        from services.tts_service import get_tts_service
        from services.a2f_client import get_blendshapes

        tts = get_tts_service()
        wav_path = await tts.synthesize_wav(
            text=text,
            voice="en-US-GuyNeural",
            rate="+0%",
            pitch="+0Hz",
        )
        result = get_blendshapes(wav_path)
        try:
            os.remove(wav_path)
        except OSError:
            pass
        if result:
            blendshapes = {
                "names": result["blendshape_names"],
                "frames": result["frames"],
            }
    except Exception as exc:
        logger.info("lab_explain_blendshapes_unavailable cell=%s error=%s", cell.id, exc)

    return {
        "success": True,
        "text": text,
        "audio_base64": audio_base64,
        "blendshapes": blendshapes,
    }


def run_lab_code(code: str, timeout_seconds: int = 5) -> CodingLabRunResponse:
    """Compile and run a Python lab snippet in a short-lived subprocess."""
    if not code.strip():
        return CodingLabRunResponse(success=False, stderr="No code to run.", exit_code=1)

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            encoding="utf-8",
            delete=False,
        ) as handle:
            tmp_path = handle.name
            handle.write(code)

        compile_result = subprocess.run(
            [sys.executable, "-m", "py_compile", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if compile_result.returncode != 0:
            return CodingLabRunResponse(
                success=False,
                stdout=compile_result.stdout,
                stderr=compile_result.stderr,
                exit_code=compile_result.returncode,
            )

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return CodingLabRunResponse(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return CodingLabRunResponse(
            success=False,
            stderr=f"Execution timed out after {timeout_seconds} seconds.",
            exit_code=124,
        )
    except Exception as exc:
        return CodingLabRunResponse(success=False, stderr=str(exc), exit_code=1)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
