import api from './api';

export interface Concept {
    id: number;
    label: string;
    slug: string;
    parent: number | null;
    order: number;
    source?: 'manual' | 'auto';
}

export async function getConcepts(courseId: number): Promise<Concept[]> {
    const response = await api.get<Concept[] | { results: Concept[] }>(
        `/courses/courses/${courseId}/concepts/`,
    );
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function createConcept(courseId: number, label: string): Promise<Concept> {
    const response = await api.post<Concept>(`/courses/courses/${courseId}/concepts/`, {
        label,
        order: 99, // default to end
    });
    return response.data;
}

export interface MergeConceptsResult {
    survivor_id: number;
    merged: number[];
    retagged: number | null;
}

/** Fold one or more duplicate concepts into a survivor: CLO links + topic
 *  selections + chunk tags all move to the survivor, the others are deleted. */
export async function mergeConcepts(
    courseId: number,
    survivorId: number,
    mergeIds: number[],
): Promise<MergeConceptsResult> {
    const response = await api.post<MergeConceptsResult>(
        `/courses/courses/${courseId}/concepts/merge/`,
        { survivor_id: survivorId, merge_ids: mergeIds },
    );
    return response.data;
}

export interface ConceptTopic {
    topic: string;
    chunks: number;
}

export interface ConceptTopicsResponse {
    topics: ConceptTopic[];
    total_chunks: number;
}

/** The distinct chunk topics grouped under a concept (e.g. OOP → classes,
 *  encapsulation, …), with chunk counts. Used to refine which topics a CLO uses. */
export async function getConceptTopics(
    courseId: number,
    conceptId: number,
): Promise<ConceptTopicsResponse> {
    const response = await api.get<ConceptTopicsResponse>(
        `/courses/courses/${courseId}/concepts/${conceptId}/topics/`,
    );
    return response.data;
}
