import api from './api'; // use the existing Axios instance with JWT
import axios from 'axios';

export interface PlacementQuestion {
  id: number;
  question: string;
  options: string[];
  correct_answer: string;
  topic: string;
  concept_id: string | null;
  order: number;
}

export interface PlacementQuestionDraft {
  question: string;
  options: string[];
  correct_answer: string;
  topic: string;
  concept_id: string | null;
  order: number;
}

const base = (courseId: number) =>
  `/courses/courses/${courseId}/placement-questions/`;

// ── Admin CRUD ──────────────────────────────────────────────────────────────

export async function getPlacementQuestions(courseId: number): Promise<PlacementQuestion[]> {
  const { data } = await api.get<PlacementQuestion[]>(base(courseId));
  return data;
}

export async function createPlacementQuestion(
  courseId: number,
  payload: PlacementQuestionDraft,
): Promise<PlacementQuestion> {
  const { data } = await api.post<PlacementQuestion>(base(courseId), payload);
  return data;
}

export async function updatePlacementQuestion(
  courseId: number,
  questionId: number,
  payload: Partial<PlacementQuestionDraft>,
): Promise<PlacementQuestion> {
  const { data } = await api.patch<PlacementQuestion>(
    `${base(courseId)}${questionId}/`,
    payload,
  );
  return data;
}

export async function deletePlacementQuestion(
  courseId: number,
  questionId: number,
): Promise<void> {
  await api.delete(`${base(courseId)}${questionId}/`);
}

export async function bulkSavePlacementQuestions(
  courseId: number,
  questions: PlacementQuestionDraft[],
): Promise<PlacementQuestion[]> {
  const { data } = await api.post<PlacementQuestion[]>(
    `${base(courseId)}bulk-save/`,
    { questions },
  );
  return data;
}

// ── AI generation (calls FastAPI ai_service) ────────────────────────────────
// Note: the AI service URL is the direct FastAPI base, same pattern as other AI calls.

const AI_BASE = import.meta.env.VITE_AI_SERVICE_URL ?? 'http://localhost:8001';

interface CLOPlanItem {
  name: string;
  description: string;
  concepts: { id: string; label: string }[];
}

export async function generatePlacementQuestions(params: {
  courseTitle: string;
  clos?: CLOPlanItem[];
  numQuestions?: number;
}): Promise<PlacementQuestionDraft[]> {
  const { data } = await axios.post<{ questions: PlacementQuestionDraft[] }>(
    `${AI_BASE}/assessments/generate-for-course`,
    {
      course_title: params.courseTitle,
      clos: params.clos ?? [],
      num_questions: params.numQuestions ?? 10,
    },
  );
  return data.questions ?? [];
}

export async function refinePlacementQuestion(params: {
  question: PlacementQuestionDraft;
  instruction: string;
  courseTitle: string;
}): Promise<PlacementQuestionDraft> {
  const { data } = await axios.post<PlacementQuestionDraft>(
    `${AI_BASE}/assessments/refine-question`,
    {
      question: params.question,
      instruction: params.instruction,
      course_title: params.courseTitle,
    },
  );
  return data;
}
