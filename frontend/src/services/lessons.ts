import api from './api';

// ---------- Types ----------

export interface Module {
    id: number;
    course: number;
    title: string;
    module_order: number;
}

export interface Lesson {
    id: number;
    module: number;
    title: string;
    lesson_order: number;
}

export interface Slide {
    id: number;
    lesson: number;
    content_json: Record<string, unknown>;
    slide_order: number;
}

export interface CodeChallenge {
    id: number;
    lesson: number;
    problem_text: string;
    starter_code: string;
    hint_text: string;
}

export interface LessonDetail extends Lesson {
    slides: Slide[];
    code_challenges: CodeChallenge[];
}

// ---------- Modules ----------

export async function getModules(courseId: number): Promise<Module[]> {
    const response = await api.get<Module[]>('/courses/modules/', {
        params: { course_id: courseId },
    });
    return response.data;
}

// ---------- Lessons ----------

export async function getLessons(moduleId: number): Promise<Lesson[]> {
    const response = await api.get<Lesson[]>('/courses/lessons/', {
        params: { module_id: moduleId },
    });
    return response.data;
}

export async function getLesson(id: number): Promise<LessonDetail> {
    const response = await api.get<LessonDetail>(`/courses/lessons/${id}/`);
    return response.data;
}

// ---------- Slides ----------

export async function getSlides(lessonId: number): Promise<Slide[]> {
    const response = await api.get<Slide[]>('/courses/slides/', {
        params: { lesson_id: lessonId },
    });
    return response.data;
}

// ---------- Code Challenges ----------

export async function getCodeChallenges(lessonId: number): Promise<CodeChallenge[]> {
    const response = await api.get<CodeChallenge[]>('/courses/code-challenges/', {
        params: { lesson_id: lessonId },
    });
    return response.data;
}
