"""
Visual Param Generator Agent — Converts bullets + template_id into structured params.

Uses a small LLM call (Ollama) to understand the semantic relationships in the
bullet points and produce the structured parameters each template renderer expects
(nodes, edges, labels, etc.).

This is the bridge between the Visual Classifier output and the Template Registry.
"""

import os
import json
import re
from typing import Any

import requests

from slide_gen.data_engine.utils import extract_json_from_response


# =============================================================================
# PER-TEMPLATE PARAM SCHEMAS
# Describes what each renderer expects so the LLM knows what to produce
# =============================================================================

TEMPLATE_PARAM_SCHEMAS: dict[str, dict[str, Any]] = {
    # --- Graphviz Data Structures ---
    "linear_chain": {
        "description": "A linked list / linear chain of nodes connected sequentially",
        "schema": {
            "nodes": "list of strings — the items/values in the chain (e.g., ['Head', '10', '20', '30'])",
            "direction": "string — 'LR' (left to right) or 'TB' (top to bottom), default 'LR'",
            "show_null": "boolean — whether to show a null/end pointer, default true",
        },
        "example": {"nodes": ["Head", "10", "20", "30"], "direction": "LR", "show_null": True},
    },
    "binary_tree": {
        "description": "A binary tree with root, left, and right subtrees",
        "schema": {
            "root": "string — the root node label",
            "left": "string — the left child label",
            "right": "string — the right child label",
            "left_children": "list of strings — left subtree children",
            "right_children": "list of strings — right subtree children",
        },
        "example": {"root": "50", "left": "30", "right": "70", "left_children": ["20", "40"], "right_children": ["60", "80"]},
    },
    "general_tree": {
        "description": "A general tree with one root and multiple children at each level. Used for hierarchies like master-slave architectures, file systems, OOP inheritance, and organizational structures. Different from binary_tree because branching factor is arbitrary, not strictly left/right.",
        "schema": {
            "root": "string — the root node label",
            "children": "dict mapping each parent node label to a list of its child node labels. Can be multi-level.",
            "title": "string — optional title for the diagram",
            "relationship_label": "string — optional label placed on all edges describing the relationship, e.g. 'manages', 'contains', 'inherits from'. Leave empty for pure data structure trees.",
        },
        "example": {
            "root": "NameNode",
            "children": {
                "NameNode": ["DataNode 1", "DataNode 2", "DataNode 3"],
                "DataNode 1": ["Block A", "Block B"],
            },
            "title": "HDFS Master-Slave Architecture",
            "relationship_label": "manages"
        }
    },
    "stack": {
        "description": "A stack (LIFO) data structure showing items top to bottom",
        "schema": {
            "items": "list of strings — stack items from top to bottom",
            "top_label": "string — label for the top pointer, default 'TOP'",
        },
        "example": {"items": ["peek() → 42", "17", "8", "3"], "top_label": "TOP"},
    },
    "queue": {
        "description": "A queue (FIFO) data structure showing items front to back",
        "schema": {
            "items": "list of strings — queue items from front to back",
            "front_label": "string — label for front, default 'FRONT'",
            "back_label": "string — label for back, default 'BACK'",
        },
        "example": {"items": ["Process A", "Process B", "Process C"], "front_label": "DEQUEUE", "back_label": "ENQUEUE"},
    },
    "graph": {
        "description": "A generic graph with nodes and edges",
        "schema": {
            "nodes": "list of strings — node labels",
            "edges": "list of [int, int] — pairs of node indices that are connected",
            "directed": "boolean — true for directed graph, false for undirected",
        },
        "example": {"nodes": ["A", "B", "C", "D"], "edges": [[0, 1], [1, 2], [2, 3], [3, 0]], "directed": True},
    },

    # --- Mermaid Diagrams ---
    "flowchart": {
        "description": "A flowchart with decision nodes, process nodes, and labeled edges",
        "schema": {
            "nodes": "list of objects with {id: string, label: string, type: 'box'|'diamond'|'circle'}. Use 'diamond' for decisions/conditions, 'circle' for start/end, 'box' for processes.",
            "edges": "list of objects with {from: string, to: string, label: string (optional)}. The 'from' and 'to' must match node ids.",
            "direction": "string — 'TD' (top-down) or 'LR' (left-right), default 'TD'",
        },
        "example": {
            "nodes": [
                {"id": "A", "label": "Start", "type": "circle"},
                {"id": "B", "label": "Is Valid?", "type": "diamond"},
                {"id": "C", "label": "Process", "type": "box"},
                {"id": "D", "label": "Error", "type": "box"},
            ],
            "edges": [
                {"from": "A", "to": "B"},
                {"from": "B", "to": "C", "label": "Yes"},
                {"from": "B", "to": "D", "label": "No"},
            ],
            "direction": "TD",
        },
    },
    "cycle": {
        "description": "A circular/cycle diagram where the last node connects back to the first",
        "schema": {
            "nodes": "list of strings — cycle stages (will be connected in a loop)",
            "title": "string — optional title",
        },
        "example": {"nodes": ["Plan", "Do", "Check", "Act"], "title": "PDCA Cycle"},
    },
    "comparison": {
        "description": "Side-by-side comparison of two categories",
        "schema": {
            "left_title": "string — title for left column",
            "right_title": "string — title for right column",
            "left_items": "list of strings — items in left column",
            "right_items": "list of strings — items in right column",
        },
        "example": {
            "left_title": "Arrays",
            "right_title": "Linked Lists",
            "left_items": ["O(1) random access", "Fixed size", "Cache friendly"],
            "right_items": ["O(1) insertion", "Dynamic size", "Extra memory for pointers"],
        },
    },
    "venn_diagram": {
        "description": "Two overlapping circles showing shared and distinct properties between two concepts. Use when content compares two things with some shared and some distinct properties.",
        "schema": {
            "left_label": "string — name of left concept",
            "right_label": "string — name of right concept",
            "left_only": "list of strings — properties unique to left concept",
            "right_only": "list of strings — properties unique to right concept",
            "shared": "list of strings — properties common to both concepts",
            "title": "string — optional title",
        },
        "example": {
            "left_label": "TCP",
            "right_label": "UDP",
            "left_only": ["Connection-oriented", "Guaranteed delivery", "Flow control"],
            "right_only": ["Connectionless", "Faster", "No overhead"],
            "shared": ["Uses ports", "Transport layer", "IP-based"],
            "title": "TCP vs UDP"
        },
    },

    # --- Charts (Quantitative) ---
    "bar_chart": {
        "description": "A bar chart comparing categories with numerical values",
        "schema": {
            "labels": "list of strings — category names",
            "values": "list of numbers — corresponding values",
            "title": "string — chart title",
            "xlabel": "string — x-axis label",
            "ylabel": "string — y-axis label",
        },
        "example": {"labels": ["Python", "Java", "C++"], "values": [35, 30, 20], "title": "Language Popularity", "xlabel": "Language", "ylabel": "Popularity %"},
    },

    # --- Fallback ---
    "concept_box": {
        "description": "A simple concept box with a title and key points",
        "schema": {
            "title": "string — the main concept name",
            "points": "list of strings — key points about the concept",
        },
        "example": {"title": "Polymorphism", "points": ["Method overriding", "Method overloading", "Duck typing"]},
    },
    "analogy_diagram": {
        "description": "A two-panel mapping showing a familiar real-world concept on the left mapped to the technical concept on the right, with labeled correspondences between elements. Use when content explains a technical concept by comparing it to something familiar.",
        "schema": {
            "familiar_label": "string — the familiar real-world thing being used as the analogy",
            "technical_label": "string — the technical concept being explained",
            "mappings": "list of dicts with {familiar: string, technical: string} pairs showing what corresponds to what",
            "title": "string — optional title",
        },
        "example": {
            "familiar_label": "Library",
            "technical_label": "Database",
            "mappings": [
                {"familiar": "Book", "technical": "Record"},
                {"familiar": "Catalog", "technical": "Index"},
                {"familiar": "Librarian", "technical": "DBMS"},
                {"familiar": "Reading room", "technical": "Cache"},
            ],
            "title": "Database as a Library"
        },
    },

    # --- Architectural ---
    "architecture_diagram": {
        "description": (
            "A flexible architecture diagram for any system, model, or component architecture. "
            "Covers neural networks, transformers, attention mechanisms, LSTM, ResNet, CNN, "
            "encoder-decoder, microservices, compiler pipelines, database architectures, "
            "OS stacks, OSI model, software abstraction layers, master-slave architectures, "
            "and any content describing components with connections and data flow. "
            "Previously also covered layered_stack — use style='layered' for clean horizontal "
            "abstraction layers, style='component' for component diagrams with connections."
        ),
        "output_format": "xml",
        "schema_description": """
Return ONLY valid XML conforming to this schema:

<architecture title="..." layout="hierarchical|pipeline|network" style="layered|component">
  <component id="unique_id" label="Display Name" role="master|worker|processor|storage|input|output|layer">
    <connects to="other_id" label="optional relationship label"/>
  </component>
  ...
</architecture>

layout values:
  hierarchical → top-down flow, use for master-slave, trees, OS stacks, OSI model
  pipeline     → left-to-right flow, use for sequential processing, neural network layers
  network      → force-directed, use for peer-to-peer, mesh, graph-like architectures

style values:
  layered   → uniform full-width horizontal bands, use for OSI, OS stack, software layers
  component → individual variable-size boxes with connections, use for neural nets, microservices

role values:
  master    → rendered as double circle
  worker    → rendered as box
  processor → rendered as hexagon
  storage   → rendered as cylinder
  input     → rendered as parallelogram (left-leaning)
  output    → rendered as parallelogram (right-leaning)
  layer     → rendered as full-width band (only used when style=layered)

Rules:
  1. Only include components explicitly mentioned or clearly implied in the content
  2. Every component must have a unique id and a concise label under 25 characters
  3. Connections must reference valid component ids
  4. Maximum 8 components, maximum 12 connections
  5. If content describes clean abstraction layers with no lateral connections: use style=layered, layout=hierarchical, role=layer for all components
  6. If content does not describe a clear architecture with named components: return <architecture title="" layout="none"/>
""",
        "example_component": """
<architecture title="HDFS Architecture" layout="hierarchical" style="component">
  <component id="nn" label="NameNode" role="master">
    <connects to="dn1" label="manages"/>
    <connects to="dn2" label="manages"/>
    <connects to="dn3" label="manages"/>
  </component>
  <component id="dn1" label="DataNode 1" role="worker"/>
  <component id="dn2" label="DataNode 2" role="worker"/>
  <component id="dn3" label="DataNode 3" role="worker"/>
</architecture>
""",
        "example_layered": """
<architecture title="OSI Model" layout="hierarchical" style="layered">
  <component id="app" label="Application" role="layer">
    <connects to="trans" label=""/>
  </component>
  <component id="trans" label="Transport" role="layer">
    <connects to="net" label=""/>
  </component>
  <component id="net" label="Network" role="layer">
    <connects to="dl" label=""/>
  </component>
  <component id="dl" label="Data Link" role="layer">
    <connects to="phys" label=""/>
  </component>
  <component id="phys" label="Physical" role="layer"/>
</architecture>
""",
    },
}


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """You are a visualization parameter generator for educational slides.

Given bullet points from a slide and a template type, you MUST produce structured JSON parameters that will be used to render a visual diagram.

RULES:
1. Output ONLY valid JSON — no explanations, no markdown
2. Extract real concepts from the bullets — don't use generic placeholder text
3. Keep labels concise (max ~30 chars per label)
4. Use the content's actual terms and ideas as node labels, step names, etc.
5. For flowcharts: identify decision points (if/else/conditions) as 'diamond' nodes
6. For comparisons: split the content into two meaningful groups
7. For charts: extract or infer reasonable numerical values from the content
8. For architecture diagrams: identify components and their connections, assign layers for grouping
9. For venn diagrams: identify shared vs distinct properties between the two concepts
10. For analogy diagrams: map the familiar concept elements to their technical counterparts"""


# =============================================================================
# LLM TEMPLATE VALIDATION
# =============================================================================

_TEMPLATE_DESCRIPTIONS = {
    "linear_chain": "Linked lists, sequences of connected nodes",
    "binary_tree": "Binary trees with strict left/right children",
    "general_tree": "Hierarchies with arbitrary branching: file systems, inheritance trees, tries, B-trees",
    "stack": "LIFO data structures with push/pop",
    "queue": "FIFO data structures with enqueue/dequeue",
    "graph": "Networks of nodes and edges, adjacency relationships",
    "flowchart": "Algorithm flow with decision/branch logic, if/else, conditional steps",
    "cycle": "Circular processes, repeating loops",
    "comparison": "Side-by-side analysis, attribute-by-attribute differences, pros/cons",
    "bar_chart": "Comparing quantities across discrete categories",
    "conceptual": "Conceptual explanations, definitions, summaries, analogies, or comparisons between two things — LLM enrichment picks the final layout",
    "concept_box": "General concepts, definitions, abstract ideas",
    "architecture_diagram": (
        "System or model architecture: neural networks, transformers, microservices, compiler pipelines, "
        "any component-connection diagram, OSI model, OS architecture, software layers, technology stacks."
    ),
}

_VALIDATION_SYSTEM_PROMPT = """You are a visual template classifier for educational slides.

Given a text chunk and a predicted template type, decide if the prediction is correct or suggest a better template.

AVAILABLE TEMPLATES:
{template_list}

Output ONLY a JSON object with one field:
{{"corrected_template": "template_id_here"}}

If the prediction is correct, return the same template_id. If a different template fits better, return that one instead. ONLY use template IDs from the list above."""


def _llm_validate_template(
    template_id: str,
    raw_chunk: str,
    bullets: list[str],
    title: str,
    ollama_host: str | None = None,
    ollama_model: str | None = None,
    api_key: str | None = None,
) -> str | None:
    """
    Ask the LLM to confirm or correct the classifier's template prediction.

    Args:
        template_id: The classifier's predicted template
        raw_chunk: The raw source text chunk
        bullets: Extracted bullet points
        title: Slide title
        ollama_host: Ollama API host
        ollama_model: Model to use
        api_key: API key for cloud access

    Returns:
        Corrected template ID string, or None if the LLM call fails
    """
    host = (ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    model = ollama_model or os.getenv("OLLAMA_MODEL", "llama3")
    key = api_key or os.getenv("OLLAMA_API_KEY")

    # Build template list for the prompt
    template_list = "\n".join(
        f"- {tid}: {desc}" for tid, desc in _TEMPLATE_DESCRIPTIONS.items()
    )

    system_prompt = _VALIDATION_SYSTEM_PROMPT.format(template_list=template_list)

    bullets_text = "\n".join(f"- {b}" for b in bullets)
    user_prompt = (
        f"## RAW TEXT CHUNK:\n{raw_chunk[:500]}\n\n"
        f"## SLIDE TITLE:\n{title}\n\n"
        f"## EXTRACTED BULLETS:\n{bullets_text}\n\n"
        f"## CLASSIFIER PREDICTION: {template_id}\n\n"
        f"Is this prediction correct? If not, which template from the list above fits better?\n"
        f"Output ONLY the JSON object."
    )

    url = f"{host}/api/chat"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        text = result.get("message", {}).get("content", "")
        parsed = extract_json_from_response(text)
        if parsed and "corrected_template" in parsed:
            corrected = parsed["corrected_template"].strip().lower()
            return corrected
    except Exception as e:
        print(f"    LLM template validation failed: {e}")

    return None


# =============================================================================
# LLM ENRICHMENT LAYER
# =============================================================================

_ANALOGY_ENRICHMENT_PROMPT = """You are an educational content analyzer. Given this educational text, decide if a real-world analogy would genuinely help a student understand this concept better than a simple summary box.

The analogy must be natural and illuminating — not forced. Only say yes if the mapping is obvious and pedagogically valuable.

## TEXT:
{text}

## TITLE:
{title}

Output ONLY valid JSON:
{{"use_analogy": true/false, "familiar_label": "...", "technical_label": "...", "mappings": [{{"familiar": "...", "technical": "..."}}, ...]}}

If use_analogy is false, the other fields can be empty strings/lists."""

_VENN_ENRICHMENT_PROMPT = """You are an educational content analyzer. Given this comparison text, decide if the two concepts have explicitly shared properties as well as distinct ones, such that a Venn diagram showing overlap would be more informative than a side-by-side table.

Only say yes if shared properties are explicitly stated or strongly implied in the text.

## TEXT:
{text}

## TITLE:
{title}

Output ONLY valid JSON:
{{"use_venn": true/false, "left_label": "...", "right_label": "...", "left_only": [...], "right_only": [...], "shared": [...]}}

If use_venn is false, the other fields can be empty strings/lists."""


# =============================================================================
# CONCEPTUAL ENRICHMENT — LLM picks concept_box / comparison / analogy_diagram
# =============================================================================

_CONCEPTUAL_ENRICHMENT_PROMPT = """You are selecting a text layout enrichment for an educational slide.

Slide Title: {title}
Slide Bullets:
{bullets}
Original Chunk:
{chunk}

Select the most appropriate text layout from exactly these three options:

concept_box — the content defines or summarizes one central concept. There is one main idea being explained.
Signals: "is a", "is defined as", "refers to", "consists of", "is used for", single-subject explanation.

comparison — the content explicitly contrasts two distinct things. Both things are named and their differences are described.
Signals: "versus", "unlike", "whereas", "compared to", "on the other hand", "difference between", two named subjects.

analogy_diagram — the content explains a technical concept by mapping it to a familiar real-world scenario. The analogy must be explicit, not implied.
Signals: "like a", "similar to", "think of", "just as", "works like", "analogous to", "imagine", "picture a".

Return ONLY valid JSON:
{{"layout": "concept_box|comparison|analogy_diagram", "reasoning": "one sentence"}}

If none of the three clearly fits, return:
{{"layout": "concept_box", "reasoning": "default fallback"}}"""


def _enrich_conceptual(
    raw_chunk: str,
    bullets: list[str],
    title: str,
    host: str,
    model: str,
    api_key: str | None,
) -> dict:
    """
    LLM enrichment step for conceptual template.

    Calls the LLM to choose between concept_box, comparison, and analogy_diagram,
    then generates complete params for the chosen sub-type.

    Returns a params dict with _enriched_template set to the chosen layout.
    Falls back to concept_box silently on any error.
    """
    chosen_layout = "concept_box"
    try:
        bullets_text = "\n".join(f"- {b}" for b in bullets)
        chunk_preview = raw_chunk[:600] if raw_chunk else bullets_text
        prompt = _CONCEPTUAL_ENRICHMENT_PROMPT.format(
            title=title,
            bullets=bullets_text,
            chunk=chunk_preview,
        )
        result = _call_ollama(host, model, api_key, prompt)
        if result and result.get("layout") in ("concept_box", "comparison", "analogy_diagram"):
            chosen_layout = result["layout"]
    except Exception:
        pass  # Silent fallback — enrichment is optional

    # Now generate full params for the chosen sub-type
    try:
        if chosen_layout == "comparison":
            params = _generate_conceptual_subtype_params("comparison", bullets, title, host, model, api_key)
        elif chosen_layout == "analogy_diagram":
            params = _generate_conceptual_subtype_params("analogy_diagram", bullets, title, host, model, api_key)
        else:
            params = _generate_conceptual_subtype_params("concept_box", bullets, title, host, model, api_key)
    except Exception:
        params = {"title": title, "points": bullets}
        chosen_layout = "concept_box"

    params["_enriched_template"] = chosen_layout
    return params


def _generate_conceptual_subtype_params(
    sub_template: str,
    bullets: list[str],
    title: str,
    host: str,
    model: str,
    api_key: str | None,
) -> dict:
    """
    Generate params for a conceptual sub-type (concept_box / comparison / analogy_diagram)
    using the existing schema machinery.
    """
    schema_info = TEMPLATE_PARAM_SCHEMAS.get(sub_template)
    if not schema_info:
        return {"title": title, "points": bullets}

    prompt = _build_prompt(sub_template, schema_info, bullets, title)
    result = _call_ollama(host, model, api_key, prompt)

    if result:
        validated = _validate_params(result, sub_template, schema_info)
        if validated:
            return validated

    # Deterministic fallback per sub-type
    return _deterministic_fallback(sub_template, bullets, title)


def _llm_enrich_template(
    template_id: str,
    raw_chunk: str,
    bullets: list[str],
    title: str,
    ollama_host: str | None = None,
    ollama_model: str | None = None,
    api_key: str | None = None,
) -> tuple[str, dict | None]:
    """
    Optional LLM enrichment that may upgrade a classifier prediction to a
    richer visual template.

    Condition A: concept_box → analogy_diagram (if a natural analogy exists)
    Condition B: comparison → venn_diagram (if shared properties exist)

    Returns:
        (template_id, params_or_None)
        If enrichment succeeds: (new_template_id, complete_params_dict)
        If enrichment declines or fails: (original_template_id, None)
    """
    if template_id not in ("concept_box", "comparison"):
        return template_id, None

    host = (ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    model = ollama_model or os.getenv("OLLAMA_MODEL", "llama3")
    key = api_key or os.getenv("OLLAMA_API_KEY")

    text = "\n".join(bullets) if bullets else raw_chunk[:500]

    try:
        if template_id == "concept_box":
            prompt = _ANALOGY_ENRICHMENT_PROMPT.format(text=text, title=title)
            result = _call_ollama(host, model, key, prompt)
            if result and result.get("use_analogy") is True:
                mappings = result.get("mappings", [])
                if mappings and result.get("familiar_label") and result.get("technical_label"):
                    params = {
                        "familiar_label": result["familiar_label"],
                        "technical_label": result["technical_label"],
                        "mappings": mappings,
                        "title": title,
                    }
                    return "analogy_diagram", params

        elif template_id == "comparison":
            prompt = _VENN_ENRICHMENT_PROMPT.format(text=text, title=title)
            result = _call_ollama(host, model, key, prompt)
            if result and result.get("use_venn") is True:
                shared = result.get("shared", [])
                if shared and result.get("left_label") and result.get("right_label"):
                    params = {
                        "left_label": result["left_label"],
                        "right_label": result["right_label"],
                        "left_only": result.get("left_only", []),
                        "right_only": result.get("right_only", []),
                        "shared": shared,
                        "title": title,
                    }
                    return "venn_diagram", params

    except Exception:
        # Enrichment is optional — never surface errors
        pass

    return template_id, None


# =============================================================================
# VISUAL PARAM GENERATOR
# =============================================================================

def generate_visual_params(
    template_id: str,
    bullets: list[str],
    title: str,
    ollama_host: str | None = None,
    ollama_model: str | None = None,
    api_key: str | None = None,
    classifier_confidence: float = 1.0,
    raw_chunk: str = "",
) -> dict | str | None:
    """
    Generate structured visual parameters using LLM.

    For architecture_diagram: returns raw XML string (renderer handles parsing).
    For conceptual: calls LLM enrichment to choose and generate concept_box /
      comparison / analogy_diagram params with _enriched_template key set.
    For all other templates: returns a dict of JSON params as before.

    Args:
        template_id: The chosen template (e.g., 'flowchart', 'stack', 'conceptual')
        bullets: The bullet points from the slide
        title: The slide title
        ollama_host: Ollama API host
        ollama_model: Model to use
        api_key: API key for cloud access
        classifier_confidence: Combined L1×L2 confidence from the classifier
        raw_chunk: Raw source text chunk for LLM validation

    Returns:
        - str (XML) for architecture_diagram
        - dict (with _enriched_template key) for conceptual
        - dict for all other templates
        - None if generation fails irrecoverably
    """
    host = ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = ollama_model or os.getenv("OLLAMA_MODEL", "llama3")
    key = api_key or os.getenv("OLLAMA_API_KEY")

    # ── Special XML path for architecture_diagram ──
    if template_id == "architecture_diagram":
        return _generate_architecture_xml(bullets, title, host, model, key)

    # ── Conceptual path: LLM enrichment picks the sub-type ──
    if template_id == "conceptual":
        return _enrich_conceptual(raw_chunk, bullets, title, host, model, key)

    # ── Legacy LLM Enrichment: try upgrading concept_box/comparison ──
    enriched_template, enriched_params = _llm_enrich_template(
        template_id, raw_chunk, bullets, title, host, model, key
    )
    if enriched_params is not None:
        # Enrichment produced complete params — return directly
        return enriched_params

    # Use enriched template_id (same as original if enrichment declined)
    template_id = enriched_template

    # LLM validation step for low-confidence predictions
    if classifier_confidence < 0.85 and raw_chunk:
        corrected = _llm_validate_template(
            template_id, raw_chunk, bullets, title,
            host, model, key
        )
        if corrected and corrected != template_id and corrected in TEMPLATE_PARAM_SCHEMAS:
            template_id = corrected

    schema_info = TEMPLATE_PARAM_SCHEMAS.get(template_id)

    # Fallback for unknown templates
    if not schema_info:
        return {"title": title, "points": bullets}

    # Build the prompt
    prompt = _build_prompt(template_id, schema_info, bullets, title)

    # Call Ollama
    result = _call_ollama(host, model, key, prompt)

    if result:
        # Validate the result has the expected keys
        validated = _validate_params(result, template_id, schema_info)
        if validated:
            # Fix duplicate chart title
            if template_id == "bar_chart":
                chart_title = str(validated.get("title", ""))
                if chart_title and title and chart_title[:25] == title[:25]:
                    validated["title"] = ""
            return validated

    # If the LLM failed to generate a chart, drop the visual entirely.
    if template_id == "bar_chart":
        return None

    # Fallback: generate basic params deterministically for text-based diagrams
    return _deterministic_fallback(template_id, bullets, title)


def _generate_architecture_xml(
    bullets: list[str],
    title: str,
    host: str,
    model: str,
    api_key: str | None,
) -> str:
    """
    Generate XML params for architecture_diagram using the LLM.

    Returns a raw XML string. The renderer parses it directly.
    Falls back deterministically if the LLM call fails.
    """
    schema_info = TEMPLATE_PARAM_SCHEMAS["architecture_diagram"]
    bullets_text = "\n".join(f"- {b}" for b in bullets)

    prompt = (
        f"Generate an architecture diagram XML for this educational slide.\n\n"
        f"## SLIDE CONTENT:\n"
        f"Title: {title}\n"
        f"Bullets:\n{bullets_text}\n\n"
        f"## DESCRIPTION:\n{schema_info['description']}\n\n"
        f"## XML SCHEMA:\n{schema_info['schema_description']}\n\n"
        f"## EXAMPLE (component style):\n{schema_info['example_component']}\n\n"
        f"## EXAMPLE (layered style):\n{schema_info['example_layered']}\n\n"
        f"## YOUR TASK:\n"
        f"Output ONLY valid XML. No markdown code fences, no explanation, "
        f"no text before or after the XML. Start directly with <architecture."
    )

    url = f"{host.rstrip('/')}/api/chat"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an XML generator for architecture diagrams. Output only valid XML, nothing else."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "top_p": 0.9},
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        result = response.json()
        raw = result.get("message", {}).get("content", "").strip()

        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
            raw = re.sub(r"```$", "", raw).strip()

        # Quick sanity check: must start with <architecture
        if raw.startswith("<architecture"):
            return raw

        # If there's a <architecture block buried in the response, extract it
        match = re.search(r"(<architecture[\s\S]*?</architecture>|<architecture[^/]*/>", raw)
        if match:
            return match.group(0)

    except Exception as e:
        print(f"    Architecture XML generation failed: {e}")

    # Deterministic fallback: build minimal XML from bullets
    return _architecture_xml_fallback(bullets, title)


def _architecture_xml_fallback(bullets: list[str], title: str) -> str:
    """Deterministic XML fallback when LLM call fails entirely."""
    import xml.etree.ElementTree as ET

    root = ET.Element("architecture")
    root.set("title", title[:50] if title else "Architecture")
    root.set("layout", "hierarchical")
    root.set("style", "component")

    # Title node + first bullet as child
    top_label = (title[:20] if title else "System").replace('"', "'")
    top = ET.SubElement(root, "component")
    top.set("id", "top")
    top.set("label", top_label)
    top.set("role", "master")

    for i, b in enumerate(bullets[:6]):
        child = ET.SubElement(root, "component")
        child.set("id", f"c{i}")
        child.set("label", b[:24].strip())
        child.set("role", "worker")
        conn = ET.SubElement(top, "connects")
        conn.set("to", f"c{i}")
        conn.set("label", "")

    return ET.tostring(root, encoding="unicode")


def _build_prompt(
    template_id: str,
    schema_info: dict,
    bullets: list[str],
    title: str,
) -> str:
    """Build the LLM prompt with schema spec and example."""
    bullets_text = "\n".join(f"- {b}" for b in bullets)
    schema_desc = "\n".join(
        f"  - {k}: {v}" for k, v in schema_info["schema"].items()
    )
    example_json = json.dumps(schema_info["example"], indent=2)

    return f"""Generate visual parameters for a "{template_id}" template.

## SLIDE CONTENT:
Title: {title}
Bullets:
{bullets_text}

## REQUIRED OUTPUT SCHEMA for "{template_id}":
{schema_info["description"]}

Parameters:
{schema_desc}

## EXAMPLE OUTPUT:
{example_json}

## YOUR TASK:
Extract the actual concepts, relationships, and data from the bullet points above
and produce the structured JSON parameters that represent this content as a {template_id}.
Use the real terms from the bullets — don't use placeholder text.

Output ONLY a valid JSON object."""


def _call_ollama(
    host: str,
    model: str,
    api_key: str | None,
    prompt: str,
) -> dict | None:
    """Call Ollama API and parse JSON response.

    Uses /api/chat (not /api/generate) for compatibility with
    both local Ollama and cloud Ollama hosts.
    """
    url = f"{host.rstrip('/')}/api/chat"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.3,  # Low temp for structured output
            "top_p": 0.9,
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        result = response.json()
        text = result.get("message", {}).get("content", "")
        return extract_json_from_response(text)
    except Exception as e:
        print(f"    Visual param generation failed: {e}")
        return None


def _validate_params(
    params: dict,
    template_id: str,
    schema_info: dict,
) -> dict | None:
    """Basic validation that the LLM output has the required structure."""
    schema = schema_info["schema"]
    required_keys = list(schema.keys())

    # Check at least one required key is present
    matched = sum(1 for k in required_keys if k in params)
    if matched == 0:
        return None

    return params


def _deterministic_fallback(
    template_id: str,
    bullets: list[str],
    title: str,
) -> dict:
    """
    Deterministic fallback when LLM call fails.

    Produces basic but renderable params from the bullet text.
    """
    if template_id == "concept_box":
        return {"title": title, "points": bullets}
    elif template_id == "comparison":
        mid = len(bullets) // 2
        return {
            "left_title": "Pros",
            "right_title": "Cons",
            "left_items": bullets[:mid] if mid > 0 else bullets[:1],
            "right_items": bullets[mid:] if mid > 0 else bullets[1:],
        }
    elif template_id == "venn_diagram":
        # Split bullets: first half left-only, second half right-only, no shared
        mid = len(bullets) // 2
        left_only = bullets[:mid] if mid > 0 else bullets[:1]
        right_only = bullets[mid:] if mid > 0 else bullets[1:]
        # Derive labels from title
        left_label, right_label = _split_title_labels(title)
        return {
            "left_label": left_label,
            "right_label": right_label,
            "left_only": left_only,
            "right_only": right_only,
            "shared": [],
            "title": title,
        }
    elif template_id == "analogy_diagram":
        # First bullet → familiar concept description, rest → mappings
        familiar_label = _extract_analogy_familiar(bullets)
        technical_label = title
        mappings = []
        for b in bullets[1:] if len(bullets) > 1 else bullets:
            mappings.append({"familiar": b[:40], "technical": b[:40]})
        return {
            "familiar_label": familiar_label,
            "technical_label": technical_label,
            "mappings": mappings if mappings else [{"familiar": "Example", "technical": "Concept"}],
            "title": title,
        }
    elif template_id == "conceptual":
        # Deterministic fallback: produce concept_box-style params with _enriched_template
        return {
            "_enriched_template": "concept_box",
            "title": title,
            "points": bullets,
        }
    elif template_id in ("stack", "queue"):
        return {"items": bullets}
    elif template_id in ("linear_chain", "cycle"):
        return {"nodes": bullets}
    elif template_id == "flowchart":
        nodes = [{"id": chr(65 + i), "label": b[:30], "type": "box"} for i, b in enumerate(bullets)]
        edges = [{"from": chr(65 + i), "to": chr(66 + i)} for i in range(len(bullets) - 1)]
        return {"nodes": nodes, "edges": edges, "direction": "TD"}
    elif template_id == "general_tree":
        root = bullets[0] if bullets else title
        children = {root: bullets[1:]} if len(bullets) > 1 else {}
        return {"root": root, "children": children, "title": title, "relationship_label": ""}
    elif template_id == "architecture_diagram":
        # For XML path: return fallback XML string
        return _architecture_xml_fallback(bullets, title)
    else:
        return {"title": title, "points": bullets}


def _split_title_labels(title: str) -> tuple[str, str]:
    """
    Split a slide title into two labels for venn_diagram.

    Tries splitting on 'vs', 'versus', 'and', 'or'.
    Falls back to 'Concept A' / 'Concept B'.
    """
    title_lower = title.lower()
    for sep in [" vs ", " versus ", " vs. "]:
        if sep in title_lower:
            idx = title_lower.index(sep)
            return title[:idx].strip(), title[idx + len(sep):].strip()
    for sep in [" and ", " or "]:
        if sep in title_lower:
            idx = title_lower.index(sep)
            return title[:idx].strip(), title[idx + len(sep):].strip()
    return "Concept A", "Concept B"


def _extract_analogy_familiar(bullets: list[str]) -> str:
    """
    Extract the familiar concept label from bullet text for analogy_diagram.

    Looks for signals like 'like a', 'similar to', 'think of', 'works like'.
    Falls back to 'Real World'.
    """
    if not bullets:
        return "Real World"
    first = bullets[0].lower()
    patterns = [
        (r"like (?:a |an )(.+?)(?:\.|,|$)", 1),
        (r"similar to (?:a |an )?(.+?)(?:\.|,|$)", 1),
        (r"think of (?:a |an )?(.+?)(?:\.|,|$)", 1),
        (r"works like (?:a |an )?(.+?)(?:\.|,|$)", 1),
        (r"imagine (?:a |an )?(.+?)(?:\.|,|$)", 1),
        (r"picture (?:a |an )?(.+?)(?:\.|,|$)", 1),
    ]
    for pattern, group in patterns:
        m = re.search(pattern, first)
        if m:
            return m.group(group).strip().title()[:30]
    return "Real World"
