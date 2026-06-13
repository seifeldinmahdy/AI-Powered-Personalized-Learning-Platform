import api from './api';

export interface Certificate {
    student_name: string;
    course_title: string;
    completion_date: string | null;
    clos_attained: { code: string; text: string }[];
    score: number | null;
    verification_id: string;
}

/**
 * Fetch certificate data for on-page render. The backend refuses (403) unless
 * the course is complete (capstone PASSED) AND the survey has been submitted.
 */
export async function getCertificate(courseId: number): Promise<Certificate> {
    const resp = await api.get<Certificate>(`/courses/courses/${courseId}/certificate/`);
    return resp.data;
}

/** Download the server-generated certificate PDF (same gate as getCertificate). */
export async function downloadCertificatePdf(courseId: number): Promise<void> {
    const resp = await api.get(`/courses/courses/${courseId}/certificate/pdf/`, {
        responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([resp.data], { type: 'application/pdf' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'certificate.pdf';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
}
