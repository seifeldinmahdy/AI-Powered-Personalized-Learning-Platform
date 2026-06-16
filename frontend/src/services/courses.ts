import api from './api';

export interface Course {
    id: number;
    title: string;
    description: string;
    difficulty: string;
    status: string;
    tags: string[];
    is_published: boolean;
    price: string;
    total_lessons_count: number;
    avg_rating: string;
    created_at: string;
    syllabus?: string | object | null;
}

interface PaginatedResponse<T> {
    count: number;
    next: string | null;
    previous: string | null;
    results: T[];
}

export async function getCourses(params?: {
    search?: string;
    difficulty?: string;
    ordering?: string;
    page?: number;
}): Promise<PaginatedResponse<Course>> {
    const response = await api.get<PaginatedResponse<Course>>('/courses/courses/', { params });
    return response.data;
}

export async function getCourse(id: number): Promise<Course> {
    const response = await api.get<Course>(`/courses/courses/${id}/`);
    return response.data;
}

/** Alias for getCourse — used by CourseDetail page */
export const getCourseById = getCourse;

export async function updateCourse(id: number, data: Partial<Course>): Promise<Course> {
    const response = await api.patch<Course>(`/courses/courses/${id}/`, data);
    return response.data;
}

export async function submitCourseRating(courseId: number, rating: number): Promise<{ avg_rating: number; your_rating: number }> {
    const response = await api.post(`/courses/courses/${courseId}/rate/`, { rating });
    return response.data;
}

export async function draftCourseDescription(
    courseId: number,
    data?: { current_description?: string; topics?: string[] },
): Promise<{ description: string; source?: string }> {
    const response = await api.post<{ description: string; source?: string }>(
        `/courses/courses/${courseId}/draft_description/`,
        data ?? {},
    );
    return response.data;
}

export interface PathwayVersion {
    student_id: number | string;
    course_id: number | string;
    plan_version: number;
    generated_at: string;
    total_sessions: number;
    total_chunks: number;
}

export async function getPathwayVersions(
    courseId: number,
    studentId?: number,
): Promise<PathwayVersion[]> {
    const response = await api.get<PathwayVersion[] | { results: PathwayVersion[] }>(
        `/courses/courses/${courseId}/pathway/versions/`,
        { params: studentId ? { student_id: studentId } : undefined },
    );
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function regeneratePathway(
    courseId: number,
    studentId: number,
): Promise<unknown> {
    const response = await api.post<unknown>(
        `/courses/courses/${courseId}/pathway/regenerate/`,
        { student_id: studentId },
    );
    return response.data;
}
