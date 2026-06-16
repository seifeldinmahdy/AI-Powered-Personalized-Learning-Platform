import api from './api';

export type CorpusSourceType = 'pdf' | 'doc' | 'url';
export type IndexStatus = 'pending' | 'indexing' | 'indexed' | 'failed';

export interface CorpusSource {
    id: number;
    title: string;
    book_stem: string;
    source_type: CorpusSourceType;
    concept: number | null;
    is_active: boolean;
    index_status: IndexStatus;
    chunk_count: number;
    added_at: string;
}

export interface CourseCorpus {
    id: number;
    course: number;
    corpus_id: string;
    name: string;
    sources: CorpusSource[];
    created_at: string;
    updated_at: string;
}

export interface AvailableBook {
    book_stem: string;
    title: string;
    source_type?: CorpusSourceType;
}

export interface IndexStatusResponse {
    status: IndexStatus;
    chunk_count?: number;
    message?: string;
}

export async function getCourseCorpus(courseId: number): Promise<CourseCorpus | null> {
    try {
        const res = await api.get<CourseCorpus>(`/courses/courses/${courseId}/corpus/`);
        return res.data;
    } catch {
        return null;
    }
}

export async function getAvailableBooks(courseId: number): Promise<AvailableBook[]> {
    const res = await api.get<AvailableBook[] | { results: AvailableBook[] }>(
        `/courses/courses/${courseId}/corpus/available-books/`,
    );
    const data = res.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function uploadBook(courseId: number, file: File): Promise<unknown> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await api.post<unknown>(
        `/courses/courses/${courseId}/corpus/upload/`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return res.data;
}

export async function addCorpusSource(
    courseId: number,
    data: Omit<CorpusSource, 'id' | 'index_status' | 'chunk_count' | 'added_at'>,
): Promise<CorpusSource> {
    const res = await api.post<CorpusSource>(
        `/courses/courses/${courseId}/corpus/sources/`,
        data,
    );
    return res.data;
}

export async function removeCorpusSource(courseId: number, sourceId: number): Promise<void> {
    await api.delete(`/courses/courses/${courseId}/corpus/sources/${sourceId}/`);
}

export async function getIndexStatus(
    courseId: number,
    bookStem: string,
): Promise<IndexStatusResponse> {
    const res = await api.get<IndexStatusResponse>(
        `/courses/courses/${courseId}/corpus/index-status/`,
        { params: { book_stem: bookStem } },
    );
    return res.data;
}
