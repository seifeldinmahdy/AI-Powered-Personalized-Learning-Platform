"""
Deck Assembler — Stage 5 of the presentation pipeline.

Merges structural slides, content slides, and summary slides
into a single ordered presentation deck with slide numbering.
"""

from slide_gen.core.slide_schema import SlideInstruction


def assemble_deck(
    structural_slides: dict,
    content_slides: dict[int, list[SlideInstruction]],
    summary_slides: dict[int, SlideInstruction],
    section_ids: list[int],
) -> list[SlideInstruction]:
    """
    Assemble the final presentation deck in correct order.

    Order:
    [Title] → [Agenda] → for each section:
        [Section Divider] → [Content Slides...] → [Summary Slide]

    Args:
        structural_slides: Dict with 'title', 'agenda', 'dividers' keys
        content_slides: Dict mapping section_id → list of content slides
        summary_slides: Dict mapping section_id → summary slide
        section_ids: Ordered list of section IDs

    Returns:
        Ordered list of all slides with slide_number set
    """
    deck: list[SlideInstruction] = []

    # 1. Title slide
    deck.append(structural_slides["title"])

    # 2. Agenda slide
    deck.append(structural_slides["agenda"])

    # 3. Sections: divider → content → summary (only processed sections)
    for sid in section_ids:
        # Skip sections that weren't processed
        if sid not in content_slides:
            continue

        # Section divider
        if sid in structural_slides["dividers"]:
            deck.append(structural_slides["dividers"][sid])

        # Content slides
        deck.extend(content_slides[sid])

        # Summary slide
        if sid in summary_slides:
            deck.append(summary_slides[sid])

    # 4. Apply slide numbering
    for i, slide in enumerate(deck):
        slide.slide_number = i + 1

    return deck


def deck_to_json(deck: list[SlideInstruction]) -> list[dict]:
    """
    Convert the entire deck to a JSON-serializable list.

    Args:
        deck: Ordered list of SlideInstructions

    Returns:
        List of dicts, one per slide
    """
    return [slide.model_dump(mode="json") for slide in deck]
