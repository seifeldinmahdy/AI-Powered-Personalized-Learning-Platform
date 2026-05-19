"""
Validation Layer — Component 6 of the presentation pipeline.

Post-processing validation applied to the assembled deck:
1. Definition Registry: Suppress duplicate DEFINE tags across the session
2. Required field checks: Every slide must have title, layout, slide_type
3. Fallback logic: Empty body → generate placeholder
4. Visual validation: Bad visual params → strip visual, revert layout
5. Alt-text enforcement: If screen_reader_active and visual present → ensure alt_text
"""

from slide_gen.core.slide_schema import (
    ContentItem,
    HighlightType,
    Layout,
    SlideInstruction,
    SlideType,
    VALID_TEMPLATES,
)
from slide_gen.core.profile_schema import StudentProfile
from slide_gen.agents.accessibility import generate_alt_text


class DefinitionRegistry:
    """
    Tracks which terms have been defined within a session.

    On duplicate DEFINE, converts the item to a recall bullet
    so that the student isn't shown the same definition twice.
    """

    def __init__(self):
        self._defined_terms: set[str] = set()

    def is_defined(self, term: str) -> bool:
        """Check if a term has already been defined."""
        return term.lower().strip() in self._defined_terms

    def register(self, term: str) -> None:
        """Mark a term as defined."""
        self._defined_terms.add(term.lower().strip())

    def process_slide(self, slide: SlideInstruction) -> SlideInstruction:
        """
        Process a slide's body content, suppressing duplicate definitions.

        First occurrence: keep as definition, register the term.
        Subsequent: convert to a recall bullet ("Recall: [term] — ...")
        """
        if slide.slide_type != SlideType.CONTENT:
            return slide

        new_body = []
        for item in slide.body_content:
            if item.term and item.highlight_type == HighlightType.DEFINITION:
                if self.is_defined(item.term):
                    # Convert to recall bullet
                    new_body.append(ContentItem(
                        text=f"Recall: {item.term} — {item.text}",
                        highlight_type=HighlightType.KEY_CONCEPT,
                        term=None,
                    ))
                else:
                    # First time — keep and register
                    self.register(item.term)
                    new_body.append(item)
            else:
                new_body.append(item)

        slide.body_content = new_body
        return slide


def _validate_required_fields(slide: SlideInstruction) -> SlideInstruction:
    """Ensure every slide has required fields with valid values."""
    # Title fallback
    if not slide.title or not slide.title.strip():
        slide.title = "Untitled Slide"

    # Body fallback: content slides must have at least 1 item
    if slide.slide_type == SlideType.CONTENT and not slide.body_content:
        slide.body_content = [
            ContentItem(
                text="Content could not be generated for this section.",
                highlight_type=HighlightType.ATTENTION,
            )
        ]

    return slide


def _validate_visual(slide: SlideInstruction) -> SlideInstruction:
    """
    Validate that visual template + params are coherent.

    If the visual template is invalid or params are missing,
    strip the visual and revert layout:
      - If equations are present → Equation_Focus
      - Otherwise              → List_View
    """
    if slide.visual is None:
        return slide

    template = slide.visual.template
    params = slide.visual.params

    # Determine the correct fallback layout
    has_math = bool(slide.equation_block)
    fallback_layout = Layout.EQUATION_FOCUS if has_math else Layout.LIST_VIEW

    # Check template ID is valid
    if template not in VALID_TEMPLATES and template not in (
        "layers", "process_flow", "sequence", "timeline",
        "line_chart", "venn", "info_card", "definition_box",
    ):
        print(f"    ⚠ Invalid template '{template}' — stripping visual")
        slide.visual = None
        slide.layout = fallback_layout
        return slide

    # Check params is a non-empty dict
    if not params or not isinstance(params, dict):
        print(f"    ⚠ Empty params for '{template}' — stripping visual")
        slide.visual = None
        slide.layout = fallback_layout
        return slide

    return slide


def _enforce_alt_text(
    slide: SlideInstruction,
    screen_reader_active: bool,
) -> SlideInstruction:
    """
    Enforce accessibility: if screen reader is active and visual is present,
    ensure alt_text is generated.
    """
    if not screen_reader_active:
        return slide

    if slide.visual is not None and not slide.alt_text:
        slide.alt_text = generate_alt_text(
            template_id=slide.visual.template,
            params=slide.visual.params,
            slide_title=slide.title,
            screen_reader_active=True,
        )

    return slide


def validate_deck(
    deck: list[SlideInstruction],
    profile: StudentProfile,
) -> list[SlideInstruction]:
    """
    Run the full validation layer on the assembled deck.

    Applies:
    1. Definition Registry (duplicate suppression)
    2. Required field checks
    3. Visual validation
    4. Alt-text enforcement

    Args:
        deck: The assembled slide deck
        profile: Student profile (for accessibility flags)

    Returns:
        Validated and cleaned deck
    """
    registry = DefinitionRegistry()
    validated = []

    for slide in deck:
        # 1. Definition Registry
        slide = registry.process_slide(slide)

        # 2. Required fields
        slide = _validate_required_fields(slide)

        # 3. Visual validation
        slide = _validate_visual(slide)

        # 4. Alt-text enforcement
        slide = _enforce_alt_text(slide, profile.screen_reader_active)

        validated.append(slide)

    return validated
