from fastapi import APIRouter

from schemas.capstone import (
    DraftRubricRequest,
    DraftRubricResponse,
    ExtractSpecRequest,
    ExtractSpecResponse,
    MapProposalRequest,
    MapProposalResponse,
    CapstoneEvalRequest,
    CapstoneEvalResult,
    CapstoneAssistRequest,
    CapstoneAssistResponse,
    CapstoneRunRequest,
    CapstoneRunResponse,
    SuggestLanguageRequest,
    SuggestLanguageResponse,
    TeamRolesRequest,
)
from services.capstone_rubric_service import (
    draft_core_criteria,
    extract_criteria_from_spec,
    map_core_to_proposal,
    evaluate_capstone_rubric,
    assist_student,
    run_capstone_files,
    suggest_language,
    suggest_team_roles,
)

router = APIRouter(prefix="/capstone", tags=["capstone"])


@router.post("/draft-rubric", response_model=DraftRubricResponse)
async def draft_rubric(request: DraftRubricRequest) -> DraftRubricResponse:
    return await draft_core_criteria(request)


@router.post("/extract-spec", response_model=ExtractSpecResponse)
async def extract_spec(request: ExtractSpecRequest) -> ExtractSpecResponse:
    return await extract_criteria_from_spec(request)


@router.post("/map-proposal", response_model=MapProposalResponse)
async def map_proposal(request: MapProposalRequest) -> MapProposalResponse:
    return await map_core_to_proposal(request)


@router.post("/evaluate", response_model=CapstoneEvalResult)
async def evaluate(request: CapstoneEvalRequest) -> CapstoneEvalResult:
    return await evaluate_capstone_rubric(request)


@router.post("/assist", response_model=CapstoneAssistResponse)
async def assist(request: CapstoneAssistRequest) -> CapstoneAssistResponse:
    return await assist_student(request)


@router.post("/run", response_model=CapstoneRunResponse)
async def run(request: CapstoneRunRequest) -> CapstoneRunResponse:
    import asyncio
    return await asyncio.to_thread(run_capstone_files, request)


@router.post("/suggest-language", response_model=SuggestLanguageResponse)
async def suggest_language_endpoint(request: SuggestLanguageRequest) -> SuggestLanguageResponse:
    return await suggest_language(request)


@router.post("/team-roles")
async def team_roles(request: TeamRolesRequest) -> dict:
    """Advisory suggested division of labor (lead/support). Never feeds scoring."""
    import asyncio
    return await asyncio.to_thread(suggest_team_roles, request)
