/**
 * Problem Set API service.
 * Talks directly to the AI service's /problem-set endpoints.
 */

import api from './api';

const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';

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
    lessonId: string;
    lessonTitle?: string;
    studentProfileSummary?: string;
    slides?: { title: string; content: string; code?: string }[];
    labCells?: { id: string; cell_type: string; title: string; narrative?: string; code?: string; starter_code?: string; task_prompt?: string }[];
}

export async function generateProblemSet(opts: GenerateProblemSetOptions): Promise<ProblemSetData> {
    const res = await fetch(`${AI_URL}/problem-set/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: opts.sessionId,
            student_id: opts.studentId,
            course_id: opts.courseId,
            lesson_id: opts.lessonId,
            lesson_title: opts.lessonTitle || '',
            student_profile_summary: opts.studentProfileSummary || '',
            slides: opts.slides || [],
            lab_cells: opts.labCells || [],
        }),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Problem set generation failed: ${detail}`);
    }
    return res.json();
}

export async function getProblemSet(problemSetId: string, studentId: string = ''): Promise<ProblemSetData> {
    const params = studentId ? `?student_id=${studentId}` : '';
    const res = await fetch(`${AI_URL}/problem-set/${problemSetId}${params}`);
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Failed to load problem set: ${detail}`);
    }
    return res.json();
}

/** Student-initiated regeneration (MAX 3 per plan_version, cap enforced
 *  server-side). Throws with the server message on 409 (limit reached). */
export async function regenerateProblemSet(opts: GenerateProblemSetOptions): Promise<ProblemSetData> {
    const res = await fetch(`${AI_URL}/problem-set/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: opts.sessionId,
            student_id: opts.studentId,
            course_id: opts.courseId,
            lesson_id: opts.lessonId,
            lesson_title: opts.lessonTitle || '',
            student_profile_summary: opts.studentProfileSummary || '',
            slides: opts.slides || [],
            lab_cells: opts.labCells || [],
        }),
    });
    if (res.status === 409) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'Regeneration limit reached for this lesson.');
    }
    if (!res.ok) {
        throw new Error(`Problem set regeneration failed: ${await res.text()}`);
    }
    return res.json();
}

/** Remaining regenerations for a lesson at a plan version (Django). */
export async function getRegenerationCount(
    courseId: string | number, lessonId: string | number, planVersion: number,
): Promise<{ regenerations_used: number; remaining: number; max: number }> {
    const { data } = await api.get('/artifacts/problem-sets/regen-count/', {
        params: { course: courseId, lesson: lessonId, plan_version: planVersion },
    });
    return data;
}

/** Student-facing best score for a lesson (derived from attempts; Django). */
export async function getProblemSetBestScore(
    courseId: string | number, lessonId: string | number, planVersion?: number,
): Promise<number | null> {
    const params: Record<string, string | number> = { course: courseId, lesson: lessonId };
    if (planVersion != null) params.plan_version = planVersion;
    const { data } = await api.get('/artifacts/problem-sets/score/', { params });
    return data.best_score;
}

export async function getStudentProblemSets(
    studentId: string,
    lessonId: string,
): Promise<ProblemSetData[]> {
    const res = await fetch(`${AI_URL}/problem-set/student/${studentId}/lesson/${lessonId}`);
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Failed to load problem sets: ${detail}`);
    }
    return res.json();
}

export async function submitAnswer(
    problemSetId: string,
    questionId: string,
    studentId: string,
    code: string,
    language: string,
    hintsUsed: number,
): Promise<EvaluationResult> {
    const res = await fetch(`${AI_URL}/problem-set/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            problem_set_id: problemSetId,
            question_id: questionId,
            student_id: studentId,
            code,
            language,
            hints_used: hintsUsed,
        }),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Submission failed: ${detail}`);
    }
    return res.json();
}

export async function getDynamicHint(params: {
    problemSetId: string;
    questionId: string;
    studentId: string;
    lessonId: string;
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
    const res = await fetch(`${AI_URL}/problem-set/hint`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            problem_set_id: params.problemSetId,
            question_id: params.questionId,
            student_id: params.studentId,
            lesson_id: params.lessonId,
            current_code: params.currentCode,
            hint_number: params.hintNumber,
            evaluated_rubric: params.evaluatedRubric ?? null,
        }),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Hint generation failed: ${detail}`);
    }
    return res.json();
}

export interface NewlyEarnedAchievement {
    name: string;
    icon_url: string;
    xp_reward: number;
}

export async function notifySummaryViewed(params: {
    problemSetId: string;
    studentId: string;
    lessonId: string;
}): Promise<{
    status: string;
    newly_earned_achievements?: NewlyEarnedAchievement[];
    already_completed?: boolean;
}> {
    const res = await fetch(`${AI_URL}/problem-set/summary-viewed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            problem_set_id: params.problemSetId,
            student_id: params.studentId,
            lesson_id: params.lessonId,
        }),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Summary viewed notification failed: ${detail}`);
    }
    return res.json();
}
