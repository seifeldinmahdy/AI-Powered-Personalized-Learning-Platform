import api from './api';

export interface CLO {
    id: number;
    code: string;
    text: string;
    bloom_level: string;
    concepts: number[];
    order: number;
}

export interface CLODraft {
    code: string;
    text: string;
    bloom_level: string;
    concept_ids: string[];
    order: number;
}

export interface CLOAttainment {
    id: number;
    code: string;
    text: string;
    attainment: number | null;
    evidence_count: number;
}

export async function getCLOs(courseId: number): Promise<CLO[]> {
    const response = await api.get<CLO[] | { results: CLO[] }>(
        `/courses/courses/${courseId}/clos/`,
    );
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function suggestCLOs(courseId: number): Promise<{ drafts: CLODraft[] }> {
    const response = await api.post<{ drafts: CLODraft[] }>(
        `/courses/courses/${courseId}/clos/suggest/`,
        {},
    );
    return response.data;
}

export async function createCLO(courseId: number, data: Omit<CLO, 'id'>): Promise<CLO> {
    const response = await api.post<CLO>(`/courses/courses/${courseId}/clos/`, data);
    return response.data;
}

export async function updateCLO(courseId: number, id: number, data: Partial<CLO>): Promise<CLO> {
    const response = await api.patch<CLO>(`/courses/courses/${courseId}/clos/${id}/`, data);
    return response.data;
}

export async function deleteCLO(courseId: number, id: number): Promise<void> {
    await api.delete(`/courses/courses/${courseId}/clos/${id}/`);
}

export async function getCLOAttainment(courseId: number, studentId?: number): Promise<CLOAttainment[]> {
    const params = studentId ? { student: studentId } : {};
    const response = await api.get<CLOAttainment[]>(
        `/courses/courses/${courseId}/clos/attainment/`,
        { params },
    );
    return Array.isArray(response.data) ? response.data : [];
}
