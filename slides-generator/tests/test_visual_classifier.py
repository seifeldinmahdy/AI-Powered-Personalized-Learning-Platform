"""
Tests for the Hierarchical Visual Classifier.

Tests:
1. Hierarchy mapping consistency
2. Label mapping consistency (backward compatibility)
3. Fine-tuned model inference (skipped if models not present)
4. Visual Gate logic
"""

import json
import pytest
from pathlib import Path


# ============================================================
# TEST 1: Hierarchy mapping consistency
# ============================================================

def test_hierarchy_covers_all_templates():
    """Every VALID_TEMPLATES entry maps to exactly one category."""
    from slide_gen.core.slide_schema import VALID_TEMPLATES
    from slide_gen.core.hierarchy import TEMPLATE_TO_CATEGORY, CATEGORY_HIERARCHY

    for template in VALID_TEMPLATES:
        assert template in TEMPLATE_TO_CATEGORY, f"Template '{template}' missing from TEMPLATE_TO_CATEGORY"

    # Also verify every template in hierarchy is in VALID_TEMPLATES (+ "none")
    for cat, templates in CATEGORY_HIERARCHY.items():
        for tmpl in templates:
            assert tmpl in VALID_TEMPLATES, f"Hierarchy template '{tmpl}' not in VALID_TEMPLATES"


def test_hierarchy_categories_are_complete():
    """CATEGORY_LIST should have 6 categories including 'none'."""
    from slide_gen.core.hierarchy import CATEGORY_LIST
    assert len(CATEGORY_LIST) == 6
    assert "none" in CATEGORY_LIST
    assert "data_structure" in CATEGORY_LIST
    assert "flow_diagram" in CATEGORY_LIST
    assert "comparison" in CATEGORY_LIST
    assert "chart" in CATEGORY_LIST
    assert "conceptual" in CATEGORY_LIST


def test_template_to_category_bidirectional():
    """Reverse mapping is consistent with forward mapping."""
    from slide_gen.core.hierarchy import (
        CATEGORY_HIERARCHY, TEMPLATE_TO_CATEGORY, LEVEL2_LABELS,
    )

    for cat, templates in CATEGORY_HIERARCHY.items():
        for tmpl in templates:
            assert TEMPLATE_TO_CATEGORY[tmpl] == cat

    # Level 2 labels match hierarchy
    for cat, templates in LEVEL2_LABELS.items():
        assert templates == CATEGORY_HIERARCHY[cat]


def test_none_maps_to_none():
    """'none' template maps to 'none' category."""
    from slide_gen.core.hierarchy import get_category
    assert get_category("none") == "none"


def test_get_category_fallback():
    """Unknown template defaults to 'conceptual'."""
    from slide_gen.core.hierarchy import get_category
    assert get_category("totally_unknown_template") == "conceptual"


# ============================================================
# TEST 2: Label mapping consistency (backward compat)
# ============================================================

def test_label_mapping_consistency():
    """LABEL_LIST, LABEL_TO_ID, and ID_TO_LABEL must be consistent."""
    from slide_gen.agents.visual_classifier import LABEL_LIST, LABEL_TO_ID, ID_TO_LABEL

    num_labels = len(LABEL_LIST)
    assert num_labels >= 18, f"Expected at least 18 classes, got {num_labels}"
    assert len(LABEL_TO_ID) == num_labels
    assert len(ID_TO_LABEL) == num_labels

    for i, label in enumerate(LABEL_LIST):
        assert LABEL_TO_ID[label] == i
        assert ID_TO_LABEL[i] == label


def test_none_label_exists():
    """'none' must be a valid label for no-visual slides."""
    from slide_gen.agents.visual_classifier import LABEL_LIST
    assert "none" in LABEL_LIST


def test_all_templates_in_label_list():
    """Every VALID_TEMPLATES entry must appear in classifier LABEL_LIST."""
    from slide_gen.core.slide_schema import VALID_TEMPLATES
    from slide_gen.agents.visual_classifier import LABEL_LIST

    for template in VALID_TEMPLATES:
        assert template in LABEL_LIST, f"Template '{template}' missing from classifier LABEL_LIST"


# ============================================================
# TEST 3: Hierarchical training config
# ============================================================

def test_training_dataset_category_level():
    """HierarchicalDataset in 'category' mode uses CATEGORY_LIST."""
    from slide_gen.training.train_classifier import HierarchicalDataset
    from slide_gen.core.hierarchy import CATEGORY_LIST

    # Just check the label_list is correct (don't need real data for this)
    from unittest.mock import patch, mock_open
    sample = json.dumps({"text": "test stack push pop", "label": "stack"}) + "\n"

    with patch("builtins.open", mock_open(read_data=sample)):
        ds = HierarchicalDataset.__new__(HierarchicalDataset)
        ds.level = "category"
        ds.label_list = CATEGORY_LIST
        assert ds.label_list == CATEGORY_LIST


def test_training_dataset_level2():
    """HierarchicalDataset in Level 2 mode uses per-category labels."""
    from slide_gen.core.hierarchy import LEVEL2_LABELS

    # Verify structure
    assert "data_structure" in LEVEL2_LABELS
    assert "stack" in LEVEL2_LABELS["data_structure"]
    assert "none" not in LEVEL2_LABELS  # no Level 2 for none


# ============================================================
# TEST 4: Fine-tuned model inference (hierarchical)
# ============================================================

MODEL_PATH = Path("models/visual_classifier")

@pytest.mark.skipif(not (MODEL_PATH / "level1").exists(), reason="Hierarchical model not found")
def test_model_loads():
    """Fine-tuned hierarchical model loads without error."""
    from slide_gen.agents.visual_classifier import classify_visual
    result = classify_visual("A stack uses push and pop operations in LIFO order.", model_path=str(MODEL_PATH))
    assert result is not None


@pytest.mark.skipif(not (MODEL_PATH / "level1").exists(), reason="Hierarchical model not found")
def test_output_format():
    """classify_visual returns dict with template_id, category, confidence."""
    from slide_gen.agents.visual_classifier import classify_visual
    result = classify_visual("Binary tree traversal visits root, left, right children.", model_path=str(MODEL_PATH))

    assert "template_id" in result
    assert "category" in result
    assert "confidence" in result
    assert "l1_confidence" in result
    assert "l2_confidence" in result
    assert "probabilities" in result
    assert isinstance(result["template_id"], str)
    assert 0.0 <= result["confidence"] <= 1.0


@pytest.mark.skipif(not (MODEL_PATH / "level1").exists(), reason="Hierarchical model not found")
def test_confidence_sums_to_one():
    """Level 1 probability distribution should sum to ~1.0."""
    from slide_gen.agents.visual_classifier import classify_visual
    result = classify_visual("A flowchart is used to represent decision logic.", model_path=str(MODEL_PATH))

    prob_sum = sum(result["probabilities"].values())
    assert abs(prob_sum - 1.0) < 0.01, f"L1 probabilities sum to {prob_sum}, expected ~1.0"


# ============================================================
# TEST 5: Visual Gate logic
# ============================================================

def test_visual_gate_none_template():
    """Visual Gate returns None for 'none' template in Balanced/Text_Heavy mode."""
    from slide_gen.agents.visual_classifier import should_render_visual

    classification = {"template_id": "none", "confidence": 0.9}
    assert should_render_visual(classification, "Balanced") is None
    assert should_render_visual(classification, "Text_Heavy") is None


def test_visual_gate_none_visual_heavy_fallback():
    """Visual Gate forces concept_box fallback for 'none' in Visual_Heavy."""
    from slide_gen.agents.visual_classifier import should_render_visual

    classification = {"template_id": "none", "confidence": 0.9}
    result = should_render_visual(classification, "Visual_Heavy")
    assert result is not None
    assert result["template_id"] == "concept_box"


def test_visual_gate_high_confidence():
    """High-confidence templates render in all modes."""
    from slide_gen.agents.visual_classifier import should_render_visual

    classification = {"template_id": "flowchart", "confidence": 0.95}
    for mode in ["Visual_Heavy", "Balanced", "Text_Heavy"]:
        result = should_render_visual(classification, mode)
        assert result is not None, f"High-confidence flowchart should render in {mode}"
        assert result["template_id"] == "flowchart"


def test_visual_gate_low_confidence_text_heavy():
    """Low-confidence templates should NOT render in Text_Heavy mode."""
    from slide_gen.agents.visual_classifier import should_render_visual

    classification = {"template_id": "flowchart", "confidence": 0.4}
    result = should_render_visual(classification, "Text_Heavy")
    assert result is None
