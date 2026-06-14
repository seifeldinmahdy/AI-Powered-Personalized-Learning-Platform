/**
 * Resume API (Batch 10b). Drives the "continue where you left off" view entirely
 * from the durable index + current plan — never by scanning artifact content.
 */
import api from './api';

export interface ResumeTimelineEntry {
    kind: 'artifact' | 'problem_set';
    type: 'slides' | 'lab' | 'problem_set';
    status: string;
    // artifact (slides/lab)
    id?: number;
    session_number?: number | null;
    lesson?: number | null;
    // problem set
    ps_uid?: string;
    generation_index?: number;
    superseded?: boolean;
    best_score?: number | null;
}

export interface CourseResume {
    course_id: number;
    enrollment_id: number;
    progress_percentage: number;
    plan_version: number | null;
    total_sessions: number;
    completed: number;
    sessions_left: number;
    current_lesson: number | null;
    current_session_number: number | null;
    timeline: ResumeTimelineEntry[];
}

export async function getCourseResume(courseId: string | number): Promise<CourseResume> {
    const { data } = await api.get<CourseResume>(`/courses/${courseId}/resume/`);
    return data;
}

export interface ProblemSetAttemptRecord {
    id: number;
    question_id: string;
    code: string;
    hints_used: number;
    score: number;
    source: string;
    created_at: string;
}

export interface ProblemSetHistory {
    ps_uid: string;
    lesson: number;
    generation_index: number;
    superseded: boolean;
    best_score: number | null;
    attempts: ProblemSetAttemptRecord[];
}

/** Read-only attempt history + best score for a past problem set (ownership
 *  enforced server-side). */
export async function getProblemSetHistory(psUid: string): Promise<ProblemSetHistory> {
    const { data } = await api.get<ProblemSetHistory>(`/artifacts/problem-sets/${psUid}/history/`);
    return data;
}

/** Fetch a past slides/lab artifact's content by id (ownership enforced). */
export async function getArtifactContent(artifactId: number): Promise<Record<string, unknown>> {
    const { data } = await api.get(`/artifacts/${artifactId}/content/`);
    return data;
}
