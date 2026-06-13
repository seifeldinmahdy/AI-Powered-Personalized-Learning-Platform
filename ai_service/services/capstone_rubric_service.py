"""
Capstone AI service — rubric generation, spec extraction, proposal mapping, and evaluation.

LLM-as-judge invariant: The LLM returns ONLY binary pass/fail per rubric item
plus a short evidence quote.  Numeric scores are never emitted by the LLM.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore

from schemas.capstone import (
    CapstoneEvalRequest,
    CapstoneEvalResult,
    CapstoneRubricDraft,
    DraftRubricRequest,
    DraftRubricResponse,
    ExtractSpecRequest,
    ExtractSpecResponse,
    MapProposalRequest,
    MapProposalResponse,
    RubricItemResult,
    CapstoneAssistRequest,
    CapstoneAssistResponse,
    CapstoneRunRequest,
    CapstoneRunResponse,
    TeamRolesRequest,
)

logger = logging.getLogger(__name__)

# Max lines of code the assist may return (illustrative/analogous only).
ASSIST_MAX_CODE_LINES = 10

_eval_client: OllamaClient | None = None
_gen_client: OllamaClient | None = None


def _get_eval_client() -> OllamaClient:
    global _eval_client
    if _eval_client is None:
        _eval_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_EVAL_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=180,
        )
    return _eval_client


def _get_gen_client() -> OllamaClient:
    global _gen_client
    if _gen_client is None:
        _gen_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_GEN_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=120,
        )
    return _gen_client


def _as_item_list(data, key: str = "rubric_items") -> list:
    """Normalise an LLM JSON response to a list of item dicts."""
    if isinstance(data, dict):
        return data.get(key, [])
    if isinstance(data, list):
        return data
    return []


# ---------------------------------------------------------------------------
# draft_core_criteria
# ---------------------------------------------------------------------------

async def draft_core_criteria(req: DraftRubricRequest) -> DraftRubricResponse:
    """
    Ask the LLM to draft a set of binary rubric criteria for a capstone.
    Each criterion is a yes/no question that a judge can evaluate from code alone.
    """
    system = (
        "You are an expert software engineering instructor designing a capstone project rubric.\n"
        "Each rubric criterion MUST be a binary yes/no question answerable by reading the submitted code.\n"
        "Do NOT include scores, grades, or percentages — just criteria.\n"
        "Respond with valid JSON only, no prose outside the JSON block."
    )

    team_note = (
        "This is a TEAM project. Include at least 2 criteria with min_team_size=2 "
        "(collaboration-specific: PR reviews, branch history, code attribution)."
        if req.team_mode == "team"
        else "This is a SOLO project. Set min_team_size=1 for all criteria."
    )

    user = f"""
Capstone title: {req.capstone_title}
Brief: {req.brief}
Spec mode: {req.spec_mode}
{team_note}

Generate 8–12 rubric criteria. Return JSON:
```json
{{
  "rubric_items": [
    {{
      "text": "<binary yes/no question>",
      "category": "core",
      "weight": 1,
      "min_team_size": 1,
      "order": 0,
      "rationale": "<one sentence why this matters>"
    }}
  ]
}}
```
- category: "core" (must-pass) or "stretch" (bonus)
- weight: 1–3 (higher = more important)
- min_team_size: 1 (all) or 2+ (team-only criteria)
"""
    client = _get_gen_client()
    try:
        data = client.chat_json(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.4,
            timeout_override=120,
        )
        items = [CapstoneRubricDraft(**item) for item in _as_item_list(data)]
    except Exception:
        logger.exception("draft_core_criteria: failed to parse LLM response")
        items = []
    return DraftRubricResponse(rubric_items=items)


# ---------------------------------------------------------------------------
# extract_criteria_from_spec
# ---------------------------------------------------------------------------

async def extract_criteria_from_spec(req: ExtractSpecRequest) -> ExtractSpecResponse:
    """
    Extract binary rubric criteria from an admin-supplied specification document.
    """
    system = (
        "You are an expert at extracting verifiable software requirements.\n"
        "Convert each functional requirement into a binary yes/no rubric question.\n"
        "Respond with valid JSON only."
    )

    team_note = (
        "This is a TEAM project. Add at least 1 collaboration criterion (min_team_size=2)."
        if req.team_mode == "team"
        else "Solo project — set min_team_size=1 for all."
    )

    user = f"""
Capstone title: {req.capstone_title}
{team_note}

Specification document:
---
{req.spec_text[:6000]}
---

Extract all verifiable requirements as binary rubric criteria. Return JSON:
```json
{{
  "rubric_items": [
    {{
      "text": "<binary yes/no question>",
      "category": "core",
      "weight": 1,
      "min_team_size": 1,
      "order": 0,
      "rationale": "<source in spec>"
    }}
  ]
}}
```
"""
    client = _get_gen_client()
    try:
        data = client.chat_json(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            timeout_override=120,
        )
        items = [CapstoneRubricDraft(**item) for item in _as_item_list(data)]
    except Exception:
        logger.exception("extract_criteria_from_spec: failed to parse LLM response")
        items = []
    return ExtractSpecResponse(rubric_items=items)


# ---------------------------------------------------------------------------
# map_core_to_proposal
# ---------------------------------------------------------------------------

async def map_core_to_proposal(req: MapProposalRequest) -> MapProposalResponse:
    """
    Assess whether a student proposal covers the core criteria.
    Returns a coverage mapping + suggestions.  confidence_score is a feasibility
    indicator (0–1), NOT a grade.
    """
    system = (
        "You are evaluating whether a student's project proposal covers required criteria.\n"
        "For each criterion, decide: covered (yes/no) based on the proposal.\n"
        "confidence_score (0.0–1.0) reflects feasibility of the proposal in the given time, not quality.\n"
        "Respond with valid JSON only. Do NOT emit any numeric grade or score for the student."
    )

    criteria_json = json.dumps(req.core_criteria, indent=2)
    features_str = "\n".join(f"- {f}" for f in req.planned_features)

    user = f"""
Capstone: {req.capstone_title}
Brief: {req.brief}

Core criteria:
{criteria_json}

Student proposal title: {req.proposal_title}
Description: {req.proposal_description}
Planned features:
{features_str}

Evaluate coverage. Return JSON:
```json
{{
  "confidence_score": 0.8,
  "coverage": [
    {{"criterion_id": 1, "covered": true, "reason": "Feature X addresses this."}}
  ],
  "suggestions": ["Consider adding Y to fully address criterion Z."]
}}
```
"""
    client = _get_eval_client()
    try:
        data = client.chat_json(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            timeout_override=120,
        )
        if not isinstance(data, dict):
            data = {}
        return MapProposalResponse(
            confidence_score=float(data.get("confidence_score", 0.5)),
            coverage=data.get("coverage", []),
            suggestions=data.get("suggestions", []),
        )
    except Exception:
        logger.exception("map_core_to_proposal: failed to parse LLM response")
        return MapProposalResponse(confidence_score=0.5, coverage=[], suggestions=[])


# ---------------------------------------------------------------------------
# evaluate_capstone_rubric
# ---------------------------------------------------------------------------

async def evaluate_capstone_rubric(req: CapstoneEvalRequest) -> CapstoneEvalResult:
    """
    Judge the submitted code bundle against each rubric item.

    The LLM returns ONLY binary pass/fail + evidence quote per item.
    NUMERIC SCORE IS NEVER COMPUTED OR RETURNED HERE — that happens in Django.
    """
    system = (
        "You are a strict software engineering evaluator.\n"
        "For each rubric criterion, answer YES (passed=true) or NO (passed=false) "
        "based solely on evidence found in the submitted code.\n"
        "Provide a SHORT evidence quote (≤ 2 sentences) from the code to justify each decision.\n"
        "Do NOT compute totals, percentages, scores, or grades.\n"
        "Respond with valid JSON only."
    )

    criteria_json = json.dumps(
        [{"id": item.id, "text": item.text} for item in req.rubric_items],
        indent=2,
    )

    proposal_section = (
        f"\nStudent proposal context:\n{req.proposal_text[:500]}\n"
        if req.proposal_text
        else ""
    )

    # Truncate code bundle to avoid context overflow (~50k chars ≈ ~12k tokens)
    code_preview = req.code_bundle[:50000]
    if len(req.code_bundle) > 50000:
        code_preview += "\n... [truncated for length] ..."

    user = f"""
Capstone: {req.capstone_title}
Brief: {req.brief}
{proposal_section}
Rubric criteria to evaluate:
{criteria_json}

Submitted code:
```
{code_preview}
```

For EACH criterion ID, return passed (true/false) and evidence (short quote or "not found"). Return JSON:
```json
{{
  "results": {{
    "1": {{"passed": true, "evidence": "Line 42: <code quote>"}},
    "2": {{"passed": false, "evidence": "No test files found."}}
  }},
  "feedback": "Overall qualitative comment for the student. No score."
}}
```
"""
    client = _get_eval_client()
    try:
        data = client.chat_json(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            timeout_override=180,
        )
        if not isinstance(data, dict):
            data = {}
        raw_results = data.get("results", {})
        results: dict[str, RubricItemResult] = {}
        for item_id, val in raw_results.items():
            results[str(item_id)] = RubricItemResult(
                passed=bool(val.get("passed", False)),
                evidence=str(val.get("evidence", "")),
            )
        return CapstoneEvalResult(
            results=results,
            feedback=data.get("feedback", ""),
        )
    except Exception:
        logger.exception("evaluate_capstone_rubric: failed to parse LLM response")
        # Return all-failed results on parse error
        results = {
            str(item.id): RubricItemResult(passed=False, evidence="Evaluation parse error.")
            for item in req.rubric_items
        }
        return CapstoneEvalResult(results=results, feedback="Evaluation failed — please retry.")


# ---------------------------------------------------------------------------
# Batch 3 — scoped AI assist (Socratic, rubric-aware, code-capped)
# ---------------------------------------------------------------------------

# Mirror the tutor's Socratic skills (reused, not re-invented).
_SOCRATIC_FALLBACK = (
    "SKILL — SOCRATIC GUARD: Never give the student the direct answer. Ask guiding "
    "questions, provide hints, and help them arrive at the answer themselves. Only "
    "after repeated failed attempts provide a small partial answer."
)


def _socratic_skill_text() -> str:
    """Reuse SOCRATIC_GUARD / SOCRATIC_SCAFFOLD from the tutor service if available."""
    try:
        from services.tutor_service import TUTOR_SKILLS  # lazy to avoid import cost
        parts = [TUTOR_SKILLS.get("SOCRATIC_GUARD", ""), TUTOR_SKILLS.get("SOCRATIC_SCAFFOLD", "")]
        joined = "\n\n".join(p for p in parts if p)
        return joined or _SOCRATIC_FALLBACK
    except Exception:
        return _SOCRATIC_FALLBACK


def _cap_code_blocks(text: str, max_lines: int = ASSIST_MAX_CODE_LINES) -> str:
    """
    Post-processing guard: trim any fenced code block to at most `max_lines`
    lines so the assist can never ghost-write a full solution.
    """
    import re

    def _trim(match: "re.Match") -> str:
        fence = match.group(1) or "```"
        lang = match.group(2) or ""
        body = match.group(3) or ""
        lines = body.split("\n")
        # Drop a trailing empty line introduced by the fence
        if lines and lines[-1].strip() == "":
            lines = lines[:-1]
        if len(lines) > max_lines:
            lines = lines[:max_lines] + ["# … (truncated — assist shows only a few illustrative lines)"]
        return f"{fence}{lang}\n" + "\n".join(lines) + f"\n{fence}"

    pattern = re.compile(r"(```)([a-zA-Z0-9_+-]*)\n([\s\S]*?)```")
    return pattern.sub(_trim, text)


async def assist_student(req: CapstoneAssistRequest) -> CapstoneAssistResponse:
    """
    Rubric-aware Socratic helper. Explains concepts, locates bugs, asks leading
    questions, reviews the student's own snippet, and scaffolds AROUND graded
    features — but NEVER implements rubric-bearing functionality.
    """
    rubric_block = "\n".join(f"- {r}" for r in req.rubric_items) or "(no rubric provided)"
    system = (
        "You are a capstone project mentor. Help the student learn WITHOUT doing the "
        "graded work for them.\n\n"
        f"{_socratic_skill_text()}\n\n"
        "STRICT RULES:\n"
        "1. NEVER implement or write out any functionality that a rubric criterion grades. "
        "If the question asks you to build a graded feature, refuse and instead ask leading "
        "questions or explain the underlying concept.\n"
        f"2. Any code you show must be ≤{ASSIST_MAX_CODE_LINES} lines and only illustrative or "
        "analogous — never the student's actual graded solution.\n"
        "3. You MAY: explain concepts, locate bugs in the student's own snippet, suggest "
        "debugging strategies, and scaffold around (not through) graded features.\n\n"
        "These rubric criteria are GRADED — do not implement any of them:\n"
        f"{rubric_block}"
    )

    snippet_block = f"\n\nStudent's current snippet:\n```\n{req.code_snippet[:3000]}\n```" if req.code_snippet else ""
    user = (
        f"Capstone: {req.capstone_title}\n"
        f"Brief: {req.brief}\n\n"
        f"Student question: {req.question}{snippet_block}"
    )

    client = _get_eval_client()
    try:
        raw = client.chat(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.4,
            timeout_override=90,
        )
        answer = raw if isinstance(raw, str) else str(raw)
    except Exception:
        logger.exception("assist_student LLM call failed")
        answer = "Sorry, I couldn't generate help right now. Try rephrasing your question."

    # Defense in depth: enforce the code-line cap even if the model ignored it.
    answer = _cap_code_blocks(answer)
    return CapstoneAssistResponse(answer=answer)


# ---------------------------------------------------------------------------
# Team role advisor — advisory "suggested division of labor" (lead/support).
# NEVER feeds scoring, the verdict, or contribution checks. Text advice only.
# ---------------------------------------------------------------------------

# Below this average evidence-per-member we don't trust the mastery vectors and
# fall back to a balanced/rotation suggestion instead of inventing strengths.
TEAM_ROLES_MIN_AVG_EVIDENCE = 3


def _total_evidence(members: list) -> int:
    total = 0
    for m in members:
        for entry in (m.mastery or {}).values():
            if isinstance(entry, dict):
                try:
                    total += int(entry.get("evidence") or 0)
                except (TypeError, ValueError):
                    pass
    return total


def _balanced_team_roles(members: list, rubric_items: list, *,
                         limited_data: bool, team_note: str | None = None) -> dict:
    """
    Deterministic, evidence-free fallback: rotate the lead across members so
    everyone leads at least one area and supports the rest. Makes NO strength
    claims — used when mastery data is too thin (or the LLM is unavailable).
    """
    handles = [m.handle for m in members] or ["member"]
    core = [r for r in rubric_items if r.category == "core"] or rubric_items

    areas: list[dict] = []
    if core:
        # one area per core criterion, capped so the page stays readable
        for idx, crit in enumerate(core[: max(len(handles), 4)]):
            lead = handles[idx % len(handles)]
            areas.append({
                "area": (crit.text[:60] + ("…" if len(crit.text) > 60 else "")),
                "rubric_refs": [crit.text],
                "lead": lead,
                "support": [h for h in handles if h != lead],
                "rationale": "Rotated lead — limited mastery data so far; pair up and learn together.",
            })
    else:
        areas.append({
            "area": "Whole project",
            "rubric_refs": [],
            "lead": handles[0],
            "support": handles[1:],
            "rationale": "Share the work evenly and pair on the hardest parts.",
        })

    growth = [
        {"member": h, "grow_on": "all areas",
         "why": "Not enough demonstrated data yet — rotate leads and tackle hard parts in pairs."}
        for h in handles
    ]
    note = team_note or (
        "These are starter suggestions based on limited data so far. Split the work "
        "evenly, rotate who leads, and pair up on the hardest parts — revisit these "
        "suggestions as you make progress through the project."
    )
    return {"areas": areas, "per_member_growth": growth, "team_note": note,
            "limited_data": limited_data}


def _coerce_role_advice(data, members: list) -> dict | None:
    """Defensively normalise the LLM's JSON into the strict output shape."""
    if not isinstance(data, dict):
        return None
    areas_in = data.get("areas")
    if not isinstance(areas_in, list) or not areas_in:
        return None
    areas = []
    for a in areas_in:
        if not isinstance(a, dict):
            continue
        support = a.get("support") or []
        if isinstance(support, str):
            support = [support]
        areas.append({
            "area": str(a.get("area", "")),
            "rubric_refs": [str(r) for r in (a.get("rubric_refs") or []) if r],
            "lead": str(a.get("lead", "")),
            "support": [str(s) for s in support if s],
            "rationale": str(a.get("rationale", "")),
        })

    growth = []
    for g in (data.get("per_member_growth") or []):
        if isinstance(g, dict):
            growth.append({
                "member": str(g.get("member", "")),
                "grow_on": str(g.get("grow_on", "")),
                "why": str(g.get("why", "")),
            })

    return {
        "areas": areas,
        "per_member_growth": growth,
        "team_note": str(data.get("team_note", "")),
        "limited_data": False,
    }


def suggest_team_roles(req: TeamRolesRequest) -> dict:
    """
    Rubric-aware, mastery-grounded advisory division of labor (lead/support).
    Advisory only — the team may ignore it; it never affects any score or gate.

    Graceful degradation: with empty/low-evidence mastery we return a balanced
    rotation and a limited_data flag rather than fabricating strengths.
    """
    members = req.members or []
    if len(members) < 2:
        # Solo (or malformed) — caller skips display; nothing to divide.
        return {"areas": [], "per_member_growth": [], "team_note": "", "limited_data": True}

    # ---- Degradation gate (computed in code, not by the LLM) ----
    avg_evidence = _total_evidence(members) / max(len(members), 1)
    if avg_evidence < TEAM_ROLES_MIN_AVG_EVIDENCE:
        return _balanced_team_roles(members, req.rubric_items, limited_data=True)

    # ---- Mastery-grounded suggestion via the LLM ----
    rubric_lines = "\n".join(
        f"- [{r.category}] {r.text}" + (f"  (concept: {r.concept_id})" if r.concept_id else "")
        for r in req.rubric_items
    ) or "(no rubric provided)"

    member_lines = []
    for m in members:
        strengths = sorted(
            (
                {"concept": e.get("label") or cid, "score": e.get("score"), "evidence": e.get("evidence", 0)}
                for cid, e in (m.mastery or {}).items() if isinstance(e, dict)
            ),
            key=lambda x: (x["score"] if x["score"] is not None else 0.0),
            reverse=True,
        )
        compact = ", ".join(
            f"{s['concept']}={s['score']} (n={s['evidence']})" for s in strengths
        ) or "no demonstrated mastery yet"
        member_lines.append(f"- {m.handle}: {compact}")
    members_block = "\n".join(member_lines)

    system = (
        "You advise a student project team on a SUGGESTED division of labor. This is "
        "advisory only — the team may ignore it. It must NEVER read like a grade.\n\n"
        "FRAMING — lead/support, not a hard split: everyone touches everything. For each "
        "area name a LEAD (drives it) and SUPPORT(s) (contribute and learn from the lead). "
        "The platform's mission is to BRIDGE weaknesses, so:\n"
        "  • every member must LEAD at least one area, and\n"
        "  • every member must SUPPORT an area that targets their WEAKEST concept, so they "
        "grow instead of avoiding it.\n"
        "EVIDENCE HONESTY: only claim a member is strong at something if their mastery "
        "score/evidence backs it; cite the concept in the rationale. Never invent strengths.\n"
        "Respond with valid JSON only."
    )
    user = f"""Capstone: {req.capstone_title}
Brief: {req.brief}

Rubric criteria:
{rubric_lines}

Team members and their demonstrated concept mastery (score 0–1, n = evidence count),
restricted to this course's concepts:
{members_block}

Group the work into a handful of areas mapped to the rubric criteria/concepts. Return JSON:
```json
{{
  "areas": [
    {{"area": "Data persistence", "rubric_refs": ["<criterion text>"],
      "lead": "<handle>", "support": ["<handle>"],
      "rationale": "one line tied to mastery, e.g. leads — strongest on py.io.files (0.8, n=5)"}}
  ],
  "per_member_growth": [
    {{"member": "<handle>", "grow_on": "<concept/area>", "why": "supports here to bridge their weakest concept"}}
  ],
  "team_note": "2–3 sentence friendly framing; make clear it's a suggestion"
}}
```"""

    client = _get_eval_client()
    try:
        data = client.chat_json(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            timeout_override=90,
        )
        coerced = _coerce_role_advice(data, members)
        if coerced is None:
            raise ValueError("unparseable team-roles response")
        return coerced
    except Exception:
        logger.exception("suggest_team_roles: falling back to balanced suggestion")
        return _balanced_team_roles(
            members, req.rubric_items, limited_data=False,
            team_note=("We couldn't generate tailored suggestions right now, so here's an "
                       "even split — rotate who leads and pair on the hard parts. Try Refresh later."),
        )


# ---------------------------------------------------------------------------
# Batch 3 — run uncommitted files in the sandbox (local feedback only)
# ---------------------------------------------------------------------------

def run_capstone_files(req: CapstoneRunRequest) -> CapstoneRunResponse:
    """
    Write the (uncommitted) files to a temp dir and run the entry file in a
    short-lived subprocess. Reuses the lab sandbox approach. Python-only.
    """
    import os as _os
    import re
    import subprocess
    import sys as _sys
    import tempfile

    if not req.files:
        return CapstoneRunResponse(success=False, stderr="No files to run.", exit_code=1)

    _PATH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")
    timeout_seconds = 8

    with tempfile.TemporaryDirectory() as tmpdir:
        py_files: list[str] = []
        for f in req.files:
            path = f.path
            # Path safety: no traversal, no absolute paths
            if not path or path.startswith("/") or "\\" in path or ".." in path.split("/") or not _PATH_RE.match(path):
                return CapstoneRunResponse(success=False, stderr=f"Unsafe path: {path}", exit_code=1)
            dest = _os.path.join(tmpdir, path)
            _os.makedirs(_os.path.dirname(dest) or tmpdir, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as handle:
                handle.write(f.content or "")
            if path.endswith(".py"):
                py_files.append(path)

        # Resolve entry file
        entry = (req.entry or "").strip()
        entry_file = None
        if entry.endswith(".py") and _os.path.exists(_os.path.join(tmpdir, entry)):
            entry_file = entry
        elif _os.path.exists(_os.path.join(tmpdir, "main.py")):
            entry_file = "main.py"
        elif py_files:
            entry_file = py_files[0]

        if not entry_file:
            return CapstoneRunResponse(
                success=False,
                stderr="No runnable Python entry file found (expected main.py or an entry .py).",
                exit_code=1,
            )

        try:
            result = subprocess.run(
                [_sys.executable, entry_file],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return CapstoneRunResponse(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return CapstoneRunResponse(
                success=False,
                stderr=f"Execution timed out after {timeout_seconds} seconds.",
                exit_code=124,
            )
        except Exception as exc:
            return CapstoneRunResponse(success=False, stderr=str(exc), exit_code=1)
