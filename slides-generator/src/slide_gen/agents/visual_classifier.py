"""
Hierarchical Visual Classifier Agent — Two-level DistilBERT + Visual Gate.

Level 1: Predicts category (data_structure, flow_diagram, comparison, chart, conceptual, none)
Level 2: Predicts specific template within that category

Supports:
- Hierarchical models (Level 1 + Level 2 sub-models)
- Fallback for categories without trained Level 2 models
- Combined confidence scoring (L1 × L2)
- Confidence-based visual gate by composition mode
"""

import json
from pathlib import Path

from slide_gen.core.slide_schema import VALID_TEMPLATES
from slide_gen.core.hierarchy import (
    CATEGORY_LIST,
    CATEGORY_HIERARCHY,
    LEVEL2_LABELS,
)


# Original flat label list — kept for data generation compatibility
LABEL_LIST = VALID_TEMPLATES + ["none"]
LABEL_TO_ID = {label: i for i, label in enumerate(LABEL_LIST)}
ID_TO_LABEL = {i: label for i, label in enumerate(LABEL_LIST)}

# Lazy-loaded models
_l1_model = None
_l1_tokenizer = None
_l1_labels = None

_l2_models: dict[str, tuple] = {}  # category → (model, tokenizer, label_list)
_hierarchy_config = None


def _load_hierarchy_config(model_base: str | Path) -> dict | None:
    """Load the hierarchy config written during training."""
    config_path = Path(model_base) / "hierarchy_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return None


def _load_level1(model_base: str | Path):
    """Lazy-load the Level 1 (category) model."""
    global _l1_model, _l1_tokenizer, _l1_labels, _hierarchy_config

    if _l1_model is not None:
        return _l1_model, _l1_tokenizer, _l1_labels

    model_base = Path(model_base)
    _hierarchy_config = _load_hierarchy_config(model_base)

    l1_path = model_base / "level1"
    if not l1_path.exists():
        raise FileNotFoundError(
            f"Level 1 model not found at {l1_path}. "
            f"Run: python -m slide_gen.training.train_classifier --data <data.jsonl> --output {model_base}"
        )

    # Load label config
    label_config_path = l1_path / "label_config.json"
    if label_config_path.exists():
        with open(label_config_path) as f:
            config = json.load(f)
        _l1_labels = config["label_list"]
    else:
        _l1_labels = CATEGORY_LIST

    from transformers import DistilBertForSequenceClassification, DistilBertTokenizer

    _l1_tokenizer = DistilBertTokenizer.from_pretrained(str(l1_path))
    _l1_model = DistilBertForSequenceClassification.from_pretrained(
        str(l1_path), num_labels=len(_l1_labels)
    )
    _l1_model.eval()

    print(f"📋 Loaded Level 1 model: {len(_l1_labels)} categories")
    return _l1_model, _l1_tokenizer, _l1_labels


def _load_level2(model_base: str | Path, category: str):
    """Lazy-load a Level 2 (per-category template) model."""
    if category in _l2_models:
        return _l2_models[category]

    model_base = Path(model_base)
    l2_path = model_base / "level2" / category

    if not l2_path.exists():
        _l2_models[category] = None
        return None

    # Load label config
    label_config_path = l2_path / "label_config.json"
    if label_config_path.exists():
        with open(label_config_path) as f:
            config = json.load(f)
        labels = config["label_list"]
    else:
        labels = LEVEL2_LABELS.get(category, [])

    if not labels:
        _l2_models[category] = None
        return None

    from transformers import DistilBertForSequenceClassification, DistilBertTokenizer

    tokenizer = DistilBertTokenizer.from_pretrained(str(l2_path))
    model = DistilBertForSequenceClassification.from_pretrained(
        str(l2_path), num_labels=len(labels)
    )
    model.eval()

    _l2_models[category] = (model, tokenizer, labels)
    print(f"📋 Loaded Level 2 model for '{category}': {len(labels)} templates")
    return _l2_models[category]


def _predict(model, tokenizer, labels, text: str) -> dict:
    """Run inference on a single text and return predictions."""
    import torch

    inputs = tokenizer(
        text,
        return_tensors="pt",
        max_length=256,
        truncation=True,
        padding=True,
    )

    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        probs = torch.softmax(logits, dim=-1)[0]

    top_idx = probs.argmax().item()
    confidence = probs[top_idx].item()
    predicted_label = labels[top_idx]

    probabilities = {
        labels[i]: round(probs[i].item(), 4)
        for i in range(len(labels))
    }

    return {
        "label": predicted_label,
        "confidence": confidence,
        "probabilities": probabilities,
    }


def classify_visual(
    text: str,
    model_path: str = "models/visual_classifier",
) -> dict:
    """
    Hierarchically classify text into a visual template.

    Step 1: Predict category (Level 1)
    Step 2: If category ≠ 'none', predict specific template (Level 2)
    Step 3: Combine confidences

    Args:
        text: Slide content text (bullets)
        model_path: Base path to hierarchical model directory

    Returns:
        Dict with:
        - 'template_id': specific template prediction
        - 'category': Level 1 category
        - 'confidence': combined confidence (L1 × L2)
        - 'l1_confidence': Level 1 confidence
        - 'l2_confidence': Level 2 confidence (1.0 if no L2 model)
        - 'probabilities': Level 1 category probabilities
    """
    model_base = Path(model_path)

    # Step 1: Level 1 — Category prediction
    l1_model, l1_tokenizer, l1_labels = _load_level1(model_base)
    l1_result = _predict(l1_model, l1_tokenizer, l1_labels, text)

    category = l1_result["label"]
    l1_confidence = l1_result["confidence"]

    # If "none", no visual needed
    if category == "none":
        return {
            "template_id": "none",
            "category": "none",
            "confidence": l1_confidence,
            "l1_confidence": l1_confidence,
            "l2_confidence": 1.0,
            "probabilities": l1_result["probabilities"],
        }

    # Step 2: Level 2 — Template prediction within category
    l2_data = _load_level2(model_base, category)

    if l2_data is not None:
        l2_model, l2_tokenizer, l2_labels = l2_data
        l2_result = _predict(l2_model, l2_tokenizer, l2_labels, text)
        template_id = l2_result["label"]
        l2_confidence = l2_result["confidence"]
    else:
        # No Level 2 model — use first template in category as default
        templates = CATEGORY_HIERARCHY.get(category, [])
        template_id = templates[0] if templates else "concept_box"
        l2_confidence = 1.0

    # Step 3: Combined confidence
    combined_confidence = l1_confidence * l2_confidence

    return {
        "template_id": template_id,
        "category": category,
        "confidence": combined_confidence,
        "l1_confidence": l1_confidence,
        "l2_confidence": l2_confidence,
        "probabilities": l1_result["probabilities"],
    }


# =============================================================================
# VISUAL GATE — Rule-based decision logic
# =============================================================================

def should_render_visual(
    classification: dict,
    composition_mode: str,
) -> dict | None:
    """
    Decide whether to render a visual based on classifier confidence
    and the student's composition mode preference.

    Args:
        classification: Output from classify_visual()
        composition_mode: "Visual_Heavy", "Balanced", or "Text_Heavy"

    Returns:
        Dict with template_id and params if visual should render, else None
    """
    template_id = classification["template_id"]
    confidence = classification["confidence"]

    # If classifier says "none", only override for Visual_Heavy
    if template_id == "none":
        if composition_mode == "Visual_Heavy":
            return {"template_id": "concept_box", "confidence": confidence}
        return None

    # Decision thresholds based on composition mode
    if composition_mode == "Visual_Heavy":
        if confidence < 0.5:
            return {"template_id": "concept_box", "confidence": confidence}
        return {"template_id": template_id, "confidence": confidence}

    elif composition_mode == "Balanced":
        if confidence >= 0.6:
            return {"template_id": template_id, "confidence": confidence}
        if confidence >= 0.35:
            return {"template_id": "concept_box", "confidence": confidence}
        return None

    else:  # Text_Heavy
        if confidence >= 0.85:
            return {"template_id": template_id, "confidence": confidence}
        return None
