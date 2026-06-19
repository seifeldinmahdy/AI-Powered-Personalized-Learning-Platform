/**
 * Problem Set API service.
 * Talks to the AI service's /problem-set endpoints THROUGH Django (JWT), which
 * sets the verified student identity server-side — the browser never sends a
 * student_id (Track 1 / Approach A).
 */

import api from './api';

// ── Types ──────────────────────────────────────────────────────

export interface RubricCheck {
    id: string;
    question: string;
    weight: number;
    result?: boolean | null;
    evidence?: string | null;
}

export interface RubricCriterion {
    id: string;
    category: string;
    name: string;
    weight: number;
    checks: RubricCheck[];
}

export interface RubricScore {
    criterion: string;
    category: string;
    earned: number;
    max: number;
    score: number;
    comment: string;
}

export interface ProblemSetQuestion {
    id: string;
    topic: string;
    title: string;
    scenario_framing: string;
    problem_statement: string;
    starter_code: string;
    rubric: RubricCriterion[];
    example_solution: string;
    static_hint: string;
    analogy_explanation: string;
    difficulty: string;
    target_weakness: string | null;
    language: string;
}

export interface EvaluationResult {
    raw_score: number;
    hint_penalty: number;
    final_score: number;
    passed: boolean;
    feedback: string;
    rubric_scores: RubricScore[];
    evaluated_rubric?: RubricCriterion[];
    mistake_tags: string[];
    hint_to_show: string | null;
    example_solution: string;
}

export interface SubmissionData {
    code: string;
    hints_used: number;
    submitted_at: string;
    result: EvaluationResult;
}

export interface ProblemSetData {
    problem_set_id: string;
    student_id: string;
    lesson_id: string;
    course_id: string;
    generated_at: string;
    questions: ProblemSetQuestion[];
    submissions: Record<string, SubmissionData>;
}

export interface GenerateProblemSetOptions {
    sessionId: string;
    studentId: string;
    courseId: string;
    sessionNumber: string | number;
    sessionTitle?: string;
    studentProfileSummary?: string;
    slides?: { title: string; content: string; code?: string }[];
    labCells?: { id: string; cell_type: string; title: string; narrative?: string; code?: string; starter_code?: string; task_prompt?: string }[];
}

export async function generateProblemSet(opts: GenerateProblemSetOptions): Promise<ProblemSetData> {
    const res = await api.post<ProblemSetData>('/ai/problem-set/generate/', {
        session_id: opts.sessionId,
        course_id: opts.courseId,
        lesson_id: String(opts.sessionNumber),
        lesson_title: opts.sessionTitle || '',
        student_profile_summary: opts.studentProfileSummary || '',
        slides: opts.slides || [],
        lab_cells: opts.labCells || [],
    });
    return res.data;
}

export async function getProblemSet(problemSetId: string, _studentId: string = ''): Promise<ProblemSetData> {
    const res = await api.get<ProblemSetData>(`/ai/problem-set/${problemSetId}/`);
    return res.data;
}

/** Student-initiated regeneration (MAX 3 per plan_version, cap enforced
 *  server-side). Throws with the server message on 409 (limit reached). */
export async function regenerateProblemSet(opts: GenerateProblemSetOptions): Promise<ProblemSetData> {
    try {
        const res = await api.post<ProblemSetData>('/ai/problem-set/regenerate/', {
            session_id: opts.sessionId,
            course_id: opts.courseId,
            lesson_id: String(opts.sessionNumber),
            lesson_title: opts.sessionTitle || '',
            student_profile_summary: opts.studentProfileSummary || '',
            slides: opts.slides || [],
            lab_cells: opts.labCells || [],
        });
        return res.data;
    } catch (err: any) {
        if (err?.response?.status === 409) {
            throw new Error(err.response.data?.detail || 'Regeneration limit reached for this lesson.');
        }
        const detail = err?.response?.data?.detail || err?.message || 'unknown error';
        throw new Error(`Problem set regeneration failed: ${detail}`);
    }
}

/** Remaining regenerations for a lesson at a plan version (Django). */
export async function getRegenerationCount(
    courseId: string | number, sessionNumber: string | number, planVersion: number,
): Promise<{ regenerations_used: number; remaining: number; max: number }> {
    const { data } = await api.get('/artifacts/problem-sets/regen-count/', {
        params: { course: courseId, lesson: sessionNumber, plan_version: planVersion },
    });
    return data;
}

/** Student-facing best score for a lesson (derived from attempts; Django). */
export async function getProblemSetBestScore(
    courseId: string | number, sessionNumber: string | number, planVersion?: number,
): Promise<number | null> {
    const params: Record<string, string | number> = { course: courseId, lesson: sessionNumber };
    if (planVersion != null) params.plan_version = planVersion;
    const { data } = await api.get('/artifacts/problem-sets/score/', { params });
    return data.best_score;
}

export async function getStudentProblemSets(
    _studentId: string,
    sessionNumber: string,
): Promise<ProblemSetData[]> {
    const res = await api.get<ProblemSetData[]>(`/ai/problem-set/lesson/${sessionNumber}/`);
    return res.data;
}

export async function submitAnswer(
    problemSetId: string,
    questionId: string,
    _studentId: string,
    code: string,
    language: string,
    hintsUsed: number,
): Promise<EvaluationResult> {
    const res = await api.post<EvaluationResult>('/ai/problem-set/submit/', {
        problem_set_id: problemSetId,
        question_id: questionId,
        code,
        language,
        hints_used: hintsUsed,
    });
    return res.data;
}

export async function getDynamicHint(params: {
    problemSetId: string;
    questionId: string;
    studentId: string;
    sessionNumber: string | number;
    currentCode: string;
    hintNumber: number;
    evaluatedRubric?: any[] | null;
}): Promise<{
    hint_content: string;
    targets_criterion_id: string | null;
    targets_check_id: string | null;
    penalty_applied: number;
    hint_deductions: Record<string, number>;
}> {
    const res = await api.post('/ai/problem-set/hint/', {
        problem_set_id: params.problemSetId,
        question_id: params.questionId,
        lesson_id: String(params.sessionNumber),
        current_code: params.currentCode,
        hint_number: params.hintNumber,
        evaluated_rubric: params.evaluatedRubric ?? null,
    });
    return res.data;
}

export interface NewlyEarnedAchievement {
    name: string;
    icon_url: string;
    xp_reward: number;
}

export async function notifySummaryViewed(params: {
    problemSetId: string;
    studentId: string;
    sessionNumber: string | number;
}): Promise<{
    status: string;
    newly_earned_achievements?: NewlyEarnedAchievement[];
    already_completed?: boolean;
}> {
    const res = await api.post('/ai/problem-set/summary-viewed/', {
        problem_set_id: params.problemSetId,
        lesson_id: String(params.sessionNumber),
    });
    return res.data;
}
