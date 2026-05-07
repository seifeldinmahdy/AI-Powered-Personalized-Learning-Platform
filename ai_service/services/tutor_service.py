"""
Tutor Session Service — AI-powered private tutor using Ollama.

Manages session state, recursive context summarization, topic progression,
and question-answering with full context injection.

After every state change the service writes to ``SharedSessionStore`` so
that Intent, Slides, Profiler, and FER/SER subsystems can read the
latest tutor context without the frontend manually shuttling state.
"""

import os
import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv
import httpx

# Search for .env in multiple locations
_this_dir = Path(__file__).resolve().parent
for _candidate in [
    _this_dir / ".env",             # ai_service/services/.env
    _this_dir.parent / ".env",      # ai_service/.env
    _this_dir.parent.parent / ".env",  # project root .env
]:
    if _candidate.exists():
        load_dotenv(_candidate)
        break
else:
    load_dotenv()  # fallback: default search
logger = logging.getLogger(__name__)

# ── Configure Ollama Cloud ──
 
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

# ── TTS/Speech-output awareness (injected into every prompt) ──
_TTS_AWARENESS = (
    "OUTPUT MODALITY: Your text will be converted to speech via a Text-to-Speech engine "
    "and spoken aloud by an avatar. Therefore: "
    "never use markdown, bullet points, numbered lists, headers, asterisks, or any visual formatting. "
    "Write in natural spoken sentences. Avoid parenthetical asides. "
    "Do not include stage directions like '[pause]' or '(laughs)'. "
    "Spell out abbreviations the first time (for example say 'Application Programming Interface' not 'API'). "
    "Keep sentences short so the TTS sounds natural."
)

# ── System prompts (finetuned for pedagogical benchmarks) ──

LECTURE_SYSTEM_PROMPT = f"""\
You are Dr. Nova, an expert AI tutor giving a private one-on-one lecture.

{_TTS_AWARENESS}

TURN LENGTH: Keep each turn to roughly 50 to 80 words. Aim for about 30 seconds of speech, not 90.

RULES:
- Speak naturally as if talking to a student face-to-face.
- Explain ONE key idea per turn using a simple analogy or real-world example.
- Do NOT greet or introduce yourself unless this is the very first chunk of the session.
- End every turn with exactly ONE short, open-ended question to check understanding or spark curiosity. Never ask more than one question.
- Do NOT give away the full answer to your own question. Let the student think.
- If there is a next subtopic, weave a brief transition into your question.
"""

SUMMARIZE_SYSTEM_PROMPT = """\
You are a context compression assistant. Given a running summary and the latest lecture content,
produce a concise merged summary that captures ALL key points covered so far.
Keep it under 300 words. Do not add opinions or new information.
"""

ANSWER_SYSTEM_PROMPT = f"""\
You are Dr. Nova, an expert AI tutor. A student has asked a question during your lecture.

{_TTS_AWARENESS}

TURN LENGTH: Keep your response to roughly 50 to 80 words.

RULES:
- Do NOT give the answer directly. Instead, guide the student toward it with a hint, a simpler sub-question, or a relatable analogy.
- If the student is clearly stuck after multiple attempts, give a partial answer and ask them to complete the rest.
- End with exactly ONE follow-up question that helps the student think deeper. Never list multiple questions.
- Transition back to the lecture naturally after the question.
"""

REPHRASE_SYSTEM_PROMPT = f"""\
You are Dr. Nova, an expert AI tutor. A student has just asked you to explain the same topic in
a different, simpler way.

{_TTS_AWARENESS}

TURN LENGTH: Keep your response to roughly 50 to 80 words.

RULES:
- Re-explain the SAME subtopic using different analogies, simpler vocabulary, or a fresh angle.
- Do NOT say "as I mentioned before" or "let me repeat" — just dive straight into the new explanation.
- End with ONE open-ended question to verify the new explanation landed.
"""


# ── Modular Skills System (Anthropic-inspired composable prompt fragments) ──
# Each skill is a standalone prompt paragraph activated by runtime session state.
# Skills are appended to the system prompt dynamically, keeping prompts lean.

TUTOR_SKILLS = {
    # Activated on the very first chunk of a session
    "BACKGROUND_PROBE": (
        "SKILL — BACKGROUND PROBE: This is your first interaction with this student. "
        "Before diving into the material, briefly ask what they already know about the topic "
        "and what they hope to get out of this session. Keep it to one warm sentence plus one question."
    ),

    # Activated when the student's fused emotion is 'confused' or similar
    "CONFUSION_DIAGNOSIS": (
        "SKILL — CONFUSION DIAGNOSIS: The student appears confused. "
        "Do NOT re-explain the entire concept again. Instead, ask exactly one specific question "
        "to pinpoint what part is unclear, for example: 'Which part lost you — the analogy or the definition itself?' "
        "Wait for their answer before re-explaining."
    ),

    # Activated periodically (every N chunks) to trigger teach-back
    "TEACH_BACK": (
        "SKILL — TEACH-BACK CHECK: You have just finished explaining a concept. "
        "Before moving on, ask the student to explain what they just learned back to you in their own words. "
        "Frame it warmly, for example: 'Can you walk me through that concept as if you were explaining it to a friend?' "
        "Do NOT proceed to new material until you hear their explanation."
    ),

    # Activated when a student profile with engagement patterns exists
    "ENGAGEMENT_ADAPT": (
        "SKILL — ENGAGEMENT PERSONALIZATION: A learner profile is available for this student. "
        "Use the engagement patterns, learning style signals, and recommended approaches from the profile "
        "to adapt your teaching style. If the profile notes the student disengages during long theory, "
        "lead with examples. If the student learns best through analogies, prioritize analogies. "
        "Do not mention the profile to the student."
    ),

    # Always active during Q&A to enforce Socratic method
    "SOCRATIC_GUARD": (
        "SKILL — SOCRATIC GUARD: You must NEVER give the student the direct answer. "
        "Your job is to ask guiding questions, provide hints, and help the student arrive at the answer themselves. "
        "If they ask 'what is X?', respond with something like 'What do you think X might mean based on what we discussed?' "
        "Only after two failed attempts should you provide a partial answer."
    ),
}


def _build_system_prompt(base_prompt: str, active_skills: list[str]) -> str:
    """Compose the final system prompt by appending active skill fragments."""
    parts = [base_prompt.strip()]
    for skill_key in active_skills:
        if skill_key in TUTOR_SKILLS:
            parts.append(TUTOR_SKILLS[skill_key])
    return "\n\n".join(parts)


# ── Session dataclass ──
@dataclass
class TutorSession:
    """Holds the full state of a tutoring session."""

    session_id: str
    topics: List[dict]  # [{name: str, subtopics: [str, ...]}]
    current_topic_idx: int = 0
    current_subtopic_idx: int = 0
    running_summary: str = ""
    transcript: List[dict] = field(default_factory=list)  # [{role, text, timestamp}]
    status: str = "idle"  # idle | lecturing | answering | finished
    voice: str = "en-US-AndrewMultilingualNeural"
    is_first_chunk: bool = True
    student_profile_summary: Optional[str] = None
    pace_modifier: int = 0
    created_at: float = field(default_factory=time.time)

    # ── Repeat/clarification state (ISSUE-006) ──────────────────────
    # Populated after every generate_lecture_chunk() call so the system
    # always knows what the last spoken content was.
    last_chunk_text: Optional[str] = None
    last_chunk_subtopic: Optional[str] = None

    # ── Teach-back loop counter ──────────────────────────────────────
    # Incremented each chunk; triggers TEACH_BACK skill every N chunks.
    teach_back_counter: int = 0
    teach_back_interval: int = 3  # ask for teach-back every 3 chunks

    # ── Engagement personalization data from profiler ─────────────────
    student_profile_data: Optional[dict] = None

    @property
    def current_topic(self) -> Optional[str]:
        if self.current_topic_idx < len(self.topics):
            return self.topics[self.current_topic_idx]["name"]
        return None

    @property
    def current_subtopic(self) -> Optional[str]:
        if self.current_topic_idx < len(self.topics):
            topic = self.topics[self.current_topic_idx]
            subtopics = topic.get("subtopics", [])
            if self.current_subtopic_idx < len(subtopics):
                return subtopics[self.current_subtopic_idx]
        return None

    @property
    def total_items(self) -> int:
        """Total number of subtopics across all topics."""
        total = 0
        for t in self.topics:
            subs = t.get("subtopics", [])
            total += max(len(subs), 1)  # at least 1 per topic
        return total

    @property
    def completed_items(self) -> int:
        """Number of subtopics already covered."""
        done = 0
        for i, t in enumerate(self.topics):
            subs = t.get("subtopics", [])
            count = max(len(subs), 1)
            if i < self.current_topic_idx:
                done += count
            elif i == self.current_topic_idx:
                done += self.current_subtopic_idx
        return done

    @property
    def progress(self) -> float:
        total = self.total_items
        if total == 0:
            return 100.0
        return round((self.completed_items / total) * 100, 1)


# ── In-memory session store ──
_sessions: Dict[str, TutorSession] = {}


async def _call_ollama(system_prompt: str, user_prompt: str) -> str:
    """Call Ollama Cloud chat API and return the text response."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 512,
        },
    }

    headers = {}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"].strip()


# ── Relevance check ──

async def check_relevance(question: str, lesson_title: str) -> bool:
    """Return True if the question is relevant to the lesson or educational in general."""
    system = (
        "You are a relevance classifier for an AI tutoring platform. "
        "Your only job is to decide if a student's question is relevant to the lesson topic or is a legitimate educational/technical question. "
        "Reply with exactly one word: YES or NO. Nothing else."
    )
    user = (
        f"Lesson topic: {lesson_title}\n"
        f"Student question: {question}\n\n"
        "Is this question relevant to the lesson topic or a legitimate educational/technical question? "
        "Answer YES if it is related to programming, computer science, math, science, or the lesson topic. "
        "Answer NO only if it is completely unrelated to education (e.g. sports results, celebrity gossip, entertainment, politics). "
        "Reply with exactly one word: YES or NO."
    )
    try:
        answer = await _call_ollama(system, user)
        return answer.strip().upper().startswith("YES")
    except Exception:
        return True  # Default to allowing the question if the check fails


# ── Shared-store helper ──────────────────────────────────────────

def _sync_to_shared_store(session: TutorSession) -> None:
    """Write the current tutor session state to SharedSessionStore.

    This is called after every state change so that other subsystems
    (Intent, Slides, Profiler, FER/SER) can read up-to-date context
    without the frontend manually passing it.

    Parameters
    ----------
    session : TutorSession
        The tutor session whose state should be synced.
    """
    try:
        from services.session_store import get_session_store
        store = get_session_store()
        store.update_session(
            session.session_id,
            live_kwargs={
                "current_topic": session.current_topic or "",
                "current_subtopic": session.current_subtopic or "",
                "running_summary": session.running_summary,
                "tutor_transcript": session.transcript[-10:],
                "pace_modifier": session.pace_modifier,
            },
            profile_kwargs={
                "student_profile_summary": session.student_profile_summary or "",
            }
        )
    except Exception as exc:
        logger.warning("Failed to sync tutor state to SharedSessionStore: %s", exc)


# ── Public API ──

def create_session(
    topics: List[dict],
    voice: str = "en-US-GuyNeural",
    session_id: Optional[str] = None,
    student_profile_summary: Optional[str] = None,
    student_profile_data: Optional[dict] = None,
) -> TutorSession:
    """Create a new tutoring session."""
    sid = session_id or str(uuid.uuid4())

    # Auto-generate subtopics for topics that have none, so the tutor
    # self-reprompts across multiple chunks instead of one monologue.
    for topic in topics:
        subs = topic.get("subtopics", [])
        if not subs:
            name = topic.get("name", "Topic")
            topic["subtopics"] = [
                f"Introduction to {name}",
                f"Core concepts of {name}",
                f"Examples and practical usage of {name}",
                f"Summary and key takeaways of {name}",
            ]

    session = TutorSession(
        session_id=sid,
        topics=topics,
        voice=voice,
        status="idle",
        student_profile_summary=student_profile_summary,
        student_profile_data=student_profile_data,
    )
    _sessions[sid] = session
    logger.info(f"Session {sid} created with {len(topics)} topics")

    # ── Seed SharedSessionStore ──
    from services.session_store import get_session_store
    from schemas.student_context import StudentProfileState
    store = get_session_store()
    
    # We construct a profile with whatever partial data we have, relying on defaults
    # for the missing database fields until a real DB lookup is implemented.
    profile = StudentProfileState(
        student_profile_summary=student_profile_summary or ""
    )
    store.create_session(sid, profile=profile)

    _sync_to_shared_store(session)

    return session


def get_session(session_id: str) -> Optional[TutorSession]:
    """Retrieve a session by ID."""
    return _sessions.get(session_id)


async def generate_lecture_chunk(session_id: str, student_emotion: Optional[str] = None) -> dict:
    """
    Generate the next lecture chunk for the session.

    This is the core "self-reprompting" mechanism:
    1. Build a prompt with running summary + current topic/subtopic
    2. Call Gemini to generate lecture content
    3. Recursively update the running summary
    4. Advance to the next subtopic/topic
    5. Return the lecture text + metadata
    """
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    if session.status == "finished":
        return {
            "text": "",
            "topic": None,
            "subtopic": None,
            "progress": 100.0,
            "is_finished": True,
            "status": "finished",
        }

    session.status = "lecturing"

    # ── Determine which skills to activate ──
    active_skills: list[str] = []

    if session.is_first_chunk:
        active_skills.append("BACKGROUND_PROBE")

    # Confusion diagnosis: if the student looks confused, ask what's unclear
    if student_emotion and student_emotion.lower() in ("confused", "surprise", "fear"):
        active_skills.append("CONFUSION_DIAGNOSIS")

    # Teach-back: every N chunks, ask the student to explain back
    session.teach_back_counter += 1
    if session.teach_back_counter >= session.teach_back_interval:
        active_skills.append("TEACH_BACK")
        session.teach_back_counter = 0  # reset

    # Engagement personalization: if profiler data is available
    if session.student_profile_data or session.student_profile_summary:
        active_skills.append("ENGAGEMENT_ADAPT")

    # Build the composed system prompt
    system_prompt = _build_system_prompt(LECTURE_SYSTEM_PROMPT, active_skills)

    # Build the lecture prompt
    topic_name = session.current_topic or "General Review"
    subtopic_name = session.current_subtopic

    context_parts = []
    if session.running_summary:
        context_parts.append(f"SUMMARY OF WHAT YOU'VE COVERED SO FAR:\n{session.running_summary}")

    context_parts.append(f"CURRENT MAIN TOPIC: {topic_name}")
    if subtopic_name:
        context_parts.append(f"CURRENT SUBTOPIC TO EXPLAIN NOW: {subtopic_name}")
    else:
        context_parts.append(f"Explain this topic as a whole.")

    if session.is_first_chunk:
        context_parts.append("This is the BEGINNING of the session. Start with a brief warm greeting.")

        # Inject student profile for personalization from the first chunk
        if session.student_profile_summary:
            context_parts.append(
                f"STUDENT LEARNER PROFILE (use to personalize, do NOT mention to student):\n"
                f"{session.student_profile_summary}"
            )

        # Inject detailed engagement patterns from profiler if available
        if session.student_profile_data:
            import json as _json
            engagement = session.student_profile_data.get("engagement_patterns", {})
            approaches = session.student_profile_data.get("recommended_approaches", [])
            if engagement or approaches:
                profile_context = "ENGAGEMENT PATTERNS FROM PROFILER:\n"
                if engagement.get("high"):
                    profile_context += f"Student engages most when: {', '.join(engagement['high'])}\n"
                if engagement.get("low"):
                    profile_context += f"Student disengages when: {', '.join(engagement['low'])}\n"
                if approaches:
                    profile_context += f"Recommended approaches: {', '.join(approaches)}\n"
                context_parts.append(profile_context)

        session.is_first_chunk = False

    # Look ahead to tell the model what's next
    next_item = _peek_next(session)
    if next_item:
        context_parts.append(f"NEXT UP AFTER THIS: {next_item}")
    else:
        context_parts.append("This is the LAST subtopic. Wrap up with a brief conclusion.")

    # Inject student emotion for tone adaptation
    if student_emotion:
        context_parts.append(
            f"Current student emotional state: {student_emotion}. "
            "Adjust your tone accordingly — if bored, be more energetic; "
            "if confused, slow down and simplify; if anxious, be reassuring; if engaged, maintain energy. "
            "Do NOT skip planned material. Only adapt tone and pacing."
        )

    # Log active skills for debugging
    if active_skills:
        logger.info(f"Active skills for this chunk: {active_skills}")

    user_prompt = "\n\n".join(context_parts)

    # Call Ollama with reduced token budget for shorter turns
    start = time.time()
    lecture_text = await _call_ollama(system_prompt, user_prompt)
    elapsed = round(time.time() - start, 2)

    logger.info(f"Lecture chunk generated in {elapsed}s for [{topic_name} > {subtopic_name}]")

    # Add to transcript
    session.transcript.append({
        "role": "tutor",
        "text": lecture_text,
        "topic": topic_name,
        "subtopic": subtopic_name,
        "timestamp": time.time(),
    })

    # Keep transcript sliding window (last 10 entries max)
    if len(session.transcript) > 10:
        session.transcript = session.transcript[-10:]

    # ── Remember last spoken chunk for Repeat/clarification (ISSUE-006) ──
    session.last_chunk_text = lecture_text
    session.last_chunk_subtopic = subtopic_name

    # Recursively update running summary
    await _update_summary(session, lecture_text)

    # Advance to next subtopic/topic
    is_finished = _advance(session)

    # ── Sync state to SharedSessionStore ──
    _sync_to_shared_store(session)

    return {
        "text": lecture_text,
        "topic": topic_name,
        "subtopic": subtopic_name,
        "progress": session.progress,
        "is_finished": is_finished,
        "status": session.status,
        "inference_time": elapsed,
        "active_skills": active_skills,
    }


async def answer_question(session_id: str, question: str, student_emotion: Optional[str] = None) -> dict:
    """
    Handle a student question mid-lecture.
    Injects the question + full context, generates an answer.
    Adapts tone based on student_emotion when available.
    """
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    prev_status = session.status
    session.status = "answering"

    # ── Determine active skills for Q&A ──
    qa_skills: list[str] = ["SOCRATIC_GUARD"]  # always active during Q&A
    if student_emotion and student_emotion.lower() in ("confused", "surprise", "fear"):
        qa_skills.append("CONFUSION_DIAGNOSIS")

    system_prompt = _build_system_prompt(ANSWER_SYSTEM_PROMPT, qa_skills)

    context_parts = []
    if session.running_summary:
        context_parts.append(f"CONTEXT (what we've covered so far):\n{session.running_summary}")
    context_parts.append(f"CURRENT TOPIC: {session.current_topic or 'N/A'}")
    if session.current_subtopic:
        context_parts.append(f"CURRENT SUBTOPIC: {session.current_subtopic}")

    # Inject emotion-aware tone adaptation
    if student_emotion and student_emotion.lower() not in ("neutral", "unknown"):
        emotion_guidance = {
            "happy": "The student sounds engaged and positive. Match their energy with an enthusiastic, encouraging answer.",
            "sad": "The student seems down. Be warm, supportive, and extra patient. Reassure them that struggling is normal.",
            "angry": "The student sounds frustrated. Stay calm, validate their frustration, and provide a clear, structured answer.",
            "fear": "The student seems anxious or worried. Be reassuring and break your answer into small, manageable steps.",
            "surprise": "The student seems surprised or confused. Acknowledge what might be unexpected and explain clearly.",
            "disgust": "The student seems displeased. Be empathetic and try a different angle in your explanation.",
        }
        guidance = emotion_guidance.get(
            student_emotion.lower(),
            f"The student's emotional state is '{student_emotion}'. Adapt your tone to be supportive and appropriate."
        )
        context_parts.append(f"EMOTIONAL CONTEXT: {guidance}")

    context_parts.append(f"STUDENT'S QUESTION: {question}")

    user_prompt = "\n\n".join(context_parts)

    start = time.time()
    answer_text = await _call_ollama(system_prompt, user_prompt)
    elapsed = round(time.time() - start, 2)

    # Add to transcript
    session.transcript.append({
        "role": "student",
        "text": question,
        "timestamp": time.time(),
    })
    session.transcript.append({
        "role": "tutor",
        "text": answer_text,
        "topic": session.current_topic,
        "subtopic": session.current_subtopic,
        "timestamp": time.time(),
        "is_answer": True,
    })

    # Update summary with the Q&A
    qa_text = f"Student asked: {question}\nTutor answered: {answer_text}"
    await _update_summary(session, qa_text)

    # Restore status (back to lecturing or finished)
    session.status = prev_status if prev_status != "answering" else "lecturing"

    # ── Sync state to SharedSessionStore ──
    _sync_to_shared_store(session)

    return {
        "answer": answer_text,
        "topic": session.current_topic,
        "subtopic": session.current_subtopic,
        "progress": session.progress,
        "is_finished": session.status == "finished",
        "status": session.status,
        "inference_time": elapsed,
    }


async def repeat_lecture_chunk(session_id: str, mode: str = "rephrase") -> dict:
    """
    Handle a ``Repeat/clarification`` intent without advancing the topic pointer.

    Parameters
    ----------
    session_id : str
        Active session ID.
    mode : str
        ``"verbatim"`` — return the exact same last chunk text (caller should
        apply a slower TTS rate for clearer delivery).

        ``"rephrase"`` — call the LLM again for the same subtopic with a
        simplification directive, then store the result as the new
        ``last_chunk_text``.

    Returns
    -------
    dict
        Keys: ``text``, ``topic``, ``subtopic``, ``mode``, ``progress``,
        ``status``, and (rephrase only) ``inference_time``.

    Raises
    ------
    ValueError
        If the session does not exist or nothing has been spoken yet
        (``last_chunk_text`` is ``None``).
    """
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    if not session.last_chunk_text:
        raise ValueError(
            "Nothing to repeat — the tutor has not spoken any lecture content yet."
        )

    prev_status = session.status
    topic_name = session.current_topic or "General Review"
    subtopic_name = session.last_chunk_subtopic or session.current_subtopic
    elapsed: Optional[float] = None

    if mode == "verbatim":
        # Return the stored text as-is; the router will apply slower TTS rate.
        response_text = session.last_chunk_text
        logger.info(
            "Repeat[verbatim] for session %s subtopic=%s",
            session_id,
            subtopic_name,
        )
    else:
        # mode == "rephrase" (default)
        context_parts = []
        if session.running_summary:
            context_parts.append(
                f"SUMMARY OF WHAT YOU'VE COVERED SO FAR:\n{session.running_summary}"
            )
        context_parts.append(f"CURRENT MAIN TOPIC: {topic_name}")
        if subtopic_name:
            context_parts.append(f"SUBTOPIC TO RE-EXPLAIN: {subtopic_name}")
        context_parts.append(
            "INSTRUCTION: The student asked for a simpler or different explanation of "
            "the content above. Explain this differently and more simply."
        )

        user_prompt = "\n\n".join(context_parts)
        start = time.time()
        response_text = await _call_ollama(REPHRASE_SYSTEM_PROMPT, user_prompt)
        elapsed = round(time.time() - start, 2)

        logger.info(
            "Repeat[rephrase] generated in %ss for session %s subtopic=%s",
            elapsed,
            session_id,
            subtopic_name,
        )

        # Store as new last chunk so a further repeat works off the rephrased text.
        session.last_chunk_text = response_text

        # Add rephrased explanation to transcript
        session.transcript.append({
            "role": "tutor",
            "text": response_text,
            "topic": topic_name,
            "subtopic": subtopic_name,
            "timestamp": time.time(),
            "is_repeat": True,
            "repeat_mode": "rephrase",
        })
        if len(session.transcript) > 10:
            session.transcript = session.transcript[-10:]

        # Update running summary with the rephrased content.
        await _update_summary(session, response_text)

    # Restore previous status (repeat does NOT advance the topic pointer)
    session.status = prev_status if prev_status not in ("idle", "answering") else "lecturing"

    _sync_to_shared_store(session)

    result = {
        "text": response_text,
        "topic": topic_name,
        "subtopic": subtopic_name,
        "mode": mode,
        "progress": session.progress,
        "status": session.status,
    }
    if elapsed is not None:
        result["inference_time"] = elapsed
    return result


def stop_session(session_id: str) -> bool:
    """Stop a session early."""
    session = _sessions.get(session_id)
    if session:
        session.status = "finished"
        _sync_to_shared_store(session)
        return True
    return False


def get_session_state(session_id: str) -> Optional[dict]:
    """Return the current session state as a dict."""
    session = _sessions.get(session_id)
    if not session:
        return None
    return {
        "session_id": session.session_id,
        "status": session.status,
        "current_topic": session.current_topic,
        "current_subtopic": session.current_subtopic,
        "progress": session.progress,
        "is_finished": session.status == "finished",
        "topics_count": len(session.topics),
        "transcript_length": len(session.transcript),
        "voice": session.voice,
    }


# ── Internal helpers ──

async def _update_summary(session: TutorSession, new_content: str):
    """Recursively compress the running summary with new content."""
    prompt = (
        f"EXISTING SUMMARY:\n{session.running_summary or '(none yet)'}\n\n"
        f"NEW CONTENT TO INCORPORATE:\n{new_content}\n\n"
        f"Produce the merged, compressed summary:"
    )
    try:
        session.running_summary = await _call_ollama(SUMMARIZE_SYSTEM_PROMPT, prompt)
    except Exception as e:
        logger.warning(f"Summary compression failed, appending raw: {e}")
        # Fallback: just append truncated content
        session.running_summary += f"\n{new_content[:500]}"


def _advance(session: TutorSession) -> bool:
    """
    Advance to the next subtopic/topic.
    Returns True if the session is now finished.
    """
    if session.current_topic_idx >= len(session.topics):
        session.status = "finished"
        return True

    topic = session.topics[session.current_topic_idx]
    subtopics = topic.get("subtopics", [])

    if subtopics and session.current_subtopic_idx < len(subtopics) - 1:
        # Move to next subtopic
        session.current_subtopic_idx += 1
    elif session.current_topic_idx < len(session.topics) - 1:
        # Move to next topic
        session.current_topic_idx += 1
        session.current_subtopic_idx = 0
    else:
        # All done
        session.status = "finished"
        return True

    return False


def _peek_next(session: TutorSession) -> Optional[str]:
    """Peek at the next subtopic/topic without advancing."""
    topic = session.topics[session.current_topic_idx]
    subtopics = topic.get("subtopics", [])

    if subtopics and session.current_subtopic_idx < len(subtopics) - 1:
        return f"{topic['name']} > {subtopics[session.current_subtopic_idx + 1]}"
    elif session.current_topic_idx < len(session.topics) - 1:
        next_topic = session.topics[session.current_topic_idx + 1]
        next_sub = next_topic.get("subtopics", [])
        if next_sub:
            return f"{next_topic['name']} > {next_sub[0]}"
        return next_topic["name"]
    return None
