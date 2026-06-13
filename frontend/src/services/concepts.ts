import api from './api';

export interface Concept {
    id: number;
    label: string;
    slug: string;
    parent: number | null;
    order: number;
}

export async function getConcepts(courseId: number): Promise<Concept[]> {
    const response = await api.get<Concept[] | { results: Concept[] }>(
        `/courses/courses/${courseId}/concepts/`,
    );
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}
