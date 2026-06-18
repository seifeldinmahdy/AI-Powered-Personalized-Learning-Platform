import api from './api';

const AI_SERVICE = import.meta.env.VITE_AI_SERVICE_URL ?? 'http://localhost:8001';

export interface AssessmentQuestion {
    id: number;
    question: string;
    options: string[];
    correct: number; // index of correct option
    topic: string;
    concept_id?: string | null; // Django Concept.id this question probes
}

export interface IncorrectlyAnsweredItem {
    question: string;
    chosen_option: string;
    correct_option: string;
}

export interface PlacementResult {
    score_pct: number;
    mastery_level: string;
    strengths: string[];
    weaknesses: string[];
    topic_performance: Record<string, number>;
    incorrectly_answered: IncorrectlyAnsweredItem[];
    context_saved: boolean;
}

export interface SubmitPlacementPayload {
    student_id: string;
    course_id: string;
    course_title: string;
    enrollment_id: number;
    composition_mode: string;
    language_proficiency: string;
    answers: Array<{
        question_id: number;
        question: string;
        topic: string;
        concept_id?: string | null;
        chosen_option: string;
        correct_option: string;
        is_correct: boolean;
    }>;
}

/** Generate placement-test questions for a course topic via the AI microservice.
 *  Throws if the service is unavailable or returns no questions — callers are
 *  expected to surface a clear error rather than render an empty quiz. We do not
 *  substitute fabricated questions, which would be wrong for the actual course. */
export async function generateAssessmentQuestions(
    topic: string,
    count = 6,
): Promise<AssessmentQuestion[]> {
    const res = await fetch(`${AI_SERVICE}/assessments/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course_title: topic, num_questions: count }),
    });
    if (!res.ok) throw new Error(`Assessment service returned ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data.questions) || data.questions.length === 0) {
        throw new Error('Assessment service returned no questions');
    }
    // Map correct_answer string to correct index
    return data.questions.map((q: any, idx: number) => {
        const correctIndex = q.options.findIndex(
            (opt: string) => opt === q.correct_answer
        );
        return {
            id: idx + 1,
            question: q.question,
            options: q.options,
            correct: correctIndex >= 0 ? correctIndex : 0,
            topic: q.topic || 'General',
        };
    });
}

/** A category group with its questions, returned by the categorized endpoint. */
export interface CategoryGroup {
    name: string;
    description: string;
    questions: AssessmentQuestion[];
}

/** Fetch placement-test questions for a course from the Django backend.
 *  Questions are pre-authored by the admin. We group them into a single "General" category
 *  for compatibility with the UI. */
export async function fetchPlacementTest(
    courseId: string,
    courseTitle: string,
): Promise<CategoryGroup[]> {
    const res = await api.get(`/courses/courses/${courseId}/placement-test/`);
    const data = res.data;
    
    if (!Array.isArray(data) || data.length === 0) {
        throw new Error('No placement questions found for this course. Contact your instructor.');
    }

    const questions: AssessmentQuestion[] = data.map((q: any) => ({
        id: q.id,
        question: q.question,
        options: q.options || [],
        correct: -1, // Not provided by the backend to prevent cheating
        topic: q.topic || 'General',
        concept_id: q.concept_id ?? null,
    }));

    // Group into a single category since pre-authored questions don't have LLM categories yet,
    // or group by topic if we prefer, but single group matches the generic UI.
    return [{
        name: 'Placement Test',
        description: `Assess your knowledge of ${courseTitle}.`,
        questions,
    }];
}

/** Submit placement answers to backend, which builds and persists the student context. */
export async function submitPlacementResults(
    payload: SubmitPlacementPayload,
): Promise<PlacementResult> {
    const res = await fetch(`${AI_SERVICE}/assessments/submit-placement`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Placement submission failed: ${detail}`);
    }
    return res.json();
}

/** Fetch the persisted student context for a student+course pair. */
export async function getStudentContext(
    studentId: string,
    courseId: string,
): Promise<any> {
    const res = await fetch(`${AI_SERVICE}/student-context/${studentId}/${courseId}`);
    if (!res.ok) return null;
    return res.json();
}

/** Save the placement score back to the enrollment record. */
export async function updatePlacementScore(
    enrollmentId: number,
    score: number,
): Promise<void> {
    await api.patch(`/courses/enrollments/${enrollmentId}/`, { placement_score: score });
}
