import api from './api';

export interface Course {
    id: number;
    title: string;
    description: string;
    instructor: number | null;
    instructor_name: string | null;
    difficulty: string;
    status: string;
    tags: string[];
    is_published: boolean;
    price: string;
    total_lessons_count: number;
    avg_rating: string;
    created_at: string;
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
