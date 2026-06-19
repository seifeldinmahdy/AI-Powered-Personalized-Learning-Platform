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

/** Generate placement-test questions grouped by LLM-derived categories.
 *  Falls back to flat generation if the categorized endpoint is unavailable or
 *  returns no questions. Throws if no real questions can be produced at all —
 *  the caller surfaces an error+retry rather than rendering a blank quiz. */
export async function generateCategorizedQuestions(
    courseTitle: string,
    courseId: string,
    totalQuestions = 12,
): Promise<CategoryGroup[]> {
    try {
        const res = await fetch(`${AI_SERVICE}/assessments/generate-categorized`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                course_title: courseTitle,
                course_id: courseId,
                total_questions: totalQuestions,
            }),
        });
        if (res.ok) {
            const data = await res.json();
            if (Array.isArray(data.categories)) {
                let globalId = 1;
                const mapped: CategoryGroup[] = data.categories.map((cat: any) => ({
                    name: cat.name || 'General',
                    description: cat.description || '',
                    questions: (cat.questions || []).map((q: any) => {
                        const correctIndex = q.options?.findIndex(
                            (opt: string) => opt === q.correct_answer
                        ) ?? 0;
                        return {
                            id: globalId++,
                            question: q.question,
                            options: q.options || [],
                            correct: correctIndex >= 0 ? correctIndex : 0,
                            topic: q.topic || cat.name || 'General',
                            concept_id: q.concept_id ?? null,
                    };
                    }),
                })).filter((cat: CategoryGroup) => cat.questions.length > 0);

                const total = mapped.reduce((n, c) => n + c.questions.length, 0);
                if (total > 0) return mapped;
                console.warn('Categorized endpoint returned 0 questions — falling back to flat generation.');
            }
        } else {
            console.warn(`Categorized endpoint returned ${res.status} — falling back to flat generation.`);
        }
    } catch (e) {
        console.warn('Categorized generation failed — falling back to flat generation:', e);
    }

    // Fallback: flat generation wrapped in a single category. This throws if the
    // service is unavailable or returns nothing, which propagates to the caller.
    const flat = await generateAssessmentQuestions(courseTitle, totalQuestions);
    return [{ name: 'General', description: `General knowledge of ${courseTitle}.`, questions: flat }];
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

/** Fetch the persisted student context for the authenticated student + course.
 *
 * Goes through Django (JWT) which sets the verified student identity server-side
 * — the browser never sends a student_id (Track 1 / Approach A). */
export async function getStudentContext(courseId: string): Promise<any> {
    try {
        const res = await api.get(`/ai/student-context/${courseId}/`);
        return res.data;
    } catch {
        return null;
    }
}

/** Save the placement score back to the enrollment record. */
export async function updatePlacementScore(
    enrollmentId: number,
    score: number,
): Promise<void> {
    await api.patch(`/courses/enrollments/${enrollmentId}/`, { placement_score: score });
}
