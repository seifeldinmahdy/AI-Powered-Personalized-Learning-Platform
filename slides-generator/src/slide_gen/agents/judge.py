"""
Visual Judge Agent — fast LLM verification layer around the trained classifier.

This is the inference-time complement to the offline data judge. The trained
hierarchical classifier (the project's core AI contribution) stays the primary
predictor; the judge is a *cheap, fast* LLM that makes the compound system
robust to the classifier's mistakes in two places:

  1. judge_template()  — TEMPLATE ARBITRATION. Given the raw chunk + the
     classifier's top-k shortlist, pick the single best template. This catches
     cases where the right answer is the classifier's #2/#3 (or where conceptual
     vs a structural template is ambiguous). Always-on, one fast call.

  2. judge_params()    — FAITHFULNESS CHECK. Given the generated params and the
     bullets, decide whether the visual actually represents the content (no
     hallucinated nodes/edges, right structure). Lets the caller regenerate once
     or fall back instead of rendering a wrong diagram.

Design notes:
  - Uses a FAST free-plan model (VISUAL_JUDGE_MODEL, default nemotron-3-nano:30b)
    so per-slide latency stays low — NOT the heavy gpt-oss:120b generator.
  - Reads params (JSON/XML text), never pixels — diagram↔text faithfulness is
    structural/semantic, which a text LLM judges far more reliably than CLIP.
  - Fails OPEN: any error returns None / "faithful", so the judge can never make
    the pipeline worse than the classifier-only path.
  - Disabled by setting VISUAL_JUDGE_ENABLED=0.
"""

import os
import json

import requests

from slide_gen.data_engine.utils import extract_json_from_response


# Classifier-level template universe the judge chooses from (matches the
# hierarchy's template ids). concept_box / comparison / analogy_diagram / venn
# are downstream *enrichments* of `conceptual`, so they are NOT judge outputs.
JUDGE_LABELS: dict[str, str] = {
    "linear_chain": "Linked list / sequential chain of nodes with next pointers",
    "binary_tree": "Binary tree / BST with strict left & right children",
    "general_tree": "N-ary tree with arbitrary branching: trie, B-tree, file system, inheritance",
    "stack": "LIFO structure: push / pop / peek, top of stack, call stack",
    "queue": "FIFO structure: enqueue / dequeue, front & rear, BFS queue",
    "graph": "Vertices and edges, adjacency list/matrix, network, traversal over a graph",
    "flowchart": "Process WITH decision branching: if/else, yes/no, conditional steps, loops",
    "cycle": "Circular/repeating process that loops back to the start",
    "bar_chart": "Explicit numeric comparison across categories (needs real numbers)",
    "architecture_diagram": "System/model architecture: named components + connections, layered stacks (NN, microservices, OSI)",
    "conceptual": "Explains/defines/summarizes/contrasts a concept with no specific structure, process, or architecture",
    "none": "Pure narrative with no explanatory, structural, or quantitative angle",
}


def _judge_enabled() -> bool:
    return os.getenv("VISUAL_JUDGE_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def _judge_model() -> str:
    return os.getenv("VISUAL_JUDGE_MODEL", "nemotron-3-nano:30b")


def _call_judge(system_prompt: str, user_prompt: str, timeout: int = 45) -> dict | None:
    """Call the fast judge model via /api/chat with JSON output. Fails open (None)."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = _judge_model()
    key = os.getenv("OLLAMA_API_KEY")

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
        "options": {"temperature": 0.1, "top_p": 0.9},
    }
    try:
        r = requests.post(f"{host}/api/chat", json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        text = r.json().get("message", {}).get("content", "")
        return extract_json_from_response(text)
    except Exception:
        return None


# =============================================================================
# 1) TEMPLATE ARBITRATION
# =============================================================================

_ARBITER_SYSTEM = """You are a visual-template arbiter for educational slides.
A trained classifier proposes candidate templates; you pick the single best one
for the content. You may choose a template NOT in the shortlist if the shortlist
is clearly wrong. Output ONLY JSON."""


def judge_template(
    raw_chunk: str,
    bullets: list[str],
    title: str,
    candidates: list[str],
    timeout: int = 45,
) -> dict | None:
    """Pick the best template given the chunk and the classifier's shortlist.

    Args:
        raw_chunk: source text
        bullets: extracted bullets
        title: slide title
        candidates: classifier's top-k template ids (the shortlist / prior)

    Returns:
        {"template_id": str, "confidence": float, "reasoning": str} or None
        (None → caller keeps the classifier's own choice).
    """
    if not _judge_enabled():
        return None

    label_list = "\n".join(f"- {tid}: {desc}" for tid, desc in JUDGE_LABELS.items())
    shortlist = ", ".join(candidates) if candidates else "(none)"
    bullets_text = "\n".join(f"- {b}" for b in bullets)

    user = (
        f"## TEMPLATE OPTIONS:\n{label_list}\n\n"
        f"## CLASSIFIER SHORTLIST (its top guesses, best first): {shortlist}\n\n"
        f"## SLIDE TITLE:\n{title}\n\n"
        f"## BULLETS:\n{bullets_text}\n\n"
        f"## RAW TEXT (for context):\n{raw_chunk[:600]}\n\n"
        "Pick the SINGLE best template id for this content. Prefer the shortlist "
        "unless it is clearly wrong. Key rules: use a structural template "
        "(stack/queue/graph/tree/linear_chain) only when the content describes "
        "that structure's mechanics; use flowchart only with real decision "
        "branching; use bar_chart only with explicit numbers; use conceptual for "
        "definitions/explanations/comparisons; use none only for pure narrative.\n\n"
        'Output ONLY: {"template_id": "...", "confidence": 0.0-1.0, "reasoning": "one sentence"}'
    )

    result = _call_judge(_ARBITER_SYSTEM, user, timeout=timeout)
    if not result or "template_id" not in result:
        return None
    tid = str(result["template_id"]).strip().lower()
    if tid not in JUDGE_LABELS:
        return None
    try:
        conf = float(result.get("confidence", 0.8))
    except (TypeError, ValueError):
        conf = 0.8
    return {
        "template_id": tid,
        "confidence": max(0.0, min(1.0, conf)),
        "reasoning": str(result.get("reasoning", ""))[:200],
    }


# =============================================================================
# 2) PARAMS FAITHFULNESS
# =============================================================================

_FAITHFUL_SYSTEM = """You verify that a slide's visual parameters faithfully
represent the slide's content. You check for hallucinated or missing elements
and gross structural mismatches — not style. Output ONLY JSON."""


def judge_params(
    template_id: str,
    params: dict | str,
    bullets: list[str],
    title: str,
    timeout: int = 45,
) -> dict:
    """Check whether generated params faithfully represent the bullets.

    Returns {"faithful": bool, "issues": [str, ...]}. Fails OPEN: on any error
    or when disabled, returns {"faithful": True} so the caller keeps the visual.
    """
    if not _judge_enabled():
        return {"faithful": True, "issues": []}

    if isinstance(params, dict):
        params_text = json.dumps(params, ensure_ascii=False)[:1200]
    else:
        params_text = str(params)[:1200]
    bullets_text = "\n".join(f"- {b}" for b in bullets)

    user = (
        f"## TEMPLATE: {template_id}\n\n"
        f"## SLIDE TITLE:\n{title}\n\n"
        f"## BULLETS (ground truth content):\n{bullets_text}\n\n"
        f"## GENERATED VISUAL PARAMS:\n{params_text}\n\n"
        "Do these params faithfully represent the bullets for this template? "
        "Reject only for real problems: invented entities not in the content, "
        "key content missing, wrong structure (e.g. a flowchart with no decision, "
        "a bar_chart with fabricated numbers, nodes/edges that contradict the text). "
        "Minor wording differences are fine.\n\n"
        'Output ONLY: {"faithful": true/false, "issues": ["..."]}'
    )

    result = _call_judge(_FAITHFUL_SYSTEM, user, timeout=timeout)
    if not result or "faithful" not in result:
        return {"faithful": True, "issues": []}  # fail open
    faithful = bool(result["faithful"])
    issues = result.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)]
    return {"faithful": faithful, "issues": [str(i)[:120] for i in issues][:5]}
