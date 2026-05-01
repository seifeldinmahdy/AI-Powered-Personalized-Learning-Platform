"""
Structural Slides — Stage 2 of the presentation pipeline.

Generates non-content slides from the DocumentPlan:
- Title slide (opening)
- Agenda slide (table of contents)
- Section divider slides
"""

from slide_gen.core.document_plan import DocumentPlan
from slide_gen.core.slide_schema import (
    ContentItem,
    HighlightType,
    Layout,
    SlideInstruction,
    SlideType,
)


def generate_title_slide(plan: DocumentPlan) -> SlideInstruction:
    """
    Generate the opening title slide.

    Args:
        plan: The document plan with title and sections

    Returns:
        Title slide instruction
    """
    return SlideInstruction(
        slide_type=SlideType.TITLE,
        layout=Layout.CONTENT_VISUAL,
        title=plan.title,
        body_content=[],
        visual=None,
        code_block=None,
        alt_text=None,
    )


def generate_agenda_slide(plan: DocumentPlan) -> SlideInstruction:
    """
    Generate the agenda/table-of-contents slide.

    Lists all section titles as bullet points.

    Args:
        plan: The document plan with sections

    Returns:
        Agenda slide instruction
    """
    body = [
        ContentItem(text=title, highlight_type=HighlightType.NONE)
        for title in plan.section_titles
    ]

    return SlideInstruction(
        slide_type=SlideType.AGENDA,
        layout=Layout.LIST_VIEW,
        title="What We'll Cover",
        body_content=body,
        visual=None,
        code_block=None,
        alt_text=None,
    )


def generate_section_divider(
    section_title: str,
    section_index: int,
    total_sections: int,
) -> SlideInstruction:
    """
    Generate a section divider slide.

    Args:
        section_title: Title of the section
        section_index: 0-based index of the section
        total_sections: Total number of sections

    Returns:
        Section divider slide instruction
    """
    subtitle = f"Section {section_index + 1} of {total_sections}"

    return SlideInstruction(
        slide_type=SlideType.SECTION_OPENER,
        layout=Layout.CONTENT_VISUAL,
        title=section_title,
        body_content=[
            ContentItem(text=subtitle, highlight_type=HighlightType.NONE)
        ],
        visual=None,
        code_block=None,
        alt_text=None,
    )


def generate_all_structural_slides(plan: DocumentPlan) -> dict:
    """
    Generate all structural slides from the document plan.

    Returns:
        Dictionary with keys: 'title', 'agenda', 'dividers'
        where 'dividers' is a dict mapping section_id -> divider slide
    """
    title_slide = generate_title_slide(plan)
    agenda_slide = generate_agenda_slide(plan)

    dividers = {}
    for section in plan.sections:
        dividers[section.id] = generate_section_divider(
            section.title, section.id, len(plan.sections)
        )

    return {
        "title": title_slide,
        "agenda": agenda_slide,
        "dividers": dividers,
    }
