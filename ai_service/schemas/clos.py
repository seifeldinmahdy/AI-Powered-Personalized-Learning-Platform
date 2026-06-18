"""Pydantic schemas for CLO (Course Learning Outcome) AI-assisted authoring."""

from __future__ import annotations
from pydantic import BaseModel


class CLODraft(BaseModel):
    code: str
    text: str
    bloom_level: str
    concept_ids: list[str] = []
    order: int = 0


class CLOSuggestRequest(BaseModel):
    course_title: str
    course_description: str
    existing_concepts: list[dict]  # [{id: str, label: str}]


class CLOSuggestResponse(BaseModel):
    drafts: list[CLODraft]
    suggested_concepts: list[str] = []
