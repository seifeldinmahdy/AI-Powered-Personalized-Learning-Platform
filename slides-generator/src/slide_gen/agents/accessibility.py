"""
Accessibility Worker Agent — Deterministic alt-text generation.

Generates truthful alt-text by combining template_id + params.
No hallucination — describes exactly what's in the visual.
"""


# Template-specific alt-text generators
_ALT_TEXT_GENERATORS = {
    # Data structures
    "linear_chain": lambda p: (
        f"A linear chain diagram showing {len(p.get('nodes', []))} connected nodes: "
        f"{' → '.join(str(n) for n in p.get('nodes', []))}"
        f"{'. Ends with NULL pointer' if p.get('show_null') else ''}"
    ),
    "binary_tree": lambda p: (
        f"A binary tree with root node '{p.get('root', 'Root')}', "
        f"left child '{p.get('left', 'Left')}', and "
        f"right child '{p.get('right', 'Right')}'"
    ),
    "general_tree": lambda p: (
        f"A general tree diagram"
        f"{' titled ' + chr(39) + p.get('title', '') + chr(39) if p.get('title') else ''}"
        f" with root node '{p.get('root', 'Root')}' and "
        f"{sum(len(v) for v in p.get('children', {}).values())} total child nodes"
        f"{'. Relationship: ' + p.get('relationship_label', '') if p.get('relationship_label') else ''}"
    ),
    "stack": lambda p: (
        f"A stack data structure with {len(p.get('items', []))} items "
        f"from bottom to top: {', '.join(str(i) for i in p.get('items', []))}"
        f"{'. Top is labeled: ' + p.get('top_label', '') if p.get('top_label') else ''}"
    ),
    "queue": lambda p: (
        f"A queue with {len(p.get('items', []))} items: "
        f"{', '.join(str(i) for i in p.get('items', []))}"
    ),
    "graph": lambda p: (
        f"A graph with {len(p.get('nodes', []))} nodes "
        f"({', '.join(str(n) for n in p.get('nodes', []))}) "
        f"and {len(p.get('edges', []))} edges"
    ),
    "layers": lambda p: (
        f"A layered architecture diagram with {len(p.get('layers', []))} layers: "
        f"{', '.join(str(l) for l in p.get('layers', []))}"
    ),

    # Flowcharts
    "flowchart": lambda p: (
        f"A flowchart with {len(p.get('nodes', []))} nodes "
        f"and {len(p.get('edges', []))} connections"
    ),
    "process_flow": lambda p: (
        f"A process flow with {len(p.get('steps', []))} steps: "
        f"{' → '.join(str(s) for s in p.get('steps', []))}"
    ),
    "cycle": lambda p: (
        f"A circular cycle diagram connecting: "
        f"{' → '.join(str(n) for n in p.get('nodes', []))} → (back to start)"
    ),
    "comparison": lambda p: (
        f"A side-by-side comparison of "
        f"'{p.get('left_label', p.get('left_title', 'Left'))}' vs '{p.get('right_label', p.get('right_title', 'Right'))}'. "
        f"Left has {len(p.get('left_items', []))} items, "
        f"Right has {len(p.get('right_items', []))} items"
    ),
    "venn_diagram": lambda p: (
        f"A Venn diagram comparing '{p.get('left_label', 'Left')}' and '{p.get('right_label', 'Right')}'. "
        f"{len(p.get('left_only', []))} unique to left, "
        f"{len(p.get('right_only', []))} unique to right, "
        f"{len(p.get('shared', []))} shared properties"
    ),
    "sequence": lambda p: (
        f"A sequence diagram with actors: "
        f"{', '.join(str(a) for a in p.get('actors', []))} "
        f"exchanging {len(p.get('messages', []))} messages"
    ),
    "timeline": lambda p: (
        f"A timeline showing {len(p.get('events', []))} events"
    ),

    # Charts
    "bar_chart": lambda p: (
        f"A bar chart with categories: "
        f"{', '.join(f'{l}={v}' for l, v in zip(p.get('labels', []), p.get('values', [])))}"
    ),
    "line_chart": lambda p: (
        f"A line chart with {len(p.get('x_values', []))} data points"
    ),

    # Fallback templates
    "concept_box": lambda p: (
        f"A concept box titled '{p.get('title', 'Concept')}' with "
        f"{len(p.get('points', []))} key points: "
        f"{'; '.join(str(pt) for pt in p.get('points', []))}"
    ),
    "analogy_diagram": lambda p: (
        f"An analogy diagram mapping '{p.get('familiar_label', 'Familiar')}' to "
        f"'{p.get('technical_label', 'Technical')}' with "
        f"{len(p.get('mappings', []))} correspondences"
    ),
    "info_card": lambda p: (
        f"An information card titled '{p.get('title', 'Info')}' "
        f"with {len(p.get('items', []))} key-value pairs"
    ),
    "definition_box": lambda p: (
        f"A definition box for the term '{p.get('term', 'Term')}': "
        f"{p.get('definition', 'No definition provided')}"
    ),

    # Architectural
    "layered_stack": lambda p: (
        f"A layered architecture diagram"
        f"{' titled ' + chr(39) + p.get('title', '') + chr(39) if p.get('title') else ''}"
        f" with {len(p.get('layers', []))} layers from top to bottom: "
        f"{', '.join(str(l) for l in p.get('layers', []))}"
    ),
    "architecture_diagram": lambda p: (
        f"An architecture diagram"
        f"{' titled ' + chr(39) + p.get('title', '') + chr(39) if p.get('title') else ''}"
        f" with {len(p.get('nodes', []))} components and "
        f"{len(p.get('edges', []))} connections"
    ),
}


def generate_alt_text(
    template_id: str | None,
    params: dict | None,
    slide_title: str = "",
    screen_reader_active: bool = False,
) -> str | None:
    """
    Generate accessibility alt-text for a visual template.

    Uses template_id + actual params to describe the visual truthfully.
    No hallucination — only describes what's actually in the data.

    Args:
        template_id: Visual template identifier
        params: Template parameters
        slide_title: Slide title for context
        screen_reader_active: Whether a11y is required

    Returns:
        Alt-text string, or None if not needed
    """
    # Only generate alt-text when accessibility is active
    if not screen_reader_active:
        return None

    # No visual → no alt-text needed
    if not template_id:
        return None

    params = params or {}

    # Use template-specific generator if available
    generator = _ALT_TEXT_GENERATORS.get(template_id)
    if generator:
        try:
            return generator(params)
        except (KeyError, TypeError, IndexError):
            pass

    # Generic fallback
    return f"A {template_id.replace('_', ' ')} visual related to: {slide_title}"
