"""Pydantic schemas for post-course survey AI summarization."""

from __future__ import annotations
from pydantic import BaseModel


class SurveySummarizeRequest(BaseModel):
    course_id: int
    text_answers: list[str]
    # {question_prompt: {1: count, 2: count, 3: count, 4: count, 5: count}}
    likert_distributions: dict[str, dict]
    clo_labels: list[str] = []


class SurveySummaryResult(BaseModel):
    recurring_themes: list[dict] = []   # [{theme: str, count: int}]
    sentiment: str = "mixed"            # positive | mixed | negative
    top_praise: list[str] = []
    top_complaints: list[str] = []
    per_clo_perception: dict[str, str] = {}  # {clo_text: sentiment_description}
