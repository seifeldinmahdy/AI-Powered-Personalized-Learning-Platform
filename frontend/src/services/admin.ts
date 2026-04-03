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
    instructor_name: string;
}

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
