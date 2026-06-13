import api from './api';

export interface SurveyQuestion {
    id: number;
    kind: 'likert' | 'text' | 'single' | 'multi';
    prompt: string;
    options: string[];
    order: number;
    clo: number | null;
}

export interface SurveyStatus {
    pending: boolean;
    template_id: number | null;
}

export interface SurveySummary {
    recurring_themes: Array<{ theme: string; count: number }>;
    sentiment: string;
    top_praise: string[];
    top_complaints: string[];
    per_clo_perception: Record<string, string>;
    response_count: number;
    generated_at: string;
}

export async function getSurveyStatus(enrollmentId: number): Promise<SurveyStatus> {
    const response = await api.get<SurveyStatus>('/feedback/surveys/status/', {
        params: { enrollment: enrollmentId },
    });
    return response.data;
}

export async function getSurveyQuestions(courseId: number): Promise<SurveyQuestion[]> {
    const response = await api.get<SurveyQuestion[]>(`/feedback/surveys/${courseId}/questions/`);
    return Array.isArray(response.data) ? response.data : [];
}

export async function submitSurveyResponse(data: {
    enrollment_id: number;
    template_id: number;
    answers: Record<number, string | number | string[]>;
}): Promise<void> {
    await api.post('/feedback/surveys/respond/', data);
}

export async function getSurveySummary(courseId: number): Promise<SurveySummary> {
    const response = await api.get<SurveySummary>(`/feedback/surveys/${courseId}/summary/`);
    return response.data;
}

export async function refreshSurveySummary(courseId: number): Promise<SurveySummary> {
    const response = await api.post<SurveySummary>(`/feedback/surveys/${courseId}/refresh/`, {});
    return response.data;
}
