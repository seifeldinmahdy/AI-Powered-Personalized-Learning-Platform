"""Unified student context shared across course_pathway and slides-generator.

This is the single source of truth for student context in the platform.
Both the pathway generator and the slide orchestrator read from this module,
ensuring zero divergence between the two systems.
"""

from __future__ import annotations

import time
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class StudentProfileState(BaseModel):
    """Slow-changing global fields. Maps to Redis key: session:{id}:profile"""
    model_config = {"extra": "forbid"}

    # TODO: Populate from profile DB once connected. Defaults are temporary fallbacks.
    student_id: str = ""
    course_id: str = ""
    mastery_level: Literal["Novice", "Intermediate", "Expert"] = "Novice"
    composition_mode: Literal["visual_heavy", "text_heavy", "balanced"] = "balanced"
    language_proficiency: Literal["Elementary", "Intermediate", "Advanced", "Native"] = "Intermediate"
    
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    topic_performance: dict[str, float] = Field(default_factory=dict)
    incorrectly_answered: list[str] = Field(default_factory=list)
    use_synthetic_context: bool = False
    course_intent: str = ""
    student_profile_summary: str = Field(default="", description="Short text summary of the student's learning profile")

    def is_fully_hydrated(self) -> bool:
        """Return True if real profile data has been populated from the database."""
        return bool(self.student_id and self.course_id and self.mastery_level)


class LiveSessionState(BaseModel):
    """Fast-changing real-time fields. Maps to Redis key: session:{id}:live"""
    model_config = {"extra": "forbid"}

    session_id: str = Field(default="", description="Active session identifier")
    
    current_slide_index: int = Field(default=0, description="Current slide being viewed")
    current_slide_title: str = Field(default="", description="Title of the current slide")
    current_topic: str = Field(default="", description="Topic currently being taught")
    current_subtopic: str = Field(default="", description="Subtopic currently being taught")
    
    running_summary: str = Field(default="", description="Summarized context of the lesson so far")
    
    tutor_transcript: list[dict] = Field(
        default_factory=list, 
        description="Rolling window of the last 10 conversational turns with the tutor"
    )

    fused_emotion: str = Field(default="", description="Current resolved student emotion")
    fused_emotion_confidence: float = Field(default=0.0, description="Confidence score of the fused emotion prediction")
    
    pace_modifier: int = Field(
        default=0, 
        ge=-50, 
        le=50, 
        description="Pace adjustment factor for TTS and generation. Bounded between -50 and +50."
    )
    
    # CONTRACT: Writers MUST explicitly update this field via time.time() prior to serializing 
    # to Redis to ensure staleness detection works. Default factory only fires on object creation.
    last_updated_at: float = Field(default_factory=time.time, description="Unix timestamp of last write to cache")

    @field_validator('tutor_transcript')
    @classmethod
    def cap_transcript(cls, v):
        """Enforce strict 10-turn cap to prevent unbounded Redis/Prompt growth."""
        return v[-10:] if len(v) > 10 else v


class UnifiedStudentContext(BaseModel):
    """Composed wrapper for Python-side convenience."""
    profile: StudentProfileState
    live: LiveSessionState

    def to_pathway_context(self):
        """Convert to the pathway generator's StudentContext schema."""
        import sys
        from pathlib import Path

        course_pathway_src = str(
            Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src"
        )
        if course_pathway_src not in sys.path:
            sys.path.insert(0, course_pathway_src)

        from pathway.models.schemas import StudentContext

        return StudentContext(
            student_id=self.profile.student_id,
            course_id=self.profile.course_id,
            mastery_level=self.profile.mastery_level,
            composition_mode=self.profile.composition_mode,
            language_proficiency=self.profile.language_proficiency,
            strengths=self.profile.strengths,
            weaknesses=self.profile.weaknesses,
            topic_performance=self.profile.topic_performance,
            incorrectly_answered=self.profile.incorrectly_answered,
            use_synthetic_context=self.profile.use_synthetic_context,
            course_intent=self.profile.course_intent,
        )

    def to_slide_profile(self):
        """Convert to the slides-generator's StudentProfile schema."""
        import sys
        from pathlib import Path

        slides_src = str(
            Path(__file__).resolve().parent.parent.parent
            / "slides-generator"
            / "src"
        )
        if slides_src not in sys.path:
            sys.path.insert(0, slides_src)

        from slide_gen.core.profile_schema import (
            CompositionMode,
            LanguageProficiency,
            MasteryLevel,
            StudentProfile,
        )

        mode_map = {
            "visual_heavy": CompositionMode.VISUAL_HEAVY,
            "text_heavy": CompositionMode.TEXT_HEAVY,
            "balanced": CompositionMode.BALANCED,
        }
        mastery_map = {
            "Novice": MasteryLevel.NOVICE,
            "Intermediate": MasteryLevel.INTERMEDIATE,
            "Expert": MasteryLevel.EXPERT,
        }
        lang_map = {
            "Elementary": LanguageProficiency.ELEMENTARY,
            "Intermediate": LanguageProficiency.INTERMEDIATE,
            "Advanced": LanguageProficiency.ADVANCED,
            "Native": LanguageProficiency.NATIVE,
        }

        return StudentProfile(
            mastery_level=mastery_map[self.profile.mastery_level],
            composition_mode=mode_map[self.profile.composition_mode],
            language_proficiency=lang_map[self.profile.language_proficiency],
        )

    def to_slides_prompt_dict(self) -> dict[str, str]:
        """Flatten profile state for prompt injection into the slides pipeline."""
        mode_display = {
            "visual_heavy": "Visual_Heavy",
            "text_heavy": "Text_Heavy",
            "balanced": "Balanced",
        }
        return {
            "mastery_level": self.profile.mastery_level,
            "composition_mode": mode_display.get(self.profile.composition_mode, "Balanced"),
            "language_proficiency": self.profile.language_proficiency,
        }


def get_mvp_student_context(
    student_id: str = "mvp_student_001",
    course_id: str = "pythonlearn",
) -> UnifiedStudentContext:
    """Return the hardcoded MVP context: Novice / Visual_Heavy / Elementary."""
    profile = StudentProfileState(
        student_id=student_id,
        course_id=course_id,
        mastery_level="Novice",
        composition_mode="visual_heavy",
        language_proficiency="Elementary",
        strengths=[],
        weaknesses=[],
        topic_performance={},
        incorrectly_answered=[],
        use_synthetic_context=False,
        course_intent="Introduction to Programming with Python",
    )
    live = LiveSessionState()
    return UnifiedStudentContext(profile=profile, live=live)
