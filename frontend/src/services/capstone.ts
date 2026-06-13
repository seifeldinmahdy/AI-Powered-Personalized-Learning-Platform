import api from './api';

// ---- Shared types ----

export interface CapstoneRubricItem {
    id: number;
    text: string;
    category: 'core' | 'stretch';
    clo: number | null;
    concept: number | null;
    weight: number;
    min_team_size: number;
    order: number;
}

export interface Capstone {
    id: number;
    course: number;
    title: string;
    spec_mode: 'admin_defined' | 'student_proposed';
    team_mode: 'solo' | 'team';
    team_cap: number;
    deadline: string | null;
    status: 'draft' | 'active' | 'completed' | 'archived';
    brief_text: string;
    github_template_repo: string;
    run_command: string;
    rubric_items: CapstoneRubricItem[];
    created_at: string;
    updated_at: string;
}

export interface CapstoneProposal {
    id: number;
    capstone: number;
    student: number;
    student_username: string;
    title: string;
    description: string;
    planned_features: string[];
    approval_status: 'pending' | 'approved' | 'rejected';
    admin_feedback: string;
    confidence_score: number | null;
    submitted_at: string;
    reviewed_at: string | null;
}

export interface CapstoneSubmission {
    id: number;
    capstone: number;
    enrollment: number;
    proposal: number | null;
    repo_url: string;
    latest_commit_sha: string;
    github_username: string;
    results: Record<string, { passed: boolean; weight: number; evidence: string }>;
    score: number | null;
    verdict: 'pending' | 'pass' | 'fail';
    feedback: string;
    status: 'pending' | 'evaluating' | 'completed' | 'failed';
    submitted_at: string;
    evaluated_at: string | null;
}

export interface RubricDraft {
    text: string;
    category: string;
    weight: number;
    min_team_size: number;
    order: number;
    rationale: string;
}

// ---- Capstone CRUD ----

export async function getCapstoneForCourse(courseId: number): Promise<Capstone> {
    const resp = await api.get<Capstone>(`/capstone/course/${courseId}/`);
    return resp.data;
}

export async function listCapstones(): Promise<Capstone[]> {
    const resp = await api.get<Capstone[] | { results: Capstone[] }>('/capstone/capstones/');
    const data = resp.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function createCapstone(data: Partial<Capstone>): Promise<Capstone> {
    const resp = await api.post<Capstone>('/capstone/capstones/', data);
    return resp.data;
}

export async function updateCapstone(id: number, data: Partial<Capstone>): Promise<Capstone> {
    const resp = await api.patch<Capstone>(`/capstone/capstones/${id}/`, data);
    return resp.data;
}

// ---- Rubric item management ----

export async function createRubricItem(
    capstoneId: number,
    data: Omit<CapstoneRubricItem, 'id'>,
): Promise<CapstoneRubricItem> {
    const resp = await api.post<CapstoneRubricItem>(
        `/capstone/capstones/${capstoneId}/rubric-items/`,
        data,
    );
    return resp.data;
}

export async function updateRubricItem(
    capstoneId: number,
    itemId: number,
    data: Partial<CapstoneRubricItem>,
): Promise<CapstoneRubricItem> {
    const resp = await api.patch<CapstoneRubricItem>(
        `/capstone/capstones/${capstoneId}/rubric-items/${itemId}/`,
        data,
    );
    return resp.data;
}

export async function deleteRubricItem(capstoneId: number, itemId: number): Promise<void> {
    await api.delete(`/capstone/capstones/${capstoneId}/rubric-items/${itemId}/`);
}

// ---- AI rubric actions ----

export async function draftRubric(capstoneId: number): Promise<{ rubric_items: RubricDraft[] }> {
    const resp = await api.post<{ rubric_items: RubricDraft[] }>(
        `/capstone/capstones/${capstoneId}/draft-rubric/`,
        {},
    );
    return resp.data;
}

export async function extractSpec(
    capstoneId: number,
    specText: string,
): Promise<{ rubric_items: RubricDraft[] }> {
    const resp = await api.post<{ rubric_items: RubricDraft[] }>(
        `/capstone/capstones/${capstoneId}/extract-spec/`,
        { spec_text: specText },
    );
    return resp.data;
}

// ---- Proposals ----

export async function listProposals(capstoneId?: number): Promise<CapstoneProposal[]> {
    const resp = await api.get<CapstoneProposal[] | { results: CapstoneProposal[] }>(
        '/capstone/proposals/',
        { params: capstoneId ? { capstone: capstoneId } : undefined },
    );
    const data = resp.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function submitProposal(
    data: Pick<CapstoneProposal, 'capstone' | 'title' | 'description' | 'planned_features'>,
): Promise<CapstoneProposal> {
    const resp = await api.post<CapstoneProposal>('/capstone/proposals/', data);
    return resp.data;
}

export async function approveProposal(
    proposalId: number,
    approvalStatus: 'approved' | 'rejected',
    adminFeedback?: string,
): Promise<CapstoneProposal> {
    const resp = await api.post<CapstoneProposal>(
        `/capstone/proposals/${proposalId}/approve/`,
        { approval_status: approvalStatus, admin_feedback: adminFeedback ?? '' },
    );
    return resp.data;
}

export async function mapProposalRubric(proposalId: number): Promise<{
    confidence_score: number;
    coverage: Array<{ criterion_id: number; covered: boolean; reason: string }>;
    suggestions: string[];
}> {
    const resp = await api.post(`/capstone/proposals/${proposalId}/map-rubric/`, {});
    return resp.data;
}

// ---- Submissions ----

export async function getMySubmission(capstoneId: number): Promise<CapstoneSubmission | null> {
    try {
        const resp = await api.get<CapstoneSubmission>(
            `/capstone/capstones/${capstoneId}/my-submission/`,
        );
        return resp.data;
    } catch {
        return null;
    }
}

export async function submitArchive(
    capstoneId: number,
    codeBundle: string,
    proposalId?: number,
): Promise<CapstoneSubmission> {
    const resp = await api.post<CapstoneSubmission>(
        `/capstone/capstones/${capstoneId}/submit/`,
        { code_bundle: codeBundle, proposal_id: proposalId },
    );
    return resp.data;
}

export async function submitFromRepo(
    capstoneId: number,
    repoUrl: string,
    commitSha: string,
    githubUsername: string,
): Promise<CapstoneSubmission> {
    const resp = await api.post<CapstoneSubmission>(
        `/capstone/capstones/${capstoneId}/submit-from-repo/`,
        { repo_url: repoUrl, commit_sha: commitSha, github_username: githubUsername },
    );
    return resp.data;
}

/**
 * Final submission from the in-platform IDE. The backend verifies CI is green
 * on the work branch HEAD, fast-forwards main to that commit, and grades it in
 * the background. Returns 409 (with a verdict) if CI hasn't passed yet.
 */
export async function submitForGrading(
    capstoneId: number,
): Promise<{ status: string; commit_sha: string; submission: CapstoneSubmission }> {
    const resp = await api.post(
        `/capstone/capstones/${capstoneId}/submit-for-grading/`,
        {},
    );
    return resp.data;
}

export async function provisionRepo(
    capstoneId: number,
    githubUsername: string,
): Promise<{ repo_url: string; repo_name: string }> {
    const resp = await api.post<{ repo_url: string; repo_name: string }>(
        `/capstone/capstones/${capstoneId}/provision-repo/`,
        { github_username: githubUsername },
    );
    return resp.data;
}

export async function listSubmissions(capstoneId?: number): Promise<CapstoneSubmission[]> {
    const resp = await api.get<CapstoneSubmission[] | { results: CapstoneSubmission[] }>(
        '/capstone/submissions/',
        { params: capstoneId ? { capstone: capstoneId } : undefined },
    );
    const data = resp.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

// ===========================================================================
// Batch 3 — IDE workspace, commits, CI verdict, run, AI assist, teams
// ===========================================================================

export interface TreeNode {
    path: string;
    type: 'blob' | 'tree';
    size: number | null;
    sha: string;
}

export interface FileContent {
    path: string;
    content: string;
    sha: string;
    size: number;
}

export interface ChangedFile {
    path: string;
    content: string;
    deleted?: boolean;
}

export interface CommitVerdict {
    status: 'queued' | 'in_progress' | 'completed';
    conclusion: 'success' | 'failure' | 'neutral' | null;
    reason: string;
}

export interface AssistQuota {
    id: number;
    capstone: number;
    student: number | null;
    team: number | null;
    period: string;
    used: number;
    limit: number;
    remaining: number;
    period_start: string;
}

export interface TeammateRec {
    student_id: number;
    username: string;
    score: number;
    why: string;
}

export interface Team {
    id: number;
    capstone: number;
    name: string;
    members: number[];
    member_usernames: string[];
    status: string;
    created_at: string;
}

// ---- Part A: read ----

export async function getRepoTree(capstoneId: number): Promise<{ branch: string; tree: TreeNode[] }> {
    const resp = await api.get<{ branch: string; tree: TreeNode[] }>(
        `/capstone/capstones/${capstoneId}/tree/`,
    );
    return resp.data;
}

export async function getRepoFile(capstoneId: number, path: string): Promise<FileContent> {
    const resp = await api.get<FileContent>(`/capstone/capstones/${capstoneId}/file/`, {
        params: { path },
    });
    return resp.data;
}

// ---- Part B: commit ----

export async function commitFiles(
    capstoneId: number,
    changedFiles: ChangedFile[],
    message: string,
): Promise<{ commit_sha: string; branch: string }> {
    const resp = await api.post<{ commit_sha: string; branch: string }>(
        `/capstone/capstones/${capstoneId}/commit/`,
        { changed_files: changedFiles, message },
    );
    return resp.data;
}

// ---- Part C: CI verdict ----

export async function getCommitStatus(sha: string, capstoneId: number): Promise<CommitVerdict> {
    const resp = await api.get<CommitVerdict>(`/capstone/commit-status/${sha}/`, {
        params: { capstone: capstoneId },
    });
    return resp.data;
}

// ---- Part D: run ----

export async function runFiles(
    capstoneId: number,
    files: { path: string; content: string }[],
    entry?: string,
): Promise<{ success: boolean; stdout: string; stderr: string; exit_code: number }> {
    const resp = await api.post(`/capstone/capstones/${capstoneId}/run/`, { files, entry });
    return resp.data;
}

// ---- Part E: AI assist ----

export async function getAssistQuota(capstoneId: number): Promise<AssistQuota> {
    const resp = await api.get<AssistQuota>(`/capstone/capstones/${capstoneId}/assist-quota/`);
    return resp.data;
}

export async function askAssist(
    capstoneId: number,
    question: string,
    codeSnippet?: string,
    conceptId?: number,
): Promise<{ answer: string; remaining: number }> {
    const resp = await api.post<{ answer: string; remaining: number }>(
        `/capstone/capstones/${capstoneId}/assist/`,
        { question, code_snippet: codeSnippet ?? '', concept_id: conceptId },
    );
    return resp.data;
}

// ---- Part F: teams + matchmaking ----

export async function joinQueue(capstoneId: number): Promise<unknown> {
    const resp = await api.post(`/capstone/capstones/${capstoneId}/queue/join/`, {});
    return resp.data;
}

export async function leaveQueue(capstoneId: number): Promise<unknown> {
    const resp = await api.post(`/capstone/capstones/${capstoneId}/queue/leave/`, {});
    return resp.data;
}

export async function getRecommendations(capstoneId: number): Promise<TeammateRec[]> {
    const resp = await api.get<{ recommendations: TeammateRec[] }>(
        `/capstone/capstones/${capstoneId}/recommendations/`,
    );
    return resp.data.recommendations ?? [];
}

export async function getMyTeam(capstoneId: number): Promise<Team | null> {
    const resp = await api.get<{ team: Team | null } | Team>(
        `/capstone/capstones/${capstoneId}/my-team/`,
    );
    const data = resp.data as { team?: Team | null };
    if ('team' in data) return data.team ?? null;
    return resp.data as Team;
}

export async function processMatchmaking(
    capstoneId: number,
): Promise<{ teams_formed: number; teams: Team[] }> {
    const resp = await api.post<{ teams_formed: number; teams: Team[] }>(
        `/capstone/capstones/${capstoneId}/process-queue/`,
        {},
    );
    return resp.data;
}

// ---- Team role advisor (advisory suggested division of labor) ----

export interface RoleArea {
    area: string;
    rubric_refs: string[];
    lead: string;
    support: string[];
    rationale: string;
}

export interface MemberGrowth {
    member: string;
    grow_on: string;
    why: string;
}

export interface RoleAdvice {
    areas: RoleArea[];
    per_member_growth: MemberGrowth[];
    team_note: string;
    limited_data?: boolean;
}

export interface RoleAdviceResponse {
    role_advice: RoleAdvice | null;
    generated_at: string | null;
    member_count?: number;
}

export async function getRoleAdvice(teamId: number): Promise<RoleAdviceResponse> {
    const resp = await api.get<RoleAdviceResponse>(`/capstone/team/${teamId}/role-advice/`);
    return resp.data;
}

export async function refreshRoleAdvice(teamId: number): Promise<RoleAdviceResponse> {
    const resp = await api.post<RoleAdviceResponse>(`/capstone/team/${teamId}/role-advice/refresh/`, {});
    return resp.data;
}
