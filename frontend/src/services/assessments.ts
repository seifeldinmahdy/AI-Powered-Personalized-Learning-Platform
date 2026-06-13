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
 *  Falls back to a built-in static bank if the service is unavailable. */
export async function generateAssessmentQuestions(
    topic: string,
    count = 6,
): Promise<AssessmentQuestion[]> {
    try {
        const res = await fetch(`${AI_SERVICE}/assessments/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ course_title: topic, num_questions: count }),
        });
        if (!res.ok) throw new Error('AI service error');
        const data = await res.json();
        if (Array.isArray(data.questions)) {
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
    } catch {
        // fall through to static bank
    }
    return buildStaticBank(topic, count);
}

/** A category group with its questions, returned by the categorized endpoint. */
export interface CategoryGroup {
    name: string;
    description: string;
    questions: AssessmentQuestion[];
}

/** Generate placement-test questions grouped by LLM-derived categories.
 *  Falls back to flat generation if the categorized endpoint is unavailable. */
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
        if (!res.ok) throw new Error('Categorized endpoint error');
        const data = await res.json();
        if (Array.isArray(data.categories)) {
            let globalId = 1;
            return data.categories.map((cat: any) => ({
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
        }
    } catch (e) {
        console.warn('Categorized generation failed, falling back to flat:', e);
    }

    // Fallback: use flat generation and wrap in a single category
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

// ── Static fallback bank ──────────────────────────────────────────────────────

function buildStaticBank(topic: string, count: number): AssessmentQuestion[] {
    const t = topic.toLowerCase();
    const bank: AssessmentQuestion[] = [
        {
            id: 1,
            question: `What is the primary purpose of a variable in ${topic}?`,
            options: [
                'To store data that can be used later',
                'To define the structure of a program',
                'To execute a set of instructions',
                'To connect to a database',
            ],
            correct: 0,
            topic: 'Variables',
        },
        {
            id: 2,
            question: 'Which of the following is an example of a loop construct?',
            options: ['if / else', 'for / while', 'try / catch', 'class / object'],
            correct: 1,
            topic: 'Loops',
        },
        {
            id: 3,
            question: 'What does a function return when no return statement is specified?',
            options: ['0', 'An empty string', 'null / None / undefined (depends on language)', 'An error'],
            correct: 2,
            topic: 'Functions',
        },
        {
            id: 4,
            question: 'What is Big-O notation used to describe?',
            options: [
                'The size of a program in bytes',
                'The time or space complexity of an algorithm',
                'The number of lines of code',
                'The version of a programming language',
            ],
            correct: 1,
            topic: 'Algorithms',
        },
        {
            id: 5,
            question: `Which data structure follows the Last-In-First-Out (LIFO) principle?`,
            options: ['Queue', 'Array', 'Stack', 'Linked list'],
            correct: 2,
            topic: 'Data Structures',
        },
        {
            id: 6,
            question: 'What is recursion?',
            options: [
                'A loop that runs forever',
                'A function that calls itself',
                'A method of sorting data',
                'A way to import libraries',
            ],
            correct: 1,
            topic: 'Recursion',
        },
        {
            id: 7,
            question: `In ${topic}, what keyword is typically used to define a class?`,
            options: [
                t.includes('python') ? 'class' : 'class',
                'def',
                'struct',
                'module',
            ],
            correct: 0,
            topic: 'OOP',
        },
        {
            id: 8,
            question: 'Which of the following best describes an API?',
            options: [
                'A graphical user interface',
                'A set of rules that allows programs to communicate',
                'A type of database',
                'A programming language',
            ],
            correct: 1,
            topic: 'APIs',
        },
    ];
    return bank.slice(0, count);
}
