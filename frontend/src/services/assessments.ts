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
    // student_id is no longer sent — Django sets the verified identity (Track 1).
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
    // Through Django (JWT) — identity is set server-side from the authenticated user.
    const res = await api.post<PlacementResult>('/ai/assessments/submit-placement', payload);
    return res.data;
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

// ─────────────────────────────────────────────────────────────────────────────
// IN-SESSION MCQ KNOWLEDGE CHECKPOINTS
//
// These go through Django's authenticated /ai/* proxy (NOT the AI service
// directly): Django injects the verified X-Student-ID, so the browser never
// chooses an identity. Generation runs the local QG/DG models per question and
// can take a while — callers should show a loading state.
// ─────────────────────────────────────────────────────────────────────────────

/** One answer option, mirroring mcq_service MCQOption. */
export interface MCQOptionData {
    text: string;
    is_correct: boolean;
}

/** A full generated MCQ, mirroring mcq_service MCQQuestion. The whole object is
 *  sent back on submit so the server can score it (it carries is_correct). */
export interface MCQQuestionData {
    question: string;
    options: MCQOptionData[];
    correct_answer: string;
    explanation: string;
    question_type: string;
    topic: string;
    concept_id?: string;
    mastery_used: string;
    score_category_used: string;
    distractor_scores?: number[] | null;
    generation_mode: string;
}

export interface AssessmentResponseData {
    questions: MCQQuestionData[];
    total_questions: number;
    generation_mode: string;
    session_topic?: string | null;
    checkpoint_index?: number | null;
}

/** Per-question scoring detail returned by the submit endpoint. */
export interface QuestionResult {
    correct: boolean;
    chosen_answer: string;
    correct_answer: string;
    explanation: string;
    question_type?: string;
    topic?: string;
    concept_id?: string | null;
}

export interface CheckpointResultData {
    score: number; // 0..1
    per_topic_scores: Record<string, number>;
    per_concept_scores: Record<string, number>;
    correct_count: number;
    total_count: number;
    question_results: QuestionResult[];
}

/** A source chunk fed to the generator: one representative chunk per topic. */
export interface CheckpointChunk {
    text: string;
    topic: string;
    concept_id?: string;
}

export interface GenerateCheckpointPayload {
    chunks: CheckpointChunk[];
    course_id: string;
    student_id: string; // overwritten server-side by the verified identity
    session_topic: string;
    session_number: number;
    checkpoint_index: number;
    questions_per_chunk: number;
    context: {
        mastery_level: 'Novice' | 'Intermediate' | 'Expert';
        student_id: string;
        course_id: string;
        topic_performance?: Record<string, number>;
        concept_mastery?: Record<string, number>;
        incorrectly_answered?: Array<Record<string, unknown>>;
    };
}

/** Generate the MCQs for one knowledge checkpoint. Throws on failure or if the
 *  generator returned nothing (callers surface a clear error, never a blank quiz). */
export async function generateSessionCheckpoint(
    payload: GenerateCheckpointPayload,
): Promise<AssessmentResponseData> {
    const res = await api.post('/ai/assessments/session', payload);
    const data = res.data as AssessmentResponseData;
    if (!data || !Array.isArray(data.questions) || data.questions.length === 0) {
        throw new Error('The checkpoint generator returned no questions.');
    }
    return data;
}

export interface SubmitCheckpointPayload {
    questions: MCQQuestionData[];
    answers: Record<number, string>; // question index → chosen option text
    course_id: string;
    student_id: string; // overwritten server-side by the verified identity
    session_number: number;
    checkpoint_index: number;
}

/** Submit checkpoint answers; the server scores and records concept mastery. */
export async function submitCheckpoint(
    payload: SubmitCheckpointPayload,
): Promise<CheckpointResultData> {
    const res = await api.post('/ai/assessments/submit', payload);
    return res.data as CheckpointResultData;
}
