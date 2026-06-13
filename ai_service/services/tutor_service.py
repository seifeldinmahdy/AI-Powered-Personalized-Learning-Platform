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

EMOTIONAL_SYSTEM_PROMPT = f"""\
You are Dr. Nova, an expert AI tutor. A student is expressing an emotional state during your session.

{_TTS_AWARENESS}

TURN LENGTH: Keep your response to 30 to 50 words. Brevity is kindness here.

RULES:
- Acknowledge the emotion first. Do not skip over it.
- Do NOT ask a Socratic or comprehension question. This is not a teaching moment, it is a human moment.
- Do NOT introduce new material.
- End with one gentle offer: ask if they want to continue, slow down, or take a short break.
- Stay warm, grounded, and specific to what the student actually said.
"""

PACE_SYSTEM_PROMPT = f"""\
You are Dr. Nova, an expert AI tutor. A student has asked you to change the pace of the session.

{_TTS_AWARENESS}

TURN LENGTH: One sentence only. 10 to 20 words maximum.

RULES:
- Confirm the pace change in one natural sentence.
- Do not explain, justify, or ask a question.
- Do not repeat prior material.
- Example for slowing down: "Sure, I will slow things down a bit from here."
- Example for speeding up: "Got it, let me pick up the pace."
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

    # Activated when intent is Emotional-State — replaces Socratic approach entirely
    "EMOTIONAL_ACKNOWLEDGEMENT": (
        "SKILL — EMOTIONAL ACKNOWLEDGEMENT: The student is expressing a feeling or emotional state, "
        "not asking a content question. Your ONLY job right now is to acknowledge their emotion warmly "
        "and briefly. Do NOT pivot to Socratic questioning. Do NOT explain new material. "
        "Validate what they said in one sentence, then gently ask if they are ready to continue "
        "or if they need a moment. Example: 'It sounds like you are feeling a bit overwhelmed — that is "
        "completely normal when things start moving fast. Do you want to take a breath and try again, "
        "or would it help to slow down a little?'"
    ),

    # Activated when intent is Pace-Related
    "PACE_ACKNOWLEDGEMENT": (
        "SKILL — PACE ACKNOWLEDGEMENT: The student has signalled they want to change the pace. "
        "Acknowledge the request in one short sentence and confirm the adjustment. "
        "Do not re-explain prior material. Do not ask a question. "
        "Example for slow-down: 'Got it, I will take it a bit slower from here.' "
        "Example for speed-up: 'Sure, I will pick up the pace.' "
        "Then continue naturally into the current subtopic at the new pace."
    ),

    # Activated when handling a student response to BACKGROUND_PROBE or TEACH_BACK
    "PROBE_RESPONSE_HANDLER": (
        "SKILL — PROBE RESPONSE: The student has just responded to a question you asked "
        "(either a background knowledge probe or a teach-back request). "
        "Do NOT treat their message as a new question. "
        "Acknowledge what they said briefly — affirm what is correct, gently correct what is wrong — "
        "and then transition naturally into the lecture material. "
        "Do NOT ask another open-ended question immediately."
    ),

    # Activated when the student has failed the same Socratic question twice
    "SOCRATIC_SCAFFOLD": (
        "SKILL — SCAFFOLDED HINT: The student has attempted this question at least twice without success. "
        "Stop asking them to guess. Give them a concrete partial answer — enough to move forward — "
        "and ask them to complete or apply the remaining part. "
        "Example: 'A loop keeps running as long as a condition is true. So what do you think happens if that condition never becomes false?'"
    ),

    # ── Profile-driven skills (activated by student profile data) ──

    "DIFFICULTY_TOPIC": (
        "SKILL — DIFFICULTY TOPIC: The current subtopic covers something "
        "this student has historically struggled with. Slow down. Use at "
        "least two concrete real-world examples before introducing any "
        "abstraction. Check understanding with a direct question before "
        "moving on. Do not assume prior knowledge for this concept even "
        "if it seems basic."
    ),

    "STRENGTH_TOPIC": (
        "SKILL — STRENGTH TOPIC: The current subtopic covers something "
        "this student already understands well. Move at a faster pace. "
        "Skip basic definitions. Push toward a more challenging application, "
        "edge case, or extension of this concept to keep them engaged."
    ),

    "VISUAL_LEARNER": (
        "SKILL — VISUAL LEARNER: This student learns best through visual "
        "and spatial thinking. Use spatial language throughout: 'picture "
        "this as a tree', 'imagine a grid where each row represents...', "
        "'draw a box for each step'. Reference any diagrams or visuals on "
        "the current slide explicitly. Avoid purely abstract descriptions."
    ),

    "HANDS_ON_LEARNER": (
        "SKILL — HANDS-ON LEARNER: This student learns best by doing. "
        "Lead with a code example or concrete manipulation before explaining "
        "theory. Say things like 'try changing this value and see what "
        "happens' or 'if you ran this right now, you would see...'. "
        "Ground every concept in something the student can immediately touch."
    ),

    "SURFACE_UNRESOLVED": (
        "SKILL — UNRESOLVED QUESTION: This student had an open question "
        "from a previous session that relates to the current topic. "
        "Weave the answer into your explanation naturally without saying "
        "'you asked this before'. Just address it as part of the content."
    ),

    "PACE_SLOW": (
        "SKILL — PACE PREFERENCE SLOW: This student has expressed a "
        "preference for a slower pace. Take extra time on each concept. "
        "Use more examples than usual. Do not rush transitions."
    ),

    "PACE_FAST": (
        "SKILL — PACE PREFERENCE FAST: This student has expressed a "
        "preference for a faster pace. Be concise. Skip extended analogies "
        "unless the student seems confused. Move to the next concept "
        "promptly after a brief comprehension check."
    ),

    "RECURRENT_MISTAKE": (
        "SKILL — RECURRENT MISTAKE PATTERN: This student has a known "
        "recurring mistake pattern related to the current topic. "
        "Proactively address the common mistake before the student makes "
        "it. Say something like 'one thing many students get tripped up "
        "on here is...' without singling out the student personally."
    ),

    # Activated when intent is Debugging/Code-Sharing
    "DIRECT_DEBUG_HELP": (
        "SKILL — DIRECT DEBUG HELP: The student is sharing code or an error message "
        "and asking for debugging help. Do NOT use the Socratic method here — they need "
        "a direct, clear fix. Identify the bug or error, explain WHY it happens in one "
        "or two sentences, then show the corrected approach. After giving the fix, ask "
        "ONE follow-up question to check they understand the underlying concept, for "
        "example: 'Does it make sense why Python raises that error when you try to "
        "concatenate a string and an integer?'"
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
    student_id: Optional[str] = None
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
    # Structured weak concepts from concept_mastery [{concept_id, label, score, evidence}]
    weak_concepts: list = field(default_factory=list)

    # ── Socratic attempt tracking ─────────────────────────────────────
    # Tracks how many times the student has attempted to answer the
    # current Socratic question. Resets when the topic advances or when
    # the tutor moves on from a Q&A exchange.
    socratic_attempt_count: int = 0

    # ── Last intent routed to this session ───────────────────────────
    # Written by the router on every student turn so internal handlers
    # can adapt their behaviour (e.g. skip SOCRATIC_GUARD for emotional
    # inputs, track consecutive failures, etc.).
    last_intent: Optional[str] = None
    last_intent_confidence: float = 0.0

    # ── Awaiting student response flag ───────────────────────────────
    # Set True after BACKGROUND_PROBE or TEACH_BACK so the next student
    # message is treated as a probe/teach-back response, not a question.
    awaiting_student_response: bool = False
    awaiting_response_type: Optional[str] = None  # "background_probe" | "teach_back"

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


async def _call_ollama(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    num_predict: int = 180,
    conversation_history: Optional[List[dict]] = None,
) -> str:
    """Call Ollama Cloud chat API and return the text response.

    Parameters
    ----------
    system_prompt:
        The system-role prompt for the model.
    user_prompt:
        The user-role prompt (current turn context).
    temperature:
        Sampling temperature. Use lower values for factual/compressed tasks
        (summarisation → 0.2, relevance → 0.0) and higher for generative
        tasks (lecture → 0.7, emotion handling → 0.6).
    num_predict:
        Max tokens to generate. 180 covers ~50-80 spoken words with margin.
        Summarisation tasks should pass 400.
    conversation_history:
        Optional list of prior turns in ``[{"role": ..., "content": ...}]``
        format. When provided, these are injected between the system prompt
        and the current user prompt so the model has multi-turn context.
    """
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"

    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
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


def _build_conversation_history(session: TutorSession, max_turns: int = 4) -> List[dict]:
    """
    Convert the last N transcript entries into the ``messages`` format
    expected by Ollama's chat endpoint.

    This gives the model genuine multi-turn context so it can see what
    the student just said before generating the next response, rather than
    relying solely on the compressed running summary.

    Only the last ``max_turns`` exchanges are included to stay within the
    context budget. Each exchange = 1 student message + 1 tutor message.
    """
    history = []
    # Transcript entries: [{role: "tutor"|"student", text: str, ...}]
    # We want the last max_turns * 2 entries (alternating student/tutor)
    recent = session.transcript[-(max_turns * 2):]
    for entry in recent:
        role = "assistant" if entry["role"] == "tutor" else "user"
        history.append({"role": role, "content": entry["text"]})
    return history


def _build_profile_context(session: TutorSession) -> Optional[str]:
    """
    Build the engagement profile context string for injection into prompts.

    Extracted as a helper so this can be injected on every call, not just
    the first chunk. The profile is small enough that it fits comfortably
    in every prompt without bloating it.
    """
    parts = []
    if session.student_profile_summary:
        parts.append(
            f"STUDENT LEARNER PROFILE (use to personalise, do NOT mention to student):\n"
            f"{session.student_profile_summary}"
        )
    if session.student_profile_data:
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
            parts.append(profile_context)
    return "\n".join(parts) if parts else None


# ── Relevance check ──

async def check_relevance(question: str, lesson_title: str) -> bool:
    """
    Deprecated. Off-topic detection is now the responsibility of the intent
    classifier (Off-Topic Question class). This stub always returns True so
    existing call sites do not break while they are migrated to read the
    classifier's intent label directly.

    See fix guide Fix 4 for the replacement routing pattern.
    """
    return True


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


async def _fetch_student_profile_for_tutor(student_id: str) -> dict:
    """Fetch student profile from Django for tutor personalization."""
    django_url = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{django_url}/progress/learning-profile/",
                headers={
                    "X-Student-ID": student_id,
                    "X-Service-Key": service_key,
                },
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning("Tutor profile fetch failed: %s", e)
    return {}


async def _fetch_and_attach_profile(session: TutorSession) -> None:
    """Async helper to fetch and attach profile to session after creation."""
    if not session.student_id:
        return
    profile_data = await _fetch_student_profile_for_tutor(session.student_id)
    if profile_data:
        session.student_profile_data = profile_data.get("profile_data")
        if not session.student_profile_summary:
            session.student_profile_summary = profile_data.get(
                "profile_summary", ""
            )
        # Populate structured weak concepts for skill targeting
        try:
            from services.mastery import fetch_concept_mastery, top_weak_concepts
            cm = await fetch_concept_mastery(session.student_id)
            if cm:
                session.weak_concepts = top_weak_concepts(cm, n=3)
        except Exception as _wce:
            logger.debug("Could not fetch weak concepts for tutor session: %s", _wce)
        logger.info(
            "Profile attached to session %s for student %s",
            session.session_id, session.student_id
        )


def create_session(
    topics: List[dict],
    voice: str = "en-US-GuyNeural",
    session_id: Optional[str] = None,
    student_profile_summary: Optional[str] = None,
    student_profile_data: Optional[dict] = None,
    student_id: Optional[str] = None,
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
        student_id=student_id,
    )
    _sessions[sid] = session
    logger.info(f"Session {sid} created with {len(topics)} topics")

    # If no profile data was passed by caller, try to fetch from Django
    if session.student_profile_data is None and session.student_id:
        try:
            import asyncio
            # create_session is sync — run the async fetch in the event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule fetch without blocking — profile will be
                # available by the time the first chunk is generated
                asyncio.ensure_future(_fetch_and_attach_profile(session))
            else:
                profile_data = loop.run_until_complete(
                    _fetch_student_profile_for_tutor(session.student_id)
                )
                if profile_data:
                    session.student_profile_data = profile_data.get("profile_data")
                    session.student_profile_summary = (
                        session.student_profile_summary
                        or profile_data.get("profile_summary", "")
                    )
        except Exception as e:
            logger.warning("Could not pre-fetch student profile: %s", e)

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


async def generate_lecture_chunk(
    session_id: str,
    student_emotion: Optional[str] = None,
    intent: Optional[str] = None,
    intent_confidence: float = 0.0,
) -> dict:
    """
    Generate the next lecture chunk for the session.

    This is the core "self-reprompting" mechanism:
    1. Build a prompt with running summary + current topic/subtopic
    2. Call the LLM to generate lecture content
    3. Recursively update the running summary
    4. Advance to the next subtopic/topic
    5. Return the lecture text + metadata

    Parameters
    ----------
    intent:
        The intent label from the classifier for the student's last message,
        if the chunk is being generated after a student turn. Used to choose
        which skills to activate.
    intent_confidence:
        Classifier confidence for ``intent``. Stored on the session for
        downstream logging and threshold decisions.
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

    # Record intent for session-level awareness
    if intent:
        session.last_intent = intent
        session.last_intent_confidence = intent_confidence

    session.status = "lecturing"

    # ── Determine which skills to activate ──
    active_skills: list[str] = []

    if session.is_first_chunk:
        active_skills.append("BACKGROUND_PROBE")
        session.awaiting_student_response = True
        session.awaiting_response_type = "background_probe"

    # If the student just responded to a background probe or teach-back,
    # acknowledge their response before moving into lecture content.
    elif session.awaiting_student_response:
        active_skills.append("PROBE_RESPONSE_HANDLER")
        session.awaiting_student_response = False
        session.awaiting_response_type = None

    # Confusion diagnosis: if the student looks confused, ask what's unclear
    if student_emotion and student_emotion.lower() in ("confused", "surprise", "fear"):
        active_skills.append("CONFUSION_DIAGNOSIS")

    # Teach-back: every N chunks, ask the student to explain back
    session.teach_back_counter += 1
    if session.teach_back_counter >= session.teach_back_interval:
        active_skills.append("TEACH_BACK")
        session.teach_back_counter = 0
        session.awaiting_student_response = True
        session.awaiting_response_type = "teach_back"

    # Engagement personalisation: inject on every call, not just the first
    if session.student_profile_data or session.student_profile_summary:
        active_skills.append("ENGAGEMENT_ADAPT")

    # ── Profile-driven skill activation ──
    topic_name = session.current_topic or "General Review"
    subtopic_name = session.current_subtopic

    if session.student_profile_data:
        profile = session.student_profile_data
        subtopic_lower = (subtopic_name or "").lower()
        topic_lower = (topic_name or "").lower()
        combined_lower = f"{subtopic_lower} {topic_lower}"

        difficulties = [str(d).lower() for d in profile.get("topics_of_difficulty", [])]
        strengths = [str(s).lower() for s in profile.get("topics_of_strength", [])]
        style_signals = [str(s).lower() for s in profile.get("learning_style_signals", [])]
        intentions = [str(i).lower() for i in profile.get("notable_intentions", [])]
        unresolved = profile.get("unresolved_questions", [])
        recurrent_mistakes = profile.get("recurrent_mistakes", [])

        # Difficulty topic detection — substring match in both directions
        is_difficulty_topic = any(
            d in combined_lower or any(word in d for word in combined_lower.split() if len(word) > 3)
            for d in difficulties
        )
        # Also treat low-mastery concepts as difficulty topics
        if not is_difficulty_topic and session.weak_concepts:
            for wc in session.weak_concepts:
                wc_label = str(wc.get("label", "")).lower()
                if wc_label and (wc_label in combined_lower or combined_lower in wc_label):
                    is_difficulty_topic = True
                    break

        is_strength_topic = any(
            s in combined_lower or any(word in s for word in combined_lower.split() if len(word) > 3)
            for s in strengths
        )

        # Only activate one of DIFFICULTY or STRENGTH — difficulty takes priority
        if is_difficulty_topic:
            active_skills.append("DIFFICULTY_TOPIC")
        elif is_strength_topic:
            active_skills.append("STRENGTH_TOPIC")

        # Learning style detection
        is_visual = any("visual" in s or "diagram" in s or "spatial" in s for s in style_signals)
        is_hands_on = any("hands" in s or "practical" in s or "doing" in s or "concrete" in s for s in style_signals)

        if is_visual:
            active_skills.append("VISUAL_LEARNER")
        elif is_hands_on:
            # Only add HANDS_ON if VISUAL not already added — avoid conflicting style skills
            active_skills.append("HANDS_ON_LEARNER")

        # Pace preference detection from notable_intentions
        wants_slow = any("slow" in i or "slower" in i or "more time" in i for i in intentions)
        wants_fast = any("fast" in i or "faster" in i or "skip" in i or "quick" in i for i in intentions)
        if wants_slow:
            active_skills.append("PACE_SLOW")
        elif wants_fast:
            active_skills.append("PACE_FAST")

        # Unresolved question surfacing — find one relevant to current subtopic
        if not hasattr(session, '_surfaced_unresolved'):
            session._surfaced_unresolved = set()

        for q in unresolved:
            q_words = [w for w in q.lower().split() if len(w) > 4]
            if (
                q not in session._surfaced_unresolved
                and any(w in combined_lower for w in q_words)
            ):
                # Temporarily customize the skill text with the actual question
                original_skill = TUTOR_SKILLS["SURFACE_UNRESOLVED"]
                TUTOR_SKILLS["SURFACE_UNRESOLVED"] = (
                    original_skill
                    + f' The specific unresolved question is: "{q}"'
                )
                active_skills.append("SURFACE_UNRESOLVED")
                session._surfaced_unresolved.add(q)
                break  # only one per chunk

        # Recurrent mistake detection — if current topic relates to a known mistake
        if recurrent_mistakes:
            recurrent_lower = [str(m).lower() for m in recurrent_mistakes]
            mistake_match = any(
                m in combined_lower or any(w in m for w in combined_lower.split() if len(w) > 3)
                for m in recurrent_lower
            )
            if mistake_match:
                active_skills.append("RECURRENT_MISTAKE")

    # ── Remove ENGAGEMENT_ADAPT if more specific profile skills were activated ──
    profile_specific_skills = {
        "DIFFICULTY_TOPIC", "STRENGTH_TOPIC", "VISUAL_LEARNER",
        "HANDS_ON_LEARNER", "PACE_SLOW", "PACE_FAST",
        "SURFACE_UNRESOLVED", "RECURRENT_MISTAKE"
    }
    if any(s in active_skills for s in profile_specific_skills):
        active_skills = [s for s in active_skills if s != "ENGAGEMENT_ADAPT"]

    # Build the composed system prompt
    system_prompt = _build_system_prompt(LECTURE_SYSTEM_PROMPT, active_skills)

    # Restore SURFACE_UNRESOLVED to its template form after use
    if "SURFACE_UNRESOLVED" in active_skills:
        TUTOR_SKILLS["SURFACE_UNRESOLVED"] = (
            "SKILL — UNRESOLVED QUESTION: This student had an open question "
            "from a previous session that relates to the current topic. "
            "Weave the answer into your explanation naturally without saying "
            "'you asked this before'. Just address it as part of the content."
        )

    context_parts = []
    if session.running_summary:
        context_parts.append(f"SUMMARY OF WHAT YOU'VE COVERED SO FAR:\n{session.running_summary}")

    # ── Persistent profile injection (every chunk, not just the first) ──
    profile_context = _build_profile_context(session)
    if profile_context:
        context_parts.append(profile_context)

    context_parts.append(f"CURRENT MAIN TOPIC: {topic_name}")
    if subtopic_name:
        context_parts.append(f"CURRENT SUBTOPIC TO EXPLAIN NOW: {subtopic_name}")
    else:
        context_parts.append("Explain this topic as a whole.")

    # ── Inject current slide content from SharedSessionStore ──
    try:
        from services.session_store import get_session_store
        store = get_session_store()
        ctx = store.get_session(session.session_id)
        if ctx and ctx.live.current_slide_content:
            slide_info = "CURRENT SLIDE CONTENT (base your explanation on this material):\n"
            if ctx.live.current_slide_title:
                slide_info += f"Slide title: {ctx.live.current_slide_title}\n"
            slide_info += ctx.live.current_slide_content
            context_parts.append(slide_info)
    except Exception as exc:
        logger.debug("Could not inject slide content: %s", exc)

    if session.is_first_chunk:
        context_parts.append("This is the BEGINNING of the session. Start with a brief warm greeting.")
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

    if active_skills:
        logger.info(f"Active skills for this chunk: {active_skills}")

    user_prompt = "\n\n".join(context_parts)

    # ── Build multi-turn conversation history ──
    conversation_history = _build_conversation_history(session, max_turns=3)

    start = time.time()
    lecture_text = await _call_ollama(
        system_prompt, user_prompt,
        temperature=0.7,
        conversation_history=conversation_history,
    )
    elapsed = round(time.time() - start, 2)

    logger.info(f"Lecture chunk generated in {elapsed}s for [{topic_name} > {subtopic_name}]")

    session.transcript.append({
        "role": "tutor",
        "text": lecture_text,
        "topic": topic_name,
        "subtopic": subtopic_name,
        "timestamp": time.time(),
    })
    if len(session.transcript) > 10:
        session.transcript = session.transcript[-10:]

    session.last_chunk_text = lecture_text
    session.last_chunk_subtopic = subtopic_name

    await _update_summary(session, lecture_text)

    is_finished = _advance(session)

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


async def answer_question(
    session_id: str,
    question: str,
    student_emotion: Optional[str] = None,
    intent: Optional[str] = None,
    intent_confidence: float = 0.0,
) -> dict:
    """
    Handle a student question mid-lecture.

    Behaviour varies by intent:
    - ``On-Topic Question``: Socratic method. Track attempt count; scaffold
      after two failed attempts.
    - ``Emotional-State``: Acknowledge emotion only. No Socratic questions.
    - ``Off-Topic Question``: Decline gracefully; return to lecture.
    - ``Unknown`` / no intent: Default to Socratic Q&A.

    Parameters
    ----------
    intent:
        Intent label from the classifier. Drives which skills are activated
        and which system prompt is used.
    intent_confidence:
        Classifier confidence. Stored on session for logging.
    """
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # Record intent
    if intent:
        session.last_intent = intent
        session.last_intent_confidence = intent_confidence

    # ── If the student is responding to a probe/teach-back, route to lecture ──
    # The student message is a response, not a question — hand off to the
    # lecture chunk generator which activates PROBE_RESPONSE_HANDLER.
    if session.awaiting_student_response:
        session.transcript.append({
            "role": "student",
            "text": question,
            "timestamp": time.time(),
            "is_probe_response": True,
            "probe_type": session.awaiting_response_type,
        })
        if len(session.transcript) > 10:
            session.transcript = session.transcript[-10:]
        return await generate_lecture_chunk(
            session_id,
            student_emotion=student_emotion,
            intent=intent,
            intent_confidence=intent_confidence,
        )

    prev_status = session.status

    # ── Route by intent ──────────────────────────────────────────────
    effective_intent = intent or "On-Topic Question"

    if effective_intent == "Emotional-State":
        return await handle_emotional_state(
            session_id,
            student_message=question,
            student_emotion=student_emotion,
        )

    if effective_intent == "Pace-Related":
        return await handle_pace_change(session_id, student_message=question)

    if effective_intent == "Off-Topic Question" and intent_confidence >= 0.65:
        off_topic_text = (
            f"That is a bit outside what we are covering right now. "
            f"Let us stay focused on {session.current_topic or 'the current topic'} — "
            f"feel free to ask me that after the session."
        )
        session.transcript.append({
            "role": "student", "text": question, "timestamp": time.time(),
        })
        session.transcript.append({
            "role": "tutor", "text": off_topic_text, "timestamp": time.time(),
            "is_off_topic_redirect": True,
        })
        if len(session.transcript) > 10:
            session.transcript = session.transcript[-10:]
        _sync_to_shared_store(session)
        return {
            "answer": off_topic_text,
            "intent": "Off-Topic Question",
            "topic": session.current_topic,
            "subtopic": session.current_subtopic,
            "progress": session.progress,
            "is_finished": session.status == "finished",
            "status": session.status,
            "inference_time": 0.0,
        }

    # ── Debugging/Code-Sharing — direct help, no Socratic ──────────
    if effective_intent == "Debugging/Code-Sharing":
        session.status = "answering"
        debug_skills: list[str] = ["DIRECT_DEBUG_HELP"]
        if student_emotion and student_emotion.lower() in ("confused", "surprise", "fear"):
            debug_skills.append("CONFUSION_DIAGNOSIS")
        system_prompt = _build_system_prompt(ANSWER_SYSTEM_PROMPT, debug_skills)

        context_parts = []
        if session.running_summary:
            context_parts.append(f"CONTEXT (what we've covered so far):\n{session.running_summary}")
        profile_context = _build_profile_context(session)
        if profile_context:
            context_parts.append(profile_context)
        context_parts.append(f"CURRENT TOPIC: {session.current_topic or 'N/A'}")
        if session.current_subtopic:
            context_parts.append(f"CURRENT SUBTOPIC: {session.current_subtopic}")
        context_parts.append(f"STUDENT'S CODE/ERROR: {question}")
        user_prompt = "\n\n".join(context_parts)
        conversation_history = _build_conversation_history(session, max_turns=3)

        start = time.time()
        answer_text = await _call_ollama(
            system_prompt, user_prompt,
            temperature=0.5,
            conversation_history=conversation_history,
        )
        elapsed = round(time.time() - start, 2)

        session.transcript.append({"role": "student", "text": question, "timestamp": time.time()})
        session.transcript.append({
            "role": "tutor", "text": answer_text,
            "topic": session.current_topic, "subtopic": session.current_subtopic,
            "timestamp": time.time(), "is_debug_answer": True,
        })
        if len(session.transcript) > 10:
            session.transcript = session.transcript[-10:]

        qa_text = f"Student debug request: {question}\nTutor fix: {answer_text}"
        await _update_summary(session, qa_text)
        session.status = prev_status if prev_status != "answering" else "lecturing"
        _sync_to_shared_store(session)

        return {
            "answer": answer_text,
            "intent": "Debugging/Code-Sharing",
            "topic": session.current_topic,
            "subtopic": session.current_subtopic,
            "progress": session.progress,
            "is_finished": session.status == "finished",
            "status": session.status,
            "inference_time": elapsed,
            "active_skills": debug_skills,
        }

    # ── On-Topic Question (default path) ────────────────────────────
    session.status = "answering"

    # Determine active skills based on attempt count and emotion
    qa_skills: list[str] = []

    if session.socratic_attempt_count >= 2:
        # Student has failed twice — scaffold instead of pure Socratic
        qa_skills.append("SOCRATIC_SCAFFOLD")
        session.socratic_attempt_count = 0  # reset after scaffolding
    else:
        qa_skills.append("SOCRATIC_GUARD")
        session.socratic_attempt_count += 1

    if student_emotion and student_emotion.lower() in ("confused", "surprise", "fear"):
        qa_skills.append("CONFUSION_DIAGNOSIS")

    # Profile-driven skills in Q&A context
    if session.student_profile_data:
        profile = session.student_profile_data
        style_signals = [str(s).lower() for s in profile.get("learning_style_signals", [])]
        is_visual = any("visual" in s or "diagram" in s for s in style_signals)
        is_hands_on = any("hands" in s or "concrete" in s for s in style_signals)
        if is_visual:
            qa_skills.append("VISUAL_LEARNER")
        elif is_hands_on:
            qa_skills.append("HANDS_ON_LEARNER")

    system_prompt = _build_system_prompt(ANSWER_SYSTEM_PROMPT, qa_skills)

    context_parts = []
    if session.running_summary:
        context_parts.append(f"CONTEXT (what we've covered so far):\n{session.running_summary}")

    # Persistent profile injection
    profile_context = _build_profile_context(session)
    if profile_context:
        context_parts.append(profile_context)

    context_parts.append(f"CURRENT TOPIC: {session.current_topic or 'N/A'}")
    if session.current_subtopic:
        context_parts.append(f"CURRENT SUBTOPIC: {session.current_subtopic}")

    # Inject current slide content
    try:
        from services.session_store import get_session_store
        store = get_session_store()
        ctx = store.get_session(session.session_id)
        if ctx and ctx.live.current_slide_content:
            slide_info = "CURRENT SLIDE CONTENT (use this to inform your answer):\n"
            if ctx.live.current_slide_title:
                slide_info += f"Slide title: {ctx.live.current_slide_title}\n"
            slide_info += ctx.live.current_slide_content
            context_parts.append(slide_info)
    except Exception:
        pass

    # Inject attempt count so the model knows how stuck the student is
    if session.socratic_attempt_count > 1:
        context_parts.append(
            f"NOTE: The student has attempted to answer this type of question "
            f"{session.socratic_attempt_count} time(s) without success. "
            f"Increase your scaffolding accordingly."
        )

    # Emotion-aware tone adaptation
    if student_emotion and student_emotion.lower() not in ("neutral", "unknown"):
        emotion_guidance = {
            "happy": "The student sounds engaged and positive. Match their energy.",
            "sad": "The student seems down. Be warm, supportive, and extra patient.",
            "angry": "The student sounds frustrated. Stay calm and validate their frustration.",
            "fear": "The student seems anxious. Be reassuring and break things into small steps.",
            "surprise": "The student seems surprised or confused. Acknowledge it and explain clearly.",
            "disgust": "The student seems displeased. Be empathetic and try a different angle.",
        }
        guidance = emotion_guidance.get(
            student_emotion.lower(),
            f"The student's emotional state is '{student_emotion}'. Adapt your tone to be supportive.",
        )
        context_parts.append(f"EMOTIONAL CONTEXT: {guidance}")

    context_parts.append(f"STUDENT'S QUESTION: {question}")

    user_prompt = "\n\n".join(context_parts)
    conversation_history = _build_conversation_history(session, max_turns=3)

    start = time.time()
    answer_text = await _call_ollama(
        system_prompt, user_prompt,
        temperature=0.65,
        conversation_history=conversation_history,
    )
    elapsed = round(time.time() - start, 2)

    session.transcript.append({"role": "student", "text": question, "timestamp": time.time()})
    session.transcript.append({
        "role": "tutor", "text": answer_text,
        "topic": session.current_topic, "subtopic": session.current_subtopic,
        "timestamp": time.time(), "is_answer": True,
    })
    if len(session.transcript) > 10:
        session.transcript = session.transcript[-10:]

    qa_text = f"Student asked: {question}\nTutor answered: {answer_text}"
    await _update_summary(session, qa_text)

    session.status = prev_status if prev_status != "answering" else "lecturing"
    _sync_to_shared_store(session)

    return {
        "answer": answer_text,
        "intent": effective_intent,
        "topic": session.current_topic,
        "subtopic": session.current_subtopic,
        "progress": session.progress,
        "is_finished": session.status == "finished",
        "status": session.status,
        "inference_time": elapsed,
        "active_skills": qa_skills,
    }


async def handle_emotional_state(
    session_id: str,
    student_message: str,
    student_emotion: Optional[str] = None,
) -> dict:
    """
    Respond to a student expressing an emotional state.

    Does NOT do Socratic questioning. Does NOT advance the topic pointer.
    Acknowledges the feeling, then asks if the student wants to continue,
    slow down, or take a break.

    Parameters
    ----------
    student_message:
        The raw student utterance classified as Emotional-State.
    student_emotion:
        Fused emotion label from FER/SER (optional). Used to make the
        acknowledgement more specific if available.
    """
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    prev_status = session.status
    session.status = "answering"

    system_prompt = _build_system_prompt(EMOTIONAL_SYSTEM_PROMPT, ["EMOTIONAL_ACKNOWLEDGEMENT"])

    context_parts = [
        f"CURRENT TOPIC: {session.current_topic or 'N/A'}",
        f"STUDENT'S MESSAGE: {student_message}",
    ]
    if student_emotion and student_emotion.lower() not in ("neutral", "unknown"):
        context_parts.append(
            f"DETECTED EMOTION (from facial/voice analysis): {student_emotion}. "
            "Reference this naturally if it matches what the student said."
        )

    user_prompt = "\n\n".join(context_parts)

    start = time.time()
    response_text = await _call_ollama(
        system_prompt, user_prompt, temperature=0.6
    )
    elapsed = round(time.time() - start, 2)

    session.transcript.append({"role": "student", "text": student_message, "timestamp": time.time()})
    session.transcript.append({
        "role": "tutor", "text": response_text,
        "topic": session.current_topic, "subtopic": session.current_subtopic,
        "timestamp": time.time(), "is_emotional_response": True,
    })
    if len(session.transcript) > 10:
        session.transcript = session.transcript[-10:]

    # Reset Socratic counter — emotional exchanges are not failed attempts
    session.socratic_attempt_count = 0

    session.status = prev_status if prev_status != "answering" else "lecturing"
    _sync_to_shared_store(session)

    return {
        "answer": response_text,
        "intent": "Emotional-State",
        "topic": session.current_topic,
        "subtopic": session.current_subtopic,
        "progress": session.progress,
        "is_finished": session.status == "finished",
        "status": session.status,
        "inference_time": elapsed,
    }


async def handle_pace_change(
    session_id: str,
    student_message: str,
    direction: Optional[str] = None,
) -> dict:
    """
    Respond to a student requesting a pace change and apply it to the session.

    Infers ``direction`` (``"slower"`` / ``"faster"``) from the student's
    message if not provided explicitly. Updates ``session.pace_modifier``
    so the SharedSessionStore reflects the new pace for other subsystems.

    Parameters
    ----------
    student_message:
        The raw student utterance classified as Pace-Related.
    direction:
        Optional explicit direction. If ``None``, the function infers it
        from keywords in ``student_message``.
    """
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # ── Infer direction if not provided ──────────────────────────────
    if direction is None:
        lower = student_message.lower()
        slower_keywords = {"slow", "slower", "slow down", "too fast", "wait", "hold on", "again", "repeat"}
        faster_keywords = {"faster", "speed up", "hurry", "quick", "quicker", "move on", "skip", "next"}
        if any(k in lower for k in slower_keywords):
            direction = "slower"
        elif any(k in lower for k in faster_keywords):
            direction = "faster"
        else:
            direction = "slower"  # default: assume slow-down when ambiguous

    # ── Apply pace modifier ───────────────────────────────────────────
    if direction == "slower":
        session.pace_modifier = max(session.pace_modifier - 1, -3)
    else:
        session.pace_modifier = min(session.pace_modifier + 1, 3)

    prev_status = session.status
    session.status = "answering"

    # Build a direction-aware pace instruction for the prompt
    direction_instruction = (
        "The student wants to slow down. Acknowledge this and confirm you will take it slower."
        if direction == "slower"
        else "The student wants to speed up. Acknowledge this and confirm you will move faster."
    )

    context_parts = [
        f"CURRENT TOPIC: {session.current_topic or 'N/A'}",
        f"PACE DIRECTION: {direction_instruction}",
        f"STUDENT'S MESSAGE: {student_message}",
    ]
    user_prompt = "\n\n".join(context_parts)

    start = time.time()
    response_text = await _call_ollama(
        _build_system_prompt(PACE_SYSTEM_PROMPT, ["PACE_ACKNOWLEDGEMENT"]),
        user_prompt,
        temperature=0.4,
    )
    elapsed = round(time.time() - start, 2)

    session.transcript.append({"role": "student", "text": student_message, "timestamp": time.time()})
    session.transcript.append({
        "role": "tutor", "text": response_text,
        "topic": session.current_topic, "subtopic": session.current_subtopic,
        "timestamp": time.time(), "is_pace_response": True, "pace_direction": direction,
    })
    if len(session.transcript) > 10:
        session.transcript = session.transcript[-10:]

    session.status = prev_status if prev_status != "answering" else "lecturing"
    _sync_to_shared_store(session)

    logger.info(
        "Pace change applied for session %s: direction=%s modifier=%d",
        session_id, direction, session.pace_modifier,
    )

    return {
        "answer": response_text,
        "intent": "Pace-Related",
        "pace_direction": direction,
        "pace_modifier": session.pace_modifier,
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
        conversation_history = _build_conversation_history(session, max_turns=2)
        start = time.time()
        response_text = await _call_ollama(
            REPHRASE_SYSTEM_PROMPT, user_prompt,
            temperature=0.65,
            conversation_history=conversation_history,
        )
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
        # Low temperature: this is factual compression, not generation.
        # Higher token budget: the summary itself can be up to 300 words.
        session.running_summary = await _call_ollama(
            SUMMARIZE_SYSTEM_PROMPT, prompt, temperature=0.2, num_predict=400
        )
    except Exception as e:
        logger.warning(f"Summary compression failed, appending raw: {e}")
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