"""
Hierarchical Visual Template Classification — Category Definitions.

Two-level hierarchy:
  Level 1 (Category): data_structure, flow_diagram, chart,
                       architectural, conceptual, none
  Level 2 (Template): specific template_id within each category

Used by both training (train_classifier.py) and inference (visual_classifier.py).
"""

from __future__ import annotations


# =============================================================================
# HIERARCHY DEFINITION
# =============================================================================

CATEGORY_HIERARCHY: dict[str, list[str]] = {
    "data_structure": [
        "linear_chain", "binary_tree", "general_tree",
        "stack", "queue", "graph",
    ],
    "flow_diagram": [
        "flowchart", "cycle",
    ],
    "chart": [
        "bar_chart",
    ],
    "architectural": [
        "architecture_diagram",
    ],
    "conceptual": [
        "conceptual",
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
        if _tmpl not in TEMPLATE_TO_CATEGORY:
            TEMPLATE_TO_CATEGORY[_tmpl] = _cat
# "none" and "conceptual" map to themselves
TEMPLATE_TO_CATEGORY["none"] = "none"
TEMPLATE_TO_CATEGORY["conceptual"] = "conceptual"

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

# Categories that have only one template — skip Level 2 model loading
# and return the template directly with full L1 confidence.
# This applies to: comparison, chart, conceptual, architectural
SINGLE_TEMPLATE_CATEGORIES: dict[str, str] = {
    cat: templates[0]
    for cat, templates in CATEGORY_HIERARCHY.items()
    if len(templates) == 1
}

# All template IDs that have a valid category mapping
ALL_TEMPLATE_IDS: set[str] = set(TEMPLATE_TO_CATEGORY.keys())


def get_category(template_id: str) -> str:
    """Map a template_id to its Level 1 category."""
    return TEMPLATE_TO_CATEGORY.get(template_id, "none")


def get_level2_labels(category: str) -> list[str]:
    """Get the Level 2 label list for a category."""
    return LEVEL2_LABELS.get(category, [])
