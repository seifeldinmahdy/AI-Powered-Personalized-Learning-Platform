/**
 * Coding Practice API service.
 *
 * - generateQuestion  → FastAPI (port 8001, no auth)
 * - evaluateCode      → Django  (port 8000, with auth token via shared `api` instance)
 */

import axios from "axios";
import api from "./api";

// ---------- FastAPI client (AI micro-service, no auth) ----------
const AI_BASE_URL: string =
    import.meta.env.VITE_AI_URL || "http://127.0.0.1:8001";

const aiClient = axios.create({
    baseURL: AI_BASE_URL,
    headers: { "Content-Type": "application/json" },
});

// ---------- Types ----------
export interface GenerateQuestionRequest {
    topic: string;
}

export interface GenerateQuestionResponse {
    question: string;
    starter_code: string;
}

export interface EvaluateCodeRequest {
    question: string;
    code: string;
}

export interface EvaluateCodeResponse {
    grade: number | string;
    passed: boolean;
    feedback: string;
    [key: string]: unknown; // allow extra fields from the AI
}

// ---------- API calls ----------

/**
 * Ask the local LLM to generate a coding question for the given topic.
 * Hits FastAPI directly: POST /api/coding/generate
 */
export const generateQuestion = async (
    topic: string
): Promise<GenerateQuestionResponse> => {
    const { data } = await aiClient.post<GenerateQuestionResponse>(
        "/api/coding/generate",
        { topic } satisfies GenerateQuestionRequest
    );
    return data;
};

/**
 * Submit student code to be evaluated by the AI via Django bridge.
 * Hits Django: POST /api/coding/evaluate/
 */
export const evaluateCode = async (
    question: string,
    code: string
): Promise<EvaluateCodeResponse> => {
    const { data } = await api.post<EvaluateCodeResponse>(
        "/courses/coding/evaluate/",
        { question, code } satisfies EvaluateCodeRequest
    );
    return data;
};
