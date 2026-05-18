"""
Hierarchical Visual Classifier Agent — Two-level DistilBERT + Visual Gate.

Level 1: Predicts category (data_structure, flow_diagram, comparison, chart,
         conceptual, architectural, none)
Level 2: Predicts specific template within that category

Supports:
- Hierarchical models (Level 1 + Level 2 sub-models)
- Single-template categories (skip L2, use full L1 confidence)
- Fallback for categories without trained Level 2 models
- Combined confidence scoring (L1 × L2)
- Confidence-based visual gate by composition mode
"""

import json
from pathlib import Path
import torch

# Auto-detect device: prefer CUDA, fallback to MPS, then CPU
_device = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")

from slide_gen.core.slide_schema import VALID_TEMPLATES
from slide_gen.core.hierarchy import (
    CATEGORY_LIST,
    CATEGORY_HIERARCHY,
    LEVEL2_LABELS,
    TEMPLATE_TO_CATEGORY,
    SINGLE_TEMPLATE_CATEGORIES,
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
    _l1_model.to(_device)
    _l1_model.eval()

    print(f"📋 Loaded Level 1 model: {len(_l1_labels)} categories (device: {_device})")
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
    model.to(_device)
    model.eval()

    _l2_models[category] = (model, tokenizer, labels)
    print(f"📋 Loaded Level 2 model for '{category}': {len(labels)} templates (device: {_device})")
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
    # Move inputs to same device as model
    inputs = {k: v.to(_device) for k, v in inputs.items()}

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
            For single-template categories, skip L2 and use full L1 confidence.
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

    # Step 2: Calculate Global Top 3 Templates
    all_template_probs = {}
    
    # Evaluate the top 3 Level 1 categories to find the best overall templates
    # (Multiplying Category Probability × Template Probability)
    sorted_categories = sorted(l1_result["probabilities"].items(), key=lambda x: x[1], reverse=True)
    
    for cat, l1_prob in sorted_categories[:3]:
        if cat == "none":
            all_template_probs["none"] = l1_prob
            continue

        # Single-template categories: skip L2, use full L1 confidence
        if cat in SINGLE_TEMPLATE_CATEGORIES:
            tmpl = SINGLE_TEMPLATE_CATEGORIES[cat]
            # Use max to keep the highest probability if template appears
            # in multiple categories (e.g. general_tree)
            all_template_probs[tmpl] = max(
                all_template_probs.get(tmpl, 0), l1_prob
            )
            continue

        l2_data = _load_level2(model_base, cat)
        if l2_data is not None:
            l2_model, l2_tokenizer, l2_labels = l2_data
            l2_result = _predict(l2_model, l2_tokenizer, l2_labels, text)
            for tmpl, l2_prob in l2_result["probabilities"].items():
                combined = l1_prob * l2_prob
                all_template_probs[tmpl] = max(
                    all_template_probs.get(tmpl, 0), combined
                )
        else:
            # Fallback for categories without Level 2 models
            templates = CATEGORY_HIERARCHY.get(cat, [])
            default_tmpl = templates[0] if templates else "concept_box"
            all_template_probs[default_tmpl] = max(
                all_template_probs.get(default_tmpl, 0), l1_prob
            )

    # Sort all template probabilities descending
    top_templates = sorted(all_template_probs.items(), key=lambda x: x[1], reverse=True)
    top_3 = [{"template_id": k, "confidence": round(v, 4)} for k, v in top_templates[:3]]
    
    # The absolute best template is the #1 item
    template_id = top_templates[0][0]
    combined_confidence = top_templates[0][1]
    category = TEMPLATE_TO_CATEGORY.get(template_id, "none")

    return {
        "template_id": template_id,
        "category": category,
        "confidence": combined_confidence,
        "top_3": top_3,
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
        # Render the predicted template. Only fall back to generic if confidence is abysmal.
        if confidence < 0.05:
            return {"template_id": "concept_box", "confidence": confidence}
        return {"template_id": template_id, "confidence": confidence}

    elif composition_mode == "Balanced":
        # Because confidence = L1 × L2 probabilities, values >= 0.2 are strong signals.
        # (Random chance would be ~0.16 × 0.20 = ~0.03)
        if confidence >= 0.15:
            return {"template_id": template_id, "confidence": confidence}
        # Only use concept_box as a mild fallback for borderline cases
        if confidence >= 0.05:
            return {"template_id": "concept_box", "confidence": confidence}
        return None

    else:  # Text_Heavy
        # Stricter threshold for text-heavy mode
        if confidence >= 0.35:
            return {"template_id": template_id, "confidence": confidence}
        return None
