"""Student profile schema definitions."""

from enum import Enum

from pydantic import BaseModel, Field


class MasteryLevel(str, Enum):
    """Student mastery level for content adaptation."""
    NOVICE = "Novice"
    INTERMEDIATE = "Intermediate"
    EXPERT = "Expert"


class CompositionMode(str, Enum):
    """Slide composition style preference."""
    VISUAL_HEAVY = "Visual_Heavy"
    TEXT_HEAVY = "Text_Heavy"
    BALANCED = "Balanced"


class LanguageProficiency(str, Enum):
    """English language proficiency level."""
    ELEMENTARY = "Elementary"
    INTERMEDIATE = "Intermediate"
    ADVANCED = "Advanced"
    NATIVE = "Native"


class StudentProfile(BaseModel):
    """Complete student profile for personalized slide generation."""
    
    mastery_level: MasteryLevel = Field(
        description="Student's current knowledge level"
    )
    composition_mode: CompositionMode = Field(
        description="Preferred slide composition style"
    )
    language_proficiency: LanguageProficiency = Field(
        description="English language proficiency"
    )
    screen_reader_active: bool = Field(
        default=False,
        description="Whether accessibility features are needed"
    )
    
    def to_prompt_dict(self) -> dict[str, str]:
        """Convert profile to dictionary for prompt formatting."""
        return {
            "mastery_level": self.mastery_level.value,
            "composition_mode": self.composition_mode.value,
            "language_proficiency": self.language_proficiency.value,
            "screen_reader_active": str(self.screen_reader_active),
        }
