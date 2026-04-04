"""
Tutor Session Service — AI-powered private tutor using Ollama.

Manages session state, recursive context summarization, topic progression,
and question-answering with full context injection.
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

# ── System prompts ──
LECTURE_SYSTEM_PROMPT = """\
You are Dr. Nova, an expert AI tutor giving a private one-on-one lecture.

RULES:
- Speak naturally as if talking to a student face-to-face.
- Explain the CURRENT TOPIC clearly in 2-3 short paragraphs.
- Use simple analogies and real-world examples.
- Do NOT use markdown formatting, bullet points, or headers — your output will be spoken aloud via TTS.
- Do NOT greet or introduce yourself unless this is the very first chunk of the session.
- End with a brief transition sentence leading into the next subtopic if there is one.
- Be concise but thorough. Aim for about 60-90 seconds of speech.
"""

SUMMARIZE_SYSTEM_PROMPT = """\
You are a context compression assistant. Given a running summary and the latest lecture content,
produce a concise merged summary that captures ALL key points covered so far.
Keep it under 300 words. Do not add opinions or new information.
"""

ANSWER_SYSTEM_PROMPT = """\
You are Dr. Nova, an expert AI tutor. A student has asked a question during your lecture.

RULES:
- Answer the question clearly and concisely (1-2 paragraphs).
- Use the provided context (what you've covered so far and the current topic) to give a relevant answer.
- Do NOT use markdown formatting — your output will be spoken aloud via TTS.
- After answering, add a brief sentence to transition back to the lecture.
"""


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
    voice: str = "en-US-JennyNeural"
    is_first_chunk: bool = True
    created_at: float = field(default_factory=time.time)

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
            "num_predict": 1024,
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


# ── Public API ──

def create_session(
    topics: List[dict],
    voice: str = "en-US-JennyNeural",
    session_id: Optional[str] = None,
) -> TutorSession:
    """Create a new tutoring session."""
    sid = session_id or str(uuid.uuid4())
    session = TutorSession(
        session_id=sid,
        topics=topics,
        voice=voice,
        status="idle",
    )
    _sessions[sid] = session
    logger.info(f"Session {sid} created with {len(topics)} topics")
    return session


def get_session(session_id: str) -> Optional[TutorSession]:
    """Retrieve a session by ID."""
    return _sessions.get(session_id)


async def generate_lecture_chunk(session_id: str) -> dict:
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
        session.is_first_chunk = False

    # Look ahead to tell the model what's next
    next_item = _peek_next(session)
    if next_item:
        context_parts.append(f"NEXT UP AFTER THIS: {next_item}")
    else:
        context_parts.append("This is the LAST subtopic. Wrap up with a brief conclusion.")

    user_prompt = "\n\n".join(context_parts)

    # Call Ollama
    start = time.time()
    lecture_text = await _call_ollama(LECTURE_SYSTEM_PROMPT, user_prompt)
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

    # Recursively update running summary
    await _update_summary(session, lecture_text)

    # Advance to next subtopic/topic
    is_finished = _advance(session)

    return {
        "text": lecture_text,
        "topic": topic_name,
        "subtopic": subtopic_name,
        "progress": session.progress,
        "is_finished": is_finished,
        "status": session.status,
        "inference_time": elapsed,
    }


async def answer_question(session_id: str, question: str) -> dict:
    """
    Handle a student question mid-lecture.
    Injects the question + full context, generates an answer.
    """
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    prev_status = session.status
    session.status = "answering"

    context_parts = []
    if session.running_summary:
        context_parts.append(f"CONTEXT (what we've covered so far):\n{session.running_summary}")
    context_parts.append(f"CURRENT TOPIC: {session.current_topic or 'N/A'}")
    if session.current_subtopic:
        context_parts.append(f"CURRENT SUBTOPIC: {session.current_subtopic}")
    context_parts.append(f"STUDENT'S QUESTION: {question}")

    user_prompt = "\n\n".join(context_parts)

    start = time.time()
    answer_text = await _call_ollama(ANSWER_SYSTEM_PROMPT, user_prompt)
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

    return {
        "answer": answer_text,
        "topic": session.current_topic,
        "subtopic": session.current_subtopic,
        "progress": session.progress,
        "is_finished": session.status == "finished",
        "status": session.status,
        "inference_time": elapsed,
    }


def stop_session(session_id: str) -> bool:
    """Stop a session early."""
    session = _sessions.get(session_id)
    if session:
        session.status = "finished"
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
