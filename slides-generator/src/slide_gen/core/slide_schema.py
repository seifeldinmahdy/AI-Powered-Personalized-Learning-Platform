"""Slide instruction schema definitions."""

from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class Layout(str, Enum):
    """Slide layout type."""
    CONTENT_VISUAL = "Content_Visual"
    LIST_VIEW = "List_View"
    CODE_MAIN = "Code_Main"


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
    



# List of valid template IDs for validation
VALID_TEMPLATES = [
    # Graphviz
    "linear_chain", "binary_tree", "stack", "queue", "graph", "layers",
    # Mermaid
    "flowchart", "sequence", "cycle", "comparison", "timeline", "process_flow",
    # Matplotlib
    "bar_chart", "pie_chart", "grid", "line_chart", "venn",
    # Fallback (for abstract concepts)
    "concept_box", "info_card", "definition_box",
]
