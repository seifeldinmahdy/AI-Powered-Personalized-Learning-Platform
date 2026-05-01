"""
Hierarchical Visual Template Classification — Category Definitions.

Two-level hierarchy:
  Level 1 (Category): data_structure, flow_diagram, comparison, conceptual, none
  Level 2 (Template): specific template_id within each category

Used by both training (train_classifier.py) and inference (visual_classifier.py).
"""

from __future__ import annotations


# =============================================================================
# HIERARCHY DEFINITION
# =============================================================================

CATEGORY_HIERARCHY: dict[str, list[str]] = {
    "data_structure": [
        "linear_chain", "binary_tree", "stack", "queue", "graph",
    ],
    "flow_diagram": [
        "flowchart", "cycle",
    ],
    "comparison": [
        "comparison", "grid",
    ],
    "chart": [
        "bar_chart", "pie_chart",
    ],
    "conceptual": [
        "concept_box",
    ],
    "none": [],
}

# Ordered category list (Level 1 labels)
CATEGORY_LIST: list[str] = list(CATEGORY_HIERARCHY.keys())
CATEGORY_TO_ID: dict[str, int] = {c: i for i, c in enumerate(CATEGORY_LIST)}
ID_TO_CATEGORY: dict[int, str] = {i: c for i, c in enumerate(CATEGORY_LIST)}

# Reverse mapping: template_id → category
TEMPLATE_TO_CATEGORY: dict[str, str] = {}
for _cat, _templates in CATEGORY_HIERARCHY.items():
    for _tmpl in _templates:
        TEMPLATE_TO_CATEGORY[_tmpl] = _cat
# "none" maps to itself
TEMPLATE_TO_CATEGORY["none"] = "none"

# Per-category Level 2 label lists
LEVEL2_LABELS: dict[str, list[str]] = {
    cat: templates
    for cat, templates in CATEGORY_HIERARCHY.items()
    if templates  # skip "none" — no Level 2
}

LEVEL2_LABEL_TO_ID: dict[str, dict[str, int]] = {
    cat: {label: i for i, label in enumerate(labels)}
    for cat, labels in LEVEL2_LABELS.items()
}

LEVEL2_ID_TO_LABEL: dict[str, dict[int, str]] = {
    cat: {i: label for i, label in enumerate(labels)}
    for cat, labels in LEVEL2_LABELS.items()
}

# All template IDs that have a valid category mapping
ALL_TEMPLATE_IDS: set[str] = set(TEMPLATE_TO_CATEGORY.keys())


def get_category(template_id: str) -> str:
    """Map a template_id to its Level 1 category."""
    return TEMPLATE_TO_CATEGORY.get(template_id, "conceptual")


def get_level2_labels(category: str) -> list[str]:
    """Get the Level 2 label list for a category."""
    return LEVEL2_LABELS.get(category, [])
