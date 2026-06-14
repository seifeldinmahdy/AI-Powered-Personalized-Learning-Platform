import api from './api';

export interface AdminStats {
    total_students: number;
    total_courses: number;
    active_courses: number;
    total_enrollments: number;
    completed_lessons: number;
    avg_completion: number;
    recent_enrollments: { student: string; course: string; enrolled_at: string }[];
}

export interface AdminStudent {
    id: number;
    username: string;
    email: string;
    joined: string;
    level: number;
    current_xp: number;
    current_streak: number;
    total_minutes_learned: number;
    enrollments: number;
    achievements: number;
}

export interface AdminCourse {
    id: number;
    title: string;
    description: string;
    difficulty: string;
    status: string;
    tags: string[];
    price: string;
    total_lessons_count: number;
    avg_rating: number;
    created_at: string;
}

export interface ServiceHealth {
    status: 'healthy' | 'degraded' | 'down' | 'unknown';
    error?: string;
    model_loaded?: boolean;
    model_path?: string;
    [key: string]: unknown;
}

export interface AuditLogEntry {
    id: number;
    admin: number | null;
    admin_username: string;
    action: string;
    target_type: string;
    target_id: string;
    snapshot_before: Record<string, unknown> | null;
    snapshot_after: Record<string, unknown> | null;
    ip_address: string | null;
    created_at: string;
}

export interface IntentFeedbackEntry {
    id: number;
    student_input: string;
    session_context: string;
    predicted_intent: string;
    confidence: number | null;
    feedback: string;
    corrected_intent: string | null;
    status: string;
    created_at: string;
}

export interface RetrainingCounter {
    id: number;
    reviews_since_last_train: number;
    threshold: number;
    last_trained_at: string | null;
    updated_at: string;
}

// ---------- Dashboard ----------
export async function getAdminStats(): Promise<AdminStats> {
    const res = await api.get('/courses/admin/stats/');
    return res.data;
}

export async function getAdminStudents(): Promise<AdminStudent[]> {
    const res = await api.get('/users/admin-students/');
    return res.data;
}

export async function getAdminCourses(): Promise<AdminCourse[]> {
    const res = await api.get('/courses/courses/');
    const data = res.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function createCourse(data: Partial<AdminCourse>): Promise<AdminCourse> {
    const res = await api.post('/courses/courses/', data);
    return res.data;
}

export async function updateCourse(id: number, data: Partial<AdminCourse>): Promise<AdminCourse> {
    const res = await api.patch(`/courses/courses/${id}/`, data);
    return res.data;
}

export async function deleteCourse(id: number): Promise<void> {
    await api.delete(`/courses/courses/${id}/`);
}

// ---------- Modules ----------

export interface AdminModule {
    id: number;
    course: number;
    title: string;
    module_order: number;
}

export async function getModulesByCourse(courseId: number): Promise<AdminModule[]> {
    const res = await api.get(`/courses/modules/?course_id=${courseId}`);
    const data = res.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function createModule(data: Omit<AdminModule, 'id'>): Promise<AdminModule> {
    const res = await api.post('/courses/modules/', data);
    return res.data;
}

export async function updateModule(id: number, data: Partial<AdminModule>): Promise<AdminModule> {
    const res = await api.patch(`/courses/modules/${id}/`, data);
    return res.data;
}

export async function deleteModule(id: number): Promise<void> {
    await api.delete(`/courses/modules/${id}/`);
}

// ---------- Lessons ----------

export interface AdminLesson {
    id: number;
    module: number;
    title: string;
    lesson_order: number;
}

export async function getLessonsByModule(moduleId: number): Promise<AdminLesson[]> {
    const res = await api.get(`/courses/lessons/?module_id=${moduleId}`);
    const data = res.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function createLesson(data: Omit<AdminLesson, 'id'>): Promise<AdminLesson> {
    const res = await api.post('/courses/lessons/', data);
    return res.data;
}

export async function updateLesson(id: number, data: Partial<AdminLesson>): Promise<AdminLesson> {
    const res = await api.patch(`/courses/lessons/${id}/`, data);
    return res.data;
}

export async function deleteLesson(id: number): Promise<void> {
    await api.delete(`/courses/lessons/${id}/`);
}

// ---------- Health Monitoring (distributed proxies) ----------

const HEALTH_ENDPOINTS: Record<string, string> = {
    intent: '/admin/health/intent/',
    tutor: '/admin/health/tutor/',
    rag: '/admin/health/rag/',
    slides: '/admin/health/slides/',
    asr: '/admin/health/asr/',
    tts: '/admin/health/tts/',
    fer: '/admin/health/fer/',
    ser: '/admin/health/ser/',
    pathway: '/admin/health/pathway/',
    assessments: '/admin/health/assessments/',
    a2f: '/admin/health/a2f/',
};

export async function getServiceHealth(service: string): Promise<ServiceHealth> {
    const endpoint = HEALTH_ENDPOINTS[service];
    if (!endpoint) return { status: 'unknown', error: 'Unknown service' };
    try {
        const res = await api.get(endpoint);
        return res.data;
    } catch {
        return { status: 'down', error: 'Request failed' };
    }
}

export async function getAllServicesHealth(): Promise<Record<string, ServiceHealth>> {
    const entries = await Promise.all(
        Object.entries(HEALTH_ENDPOINTS).map(async ([name, endpoint]) => {
            try {
                const res = await api.get(endpoint);
                return [name, res.data as ServiceHealth] as const;
            } catch {
                return [name, { status: 'down' as const, error: 'Request failed' }] as const;
            }
        })
    );
    return Object.fromEntries(entries);
}

export function getHealthServiceNames(): string[] {
    return Object.keys(HEALTH_ENDPOINTS);
}

// ---------- Audit Logs ----------

export async function getAuditLogs(params?: {
    action?: string;
    admin_id?: number;
}): Promise<AuditLogEntry[]> {
    const res = await api.get('/audit-logs/', { params });
    const data = res.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

// ---------- Intent Feedback & Retraining ----------

export async function getIntentFeedbackBuffer(): Promise<IntentFeedbackEntry[]> {
    const res = await api.get('/progress/intent-feedback/');
    const data = res.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function relabelFeedback(
    id: number,
    corrected_intent: string
): Promise<IntentFeedbackEntry> {
    const res = await api.patch(`/progress/intent-feedback/${id}/`, { corrected_intent });
    return res.data;
}

export async function getRetrainingCounter(): Promise<RetrainingCounter> {
    const res = await api.get('/progress/retraining-counter/');
    return res.data;
}

export async function updateThreshold(threshold: number): Promise<RetrainingCounter> {
    const res = await api.patch('/progress/retraining-counter/1/', { threshold });
    return res.data;
}
