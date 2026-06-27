from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RubricCheckDraft(BaseModel):
    text: str                       # one atomic binary (yes/no) sub-check


class CapstoneRubricDraft(BaseModel):
    text: str
    # Hierarchical decomposition: each criterion breaks into 2-4 atomic binary
    # checks the judge can answer from the code. A criterion passes iff all pass.
    checks: list[RubricCheckDraft] = Field(default_factory=list)
    category: str = "core"          # core | stretch
    weight: int = 1
    min_team_size: int = 1
    order: int = 0
    rationale: str = ""             # shown in AIDraftReviewTable, not persisted


class DraftRubricRequest(BaseModel):
    capstone_title: str
    brief: str
    spec_mode: str = "admin_defined"
    team_mode: str = "solo"


class DraftRubricResponse(BaseModel):
    rubric_items: list[CapstoneRubricDraft]


class ExtractSpecRequest(BaseModel):
    capstone_title: str
    spec_text: str
    team_mode: str = "solo"


class ExtractSpecResponse(BaseModel):
    rubric_items: list[CapstoneRubricDraft]


class MapProposalRequest(BaseModel):
    capstone_title: str
    brief: str
    core_criteria: list[dict]       # [{id, text}]
    proposal_title: str
    proposal_description: str
    planned_features: list[str] = Field(default_factory=list)


class MapProposalResponse(BaseModel):
    confidence_score: float         # 0.0–1.0; never used as a grade
    coverage: list[dict]            # [{criterion_id, covered: bool, reason}]
    suggestions: list[str]


class RubricCheckForEval(BaseModel):
    id: str             # stable check id within its criterion
    text: str


class RubricItemForEval(BaseModel):
    id: int
    text: str
    checks: list[RubricCheckForEval] = Field(default_factory=list)
    weight: int = 1
    category: str = "core"


class CapstoneEvalRequest(BaseModel):
    capstone_title: str
    brief: str
    rubric_items: list[RubricItemForEval]
    code_bundle: str
    proposal_text: str = ""


class RubricCheckResult(BaseModel):
    passed: bool        # binary — LLM judges yes/no only
    evidence: str       # short quote or reason from code


class RubricItemResult(BaseModel):
    passed: bool        # derived: true iff every check passed (or the coarse yes/no)
    evidence: str       # short quote or reason from code
    # Per-check results, keyed by check id. Empty for legacy (no-checks) criteria.
    checks: dict[str, RubricCheckResult] = Field(default_factory=dict)


class CapstoneEvalResult(BaseModel):
    results: dict[str, RubricItemResult]    # keyed by str(rubric_item_id)
    feedback: str                           # overall qualitative feedback; no numeric score


# ---- Batch 3: scoped AI assist ----

class CapstoneAssistRequest(BaseModel):
    capstone_title: str
    brief: str = ""
    rubric_items: list[str] = Field(default_factory=list)
    question: str
    code_snippet: str = ""


class CapstoneAssistResponse(BaseModel):
    answer: str                              # Socratic; code blocks capped to a few lines


# ---- Batch 3: run uncommitted files in the sandbox ----

class CapstoneRunFile(BaseModel):
    path: str
    content: str


class CapstoneRunRequest(BaseModel):
    files: list[CapstoneRunFile]
    entry: str = ""                          # student hint: entry FILE (never a shell command)
    run_command: str = ""                    # admin-configured shell command (any language)
    language: str = ""                       # capstone language → default entry + interpreter


class CapstoneRunResponse(BaseModel):
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


# ---- Language inference (admin authoring; suggestion only, human-reviewed) ----

class SuggestLanguageRequest(BaseModel):
    course_title: str
    course_description: str = ""
    concepts: list[str] = Field(default_factory=list)


class SuggestLanguageResponse(BaseModel):
    language: str                            # canonical token (python, javascript, …)
    confidence: float = 0.5                  # 0–1; advisory, never a grade
    rationale: str = ""


# ---- Team role advisor (advisory only — never feeds scoring/verdict) ----

class TeamRoleRubricItem(BaseModel):
    text: str
    category: str = "core"
    concept_id: Optional[str] = None


class TeamRoleMember(BaseModel):
    handle: str
    # {concept_id: {"label": str, "score": float|None, "evidence": int}} restricted
    # to this course's concepts. Empty/low-evidence triggers graceful degradation.
    mastery: dict = Field(default_factory=dict)


class TeamRolesRequest(BaseModel):
    capstone_title: str = ""
    brief: str = ""
    rubric_items: list[TeamRoleRubricItem] = Field(default_factory=list)
    members: list[TeamRoleMember] = Field(default_factory=list)
