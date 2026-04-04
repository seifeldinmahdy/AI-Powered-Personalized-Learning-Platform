import api from './api';

// ---------- Types ----------

export interface NewlyEarnedAchievement {
    name: string;
    icon_url: string;
    xp_reward: number;
}

export interface LessonCompletion {
    id: number;
    enrollment: number;
    lesson: number;
    lesson_title: string;
    status: 'Started' | 'In Progress' | 'Completed';
    score: number;
    completed_at: string | null;
    newly_earned_achievements?: NewlyEarnedAchievement[];
}

export interface ActivityLog {
    id: number;
    user: number;
    action_type: string;
    target_course: number | null;
    course_title: string | null;
    created_at: string;
}

// ---------- Lesson Completions ----------

export async function getLessonCompletions(enrollmentId?: number): Promise<LessonCompletion[]> {
    const response = await api.get<LessonCompletion[] | { results: LessonCompletion[] }>(
        '/progress/lesson-completions/',
        { params: enrollmentId ? { enrollment_id: enrollmentId } : undefined },
    );
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function createLessonCompletion(data: {
    enrollment: number;
    lesson: number;
    status?: string;
}): Promise<LessonCompletion> {
    const response = await api.post<LessonCompletion>('/progress/lesson-completions/', data);
    return response.data;
}

export async function markLessonComplete(
    completionId: number,
    score?: number,
): Promise<LessonCompletion> {
    const response = await api.post<LessonCompletion>(
        `/progress/lesson-completions/${completionId}/complete/`,
        score !== undefined ? { score } : {},
    );
    return response.data;
}

export async function updateLessonProgress(
    completionId: number,
    data: Partial<Pick<LessonCompletion, 'status' | 'score'>>,
): Promise<LessonCompletion> {
    const response = await api.patch<LessonCompletion>(
        `/progress/lesson-completions/${completionId}/`,
        data,
    );
    return response.data;
}

// ---------- Activity Logs ----------

export async function getActivityLogs(): Promise<ActivityLog[]> {
    const response = await api.get<ActivityLog[]>('/progress/activity-logs/');
    return response.data;
}
