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
    timeSpentMinutes?: number,
): Promise<LessonCompletion> {
    const payload: Record<string, unknown> = {};
    if (score !== undefined) payload.score = score;
    if (timeSpentMinutes !== undefined) payload.time_spent_minutes = timeSpentMinutes;
    const response = await api.post<LessonCompletion>(
        `/progress/lesson-completions/${completionId}/complete/`,
        payload,
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

// ---------- Bookmarks ----------

export interface Bookmark {
    id: number;
    user: number;
    lesson: number;
    lesson_title: string;
    course_id: number;
    slide_index: number | null;
    created_at: string;
}

export async function getBookmarks(): Promise<Bookmark[]> {
    const response = await api.get<Bookmark[] | { results: Bookmark[] }>('/progress/bookmarks/');
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function createBookmark(lessonId: number, slideIndex?: number): Promise<Bookmark> {
    const response = await api.post<Bookmark>('/progress/bookmarks/', {
        lesson: lessonId,
        slide_index: slideIndex ?? null,
    });
    return response.data;
}

export async function deleteBookmark(bookmarkId: number): Promise<void> {
    await api.delete(`/progress/bookmarks/${bookmarkId}/`);
}

export interface PracticeCompletionResult {
    xp_awarded: number;
    new_total: number;
    new_level: number;
}

export async function reportPracticeCompletion(
    lessonId: number,
    score: number
): Promise<PracticeCompletionResult> {
    const response = await api.post<PracticeCompletionResult>(
        '/progress/practice-completion/',
        { lesson_id: lessonId, score }
    );
    return response.data;
}
