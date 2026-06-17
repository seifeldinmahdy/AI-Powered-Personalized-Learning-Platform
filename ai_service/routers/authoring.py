"""AI authoring aids for admins (LLM proposes; admin reviews/edits)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/authoring", tags=["authoring"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_client():
    for p in (str(_PROJECT_ROOT / "course_pathway" / "src"),):
        if p not in sys.path:
            sys.path.insert(0, p)
    from pathway.llm.naming import OllamaClient  # type: ignore
    return OllamaClient(
        host=os.getenv("OLLAMA_HOST"),
        model=os.getenv("OLLAMA_STRONG_MODEL", "gpt-oss:120b"),
        api_key=os.getenv("OLLAMA_API_KEY", ""),
    )


class CourseDescriptionRequest(BaseModel):
    title: str
    current_description: str = ""
    topics: list[str] = Field(default_factory=list)


class CourseDescriptionResponse(BaseModel):
    description: str
    source: str  # "llm" | "fallback"


@router.post("/course-description", response_model=CourseDescriptionResponse)
async def draft_course_description(req: CourseDescriptionRequest):
    """Draft a course description for the admin to review/edit.

    Falls back to a deterministic template when no LLM key is configured, so the
    endpoint always returns something usable.
    """
    if not os.getenv("OLLAMA_API_KEY", ""):
        topics = ", ".join(req.topics[:6]) if req.topics else "the course's core concepts"
        return CourseDescriptionResponse(
            description=(f"{req.title}: a course covering {topics}. "
                         "Learners progress through guided sessions with hands-on labs and "
                         "problem sets, ending in a capstone project."),
            source="fallback",
        )
    prompt = (
        "Write a concise, accurate course description (2-4 sentences) for the course "
        f'titled "{req.title}". '
        + (f"It covers: {', '.join(req.topics[:12])}. " if req.topics else "")
        + (f'Improve on this draft: "{req.current_description}". ' if req.current_description else "")
        + "Return ONLY the description text, no preamble."
    )
    try:
        text = _get_client().chat([{"role": "user", "content": prompt}], temperature=0.4)
        return CourseDescriptionResponse(description=(text or "").strip(), source="llm")
    except Exception as e:
        logger.warning("course-description draft failed: %s", e)
        return CourseDescriptionResponse(
            description=req.current_description or f"{req.title}.", source="fallback",
        )
