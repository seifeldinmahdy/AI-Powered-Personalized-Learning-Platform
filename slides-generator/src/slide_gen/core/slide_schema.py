"""Slide instruction schema definitions."""

from enum import Enum
from typing import Literal, Optional, Any


from pydantic import BaseModel, Field


class Layout(str, Enum):
    """Slide layout type.

    Content_Visual   — text bullets alongside a diagram/chart
    List_View        — text-only bullets, no visual element
    Code_Main        — code block is the primary element
    """
    CONTENT_VISUAL   = "Content_Visual"
    LIST_VIEW        = "List_View"
    CODE_MAIN        = "Code_Main"


class SlideType(str, Enum):
    """Type of slide in the presentation deck."""
    TITLE = "Title"              # Opening slide
    AGENDA = "Agenda"            # Table of contents
    SECTION_OPENER = "Section"   # Section divider
    CONTENT = "Content"          # Normal content slide
    SUMMARY = "Summary"          # Section summary


class HighlightType(str, Enum):
    """Text highlight styling - semantic types for the frontend to render."""
    NONE = "none"              # Regular text, no special styling
    CODE = "code"              # Inline code: monospace font
    ATTENTION = "attention"    # Important/warning: bold, red/orange
    DEFINITION = "definition"  # Term being defined: bold, blue
    EXAMPLE = "example"        # Example text: italic
    KEY_CONCEPT = "key_concept"  # Core concept: bold


class CodeBlock(BaseModel):
    """Code block for displaying programming examples."""

    language: str = Field(
        description="Programming language (e.g., 'python', 'javascript', 'java')"
    )
    code: str = Field(
        description="The actual code content with proper indentation"
    )
    output: Optional[str] = Field(
        default=None,
        description="Demonstrative expected console output, shown when the user "
                    "'runs' the snippet. LLM-generated, NOT executed (no sandbox)."
    )
    runnable: bool = Field(
        default=False,
        description="True when an output is available, so the frontend renders a Run button."
    )
    generated: bool = Field(
        default=False,
        description="True when the snippet was synthesized by the LLM (no literal "
                    "code in the source), False when extracted and only validated/augmented."
    )


class VisualTemplate(BaseModel):
    """Visual instruction using template system."""
    
    template: str = Field(
        description="Template ID (e.g., 'linear_chain', 'flowchart', 'bar_chart')"
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Template-specific parameters"
    )


class ContentItem(BaseModel):
    """Single content item (bullet point or definition) on a slide."""
    
    text: str = Field(
        description="The text content of the bullet point, or the description for a definition"
    )
    highlight_type: HighlightType = Field(
        default=HighlightType.NONE,
        description="How to style this content item"
    )
    term: Optional[str] = Field(
        default=None,
        description="When set, this item is a definition: term is rendered in bold/accent color, text is the description"
    )


class SlideInstruction(BaseModel):
    """Complete slide instruction output from the AI."""
    
    slide_type: SlideType = Field(
        default=SlideType.CONTENT,
        description="Type of slide (Title, Agenda, Section, Content, Summary)"
    )
    slide_number: Optional[int] = Field(
        default=None,
        description="Position in the final deck (set by assembler)"
    )
    layout: Layout = Field(
        description="Slide layout type"
    )
    title: str = Field(
        description="Slide title"
    )
    body_content: list[ContentItem] = Field(
        default_factory=list,
        description="List of bullet points/content items"
    )
    visual: Optional[VisualTemplate] = Field(
        default=None,
        description="Visual template instruction"
    )
    code_block: Optional[CodeBlock] = Field(
        default=None,
        description="Optional code block for programming examples"
    )
    alt_text: Optional[str] = Field(
        default=None,
        description="Accessibility text describing visuals"
    )
    mastery_metadata: Optional["SlideMasteryMetadata"] = Field(
        default=None,
        description="Per-slide mastery provenance — how mastery was derived for this slide"
    )


class SlideMasteryMetadata(BaseModel):
    """Per-slide mastery provenance — tracks how mastery was derived."""
    mastery_used: Literal["Novice", "Intermediate", "Expert"]
    global_mastery: Literal["Novice", "Intermediate", "Expert"]
    topic_score: float | None = None
    topic_matched: str | None = None
    mastery_source: Literal["topic_performance", "global_fallback"]


# Update forward ref
SlideInstruction.model_rebuild()



# List of valid template IDs for validation
VALID_TEMPLATES = [
    # Data Structures (Graphviz)
    "linear_chain", "binary_tree", "general_tree", "stack", "queue", "graph",
    # Flow Diagrams (Mermaid)
    "flowchart", "cycle",
    # Comparison
    "comparison",
    # Quantitative
    "bar_chart",
    # Conceptual (LLM enrichment dispatches to concept_box/comparison/analogy_diagram)
    "conceptual",
    # Conceptual sub-types (rendered via _enriched_template key in params)
    "concept_box",
    # Architectural — layered_stack merged into architecture_diagram (style='layered')
    "architecture_diagram",
]

