"""Unified student context shared across course_pathway and slides-generator.

This is the single source of truth for student context in the platform.
Both the pathway generator and the slide orchestrator read from this module,
ensuring zero divergence between the two systems.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UnifiedStudentContext(BaseModel):
    """Shared student context consumed by both pathway and slide generation."""

    student_id: str = Field(..., description="Unique student identifier")
    course_id: str = Field(..., description="Course identifier (matches ChromaDB 'course' metadata)")
    mastery_level: Literal["Novice", "Intermediate", "Expert"] = Field(
        ..., description="Overall mastery tier from the placement test"
    )
    composition_mode: Literal["visual_heavy", "text_heavy", "balanced"] = Field(
        default="balanced", description="Slide composition style preference"
    )
    language_proficiency: Literal["Elementary", "Intermediate", "Advanced", "Native"] = Field(
        default="Intermediate", description="English language proficiency"
    )
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    topic_performance: dict[str, float] = Field(default_factory=dict)
    incorrectly_answered: list[str] = Field(default_factory=list)
    use_synthetic_context: bool = False
    course_intent: str = ""

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
            student_id=self.student_id,
            course_id=self.course_id,
            mastery_level=self.mastery_level,
            composition_mode=self.composition_mode,
            language_proficiency=self.language_proficiency,
            strengths=self.strengths,
            weaknesses=self.weaknesses,
            topic_performance=self.topic_performance,
            incorrectly_answered=self.incorrectly_answered,
            use_synthetic_context=self.use_synthetic_context,
            course_intent=self.course_intent,
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
            mastery_level=mastery_map[self.mastery_level],
            composition_mode=mode_map[self.composition_mode],
            language_proficiency=lang_map[self.language_proficiency],
        )

    def to_prompt_dict(self) -> dict[str, str]:
        """Return the dict used by the content_specialist format_input()."""
        mode_display = {
            "visual_heavy": "Visual_Heavy",
            "text_heavy": "Text_Heavy",
            "balanced": "Balanced",
        }
        return {
            "mastery_level": self.mastery_level,
            "composition_mode": mode_display.get(self.composition_mode, "Balanced"),
            "language_proficiency": self.language_proficiency,
        }


def get_mvp_student_context(
    student_id: str = "mvp_student_001",
    course_id: str = "pythonlearn",
) -> UnifiedStudentContext:
    """Return the hardcoded MVP context: Novice / Visual_Heavy / Elementary."""
    return UnifiedStudentContext(
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
