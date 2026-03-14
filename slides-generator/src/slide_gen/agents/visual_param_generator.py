"""
Visual Param Generator Agent — Converts bullets + template_id into structured params.

Uses a small LLM call (Ollama) to understand the semantic relationships in the
bullet points and produce the structured parameters each template renderer expects
(nodes, edges, labels, etc.).

This is the bridge between the Visual Classifier output and the Template Registry.
"""

import os
import json
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
    "layers": {
        "description": "Layered architecture diagram showing abstraction levels",
        "schema": {
            "layers": "list of strings — layer names from top to bottom",
        },
        "example": {"layers": ["User Interface", "Business Logic", "Data Access", "Database"]},
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
    "sequence": {
        "description": "A sequence diagram showing message exchanges between actors",
        "schema": {
            "actors": "list of strings — participant names",
            "messages": "list of objects with {from: string, to: string, text: string, type: 'solid'|'dashed'}",
        },
        "example": {
            "actors": ["Client", "Server", "Database"],
            "messages": [
                {"from": "Client", "to": "Server", "text": "HTTP Request", "type": "solid"},
                {"from": "Server", "to": "Database", "text": "Query", "type": "solid"},
                {"from": "Database", "to": "Server", "text": "Results", "type": "dashed"},
                {"from": "Server", "to": "Client", "text": "Response", "type": "dashed"},
            ],
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
    "timeline": {
        "description": "A timeline showing events in chronological order",
        "schema": {
            "title": "string — timeline title",
            "events": "list of objects with {time: string, description: string}",
        },
        "example": {
            "title": "Python History",
            "events": [
                {"time": "1991", "description": "Python 1.0 released"},
                {"time": "2000", "description": "Python 2.0 released"},
                {"time": "2008", "description": "Python 3.0 released"},
            ],
        },
    },
    "process_flow": {
        "description": "A simple sequential process: step1 → step2 → step3",
        "schema": {
            "steps": "list of strings — sequential process steps",
            "direction": "string — 'LR' (left-right) or 'TD' (top-down), default 'LR'",
        },
        "example": {"steps": ["Input Data", "Validate", "Process", "Output"], "direction": "LR"},
    },

    # --- Matplotlib Charts ---
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
    "pie_chart": {
        "description": "A pie chart showing proportions/percentages",
        "schema": {
            "labels": "list of strings — slice labels",
            "values": "list of numbers — slice values (will be converted to percentages)",
            "title": "string — chart title",
        },
        "example": {"labels": ["Stack", "Heap", "Code"], "values": [30, 50, 20], "title": "Memory Layout"},
    },
    "grid": {
        "description": "A data grid/table with rows and columns",
        "schema": {
            "data": "list of lists — 2D array of cell values",
            "col_labels": "list of strings — column headers (optional)",
            "row_labels": "list of strings — row headers (optional)",
            "title": "string — table title",
        },
        "example": {"data": [["O(1)", "O(n)"], ["O(n)", "O(1)"]], "col_labels": ["Access", "Insert"], "row_labels": ["Array", "LinkedList"], "title": "Time Complexity"},
    },
    "line_chart": {
        "description": "A line chart showing trends over a continuous axis",
        "schema": {
            "x_values": "list of numbers/strings — x-axis points",
            "y_values": "list of numbers — y-axis values",
            "title": "string — chart title",
            "xlabel": "string — x-axis label",
            "ylabel": "string — y-axis label",
        },
        "example": {"x_values": [1, 2, 4, 8, 16], "y_values": [1, 2, 4, 8, 16], "title": "Linear Growth", "xlabel": "Input Size", "ylabel": "Time"},
    },
    "venn": {
        "description": "A Venn diagram showing set relationships and overlap",
        "schema": {
            "set_a_label": "string — label for set A",
            "set_b_label": "string — label for set B",
            "set_a_only": "string — what's unique to A",
            "set_b_only": "string — what's unique to B",
            "intersection": "string — what A and B share",
            "title": "string — diagram title",
        },
        "example": {"set_a_label": "Python", "set_b_label": "JavaScript", "set_a_only": "Indentation syntax", "set_b_only": "Browser runtime", "intersection": "Dynamic typing", "title": "Language Comparison"},
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
8. For timelines: extract chronological order from the content"""


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
) -> dict:
    """
    Generate structured visual parameters using LLM.

    Args:
        template_id: The chosen template (e.g., 'flowchart', 'stack')
        bullets: The bullet points from the slide
        title: The slide title
        ollama_host: Ollama API host
        ollama_model: Model to use
        api_key: API key for cloud access

    Returns:
        Dict of structured parameters for the template renderer
    """
    host = ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = ollama_model or os.getenv("OLLAMA_MODEL", "llama3")
    key = api_key or os.getenv("OLLAMA_API_KEY")

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
            return validated

    # Fallback: generate basic params deterministically
    return _deterministic_fallback(template_id, bullets, title)


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
    """Call Ollama API and parse JSON response."""
    url = f"{host.rstrip('/')}/api/generate"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False,
        "options": {
            "temperature": 0.3,  # Low temp for structured output
            "top_p": 0.9,
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        result = response.json()
        text = result.get("response", "")
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
    elif template_id in ("process_flow",):
        return {"steps": bullets, "direction": "LR"}
    elif template_id == "timeline":
        return {
            "title": title,
            "events": [{"time": f"Step {i+1}", "description": b} for i, b in enumerate(bullets)],
        }
    elif template_id in ("stack", "queue"):
        return {"items": bullets}
    elif template_id in ("linear_chain", "cycle"):
        return {"nodes": bullets}
    elif template_id == "layers":
        return {"layers": bullets}
    elif template_id == "flowchart":
        nodes = [{"id": chr(65 + i), "label": b[:30], "type": "box"} for i, b in enumerate(bullets)]
        edges = [{"from": chr(65 + i), "to": chr(66 + i)} for i in range(len(bullets) - 1)]
        return {"nodes": nodes, "edges": edges, "direction": "TD"}
    elif template_id == "sequence":
        return {
            "actors": ["Actor A", "Actor B"],
            "messages": [{"from": "Actor A", "to": "Actor B", "text": b[:30], "type": "solid"} for b in bullets],
        }
    elif template_id in ("bar_chart", "pie_chart"):
        return {
            "labels": [b[:20] for b in bullets],
            "values": [100 // max(len(bullets), 1)] * len(bullets),
            "title": title,
        }
    elif template_id == "line_chart":
        return {
            "x_values": list(range(1, len(bullets) + 1)),
            "y_values": list(range(1, len(bullets) + 1)),
            "title": title,
            "xlabel": "X",
            "ylabel": "Y",
        }
    elif template_id == "grid":
        return {
            "data": [[b] for b in bullets],
            "col_labels": ["Content"],
            "title": title,
        }
    elif template_id == "venn":
        return {
            "set_a_label": bullets[0][:20] if len(bullets) > 0 else "A",
            "set_b_label": bullets[1][:20] if len(bullets) > 1 else "B",
            "set_a_only": bullets[0] if len(bullets) > 0 else "A only",
            "set_b_only": bullets[1] if len(bullets) > 1 else "B only",
            "intersection": bullets[2] if len(bullets) > 2 else "Shared",
            "title": title,
        }
    else:
        return {"title": title, "points": bullets}
