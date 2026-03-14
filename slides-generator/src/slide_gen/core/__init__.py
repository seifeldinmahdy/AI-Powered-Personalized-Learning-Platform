"""Core schemas for slide generation."""

from slide_gen.core.profile_schema import (
    CompositionMode,
    LanguageProficiency,
    MasteryLevel,
    StudentProfile,
)
from slide_gen.core.slide_schema import (
    CodeBlock,
    ContentItem,
    HighlightType,
    Layout,
    SlideInstruction,
    VisualTemplate,
    VALID_TEMPLATES,
)

__all__ = [
    "MasteryLevel",
    "CompositionMode",
    "LanguageProficiency",
    "StudentProfile",
    "Layout",
    "HighlightType",
    "ContentItem",
    "CodeBlock",
    "VisualTemplate",
    "SlideInstruction",
    "VALID_TEMPLATES",
]
