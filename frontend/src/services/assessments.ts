import api from './api';

const AI_SERVICE = import.meta.env.VITE_AI_SERVICE_URL ?? 'http://localhost:8001';

export interface AssessmentQuestion {
    id: number;
    question: string;
    options: string[];
    correct: number; // index of correct option
}

/** Generate placement-test questions for a course topic via the AI microservice.
 *  Falls back to a built-in static bank if the service is unavailable. */
export async function generateAssessmentQuestions(
    topic: string,
    count = 6,
): Promise<AssessmentQuestion[]> {
    try {
        const res = await fetch(`${AI_SERVICE}/api/assessments/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic, count }),
        });
        if (!res.ok) throw new Error('AI service error');
        const data = await res.json();
        if (Array.isArray(data.questions)) return data.questions as AssessmentQuestion[];
    } catch {
        // fall through to static bank
    }
    return buildStaticBank(topic, count);
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
        },
        {
            id: 2,
            question: 'Which of the following is an example of a loop construct?',
            options: ['if / else', 'for / while', 'try / catch', 'class / object'],
            correct: 1,
        },
        {
            id: 3,
            question: 'What does a function return when no return statement is specified?',
            options: ['0', 'An empty string', 'null / None / undefined (depends on language)', 'An error'],
            correct: 2,
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
        },
        {
            id: 5,
            question: `Which data structure follows the Last-In-First-Out (LIFO) principle?`,
            options: ['Queue', 'Array', 'Stack', 'Linked list'],
            correct: 2,
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
        },
    ];
    return bank.slice(0, count);
}
