/**
 * Coding Practice API service.
 *
 * - generateQuestion      → FastAPI (port 8001, no auth)
 * - evaluateCode          → Django bridge (auth token via shared `api` instance)
 * - getRubric             → Django bridge
 * - evaluateCodeGraded    → Django bridge
 * - getHint               → Django bridge
 */

import axios from "axios";
import api from "./api";

const AI_BASE_URL: string =
    import.meta.env.VITE_AI_URL || "http://127.0.0.1:8001";

const aiClient = axios.create({
    baseURL: AI_BASE_URL,
    headers: { "Content-Type": "application/json" },
});

// ---------- Types ----------

export interface GenerateQuestionResponse {
    question: string;
    starter_code: string;
}

export interface EvaluateCodeResponse {
    status: "Pass" | "Needs Work" | string;
    feedback: string;
}

export interface RubricCriterion {
    name: string;
    weight: number;
    description: string;
}

export interface Rubric {
    criteria: RubricCriterion[];
    total_points: number;
}

export interface BreakdownItem {
    criterion: string;
    earned: number;
    max: number;
    comment: string;
}

export interface GradedResult {
    score: number;
    letter_grade: string;
    status: "Pass" | "Needs Work" | "Error";
    breakdown: BreakdownItem[];
    feedback: string;
    hint: string;
}

// ---------- API calls ----------

export const generateQuestion = async (
    topic: string
): Promise<GenerateQuestionResponse> => {
    const { data } = await aiClient.post<GenerateQuestionResponse>(
        "/api/coding/generate",
        { topic }
    );
    return data;
};

export const evaluateCode = async (
    question: string,
    code: string
): Promise<EvaluateCodeResponse> => {
    const { data } = await api.post<EvaluateCodeResponse>(
        "/courses/coding/evaluate/",
        { question, code }
    );
    return data;
};

export const getRubric = async (question: string): Promise<Rubric> => {
    const { data } = await api.post<Rubric>("/courses/coding/rubric/", { question });
    return data;
};

export const evaluateCodeGraded = async (
    question: string,
    code: string,
    rubric?: Rubric
): Promise<GradedResult> => {
    const payload: Record<string, unknown> = { question, code };
    if (rubric) payload.rubric = rubric;
    const { data } = await api.post<GradedResult>(
        "/courses/coding/evaluate-graded/",
        payload
    );
    return data;
};

export const getHint = async (
    question: string,
    code: string,
    hintLevel: number
): Promise<{ hint: string; level: number }> => {
    const { data } = await api.post<{ hint: string; level: number }>(
        "/courses/coding/hint/",
        { question, code, hint_level: hintLevel }
    );
    return data;
};
