/**
 * Tutor API client — communicates with the FastAPI AI tutor service.
 * Talks directly to the AI service (port 8001) for tutor endpoints.
 */

import axios from "axios";

const AI_SERVICE_URL: string =
  import.meta.env.VITE_AI_SERVICE_URL || "http://localhost:8001";

const aiApi = axios.create({
  baseURL: AI_SERVICE_URL,
  headers: { "Content-Type": "application/json" },
});

// ─── Types ──────────────────────────────────────────────────────

export interface TopicInput {
  name: string;
  subtopics: string[];
}

export interface StartSessionResponse {
  success: boolean;
  session_id: string;
  topics_count: number;
  total_items: number;
  status: string;
  voice: string;
}

export interface ContinueResponse {
  success: boolean;
  session_id: string;
  text: string;
  audio_base64: string | null;
  topic: string | null;
  subtopic: string | null;
  progress: number;
  is_finished: boolean;
  status: string;
  inference_time: number | null;
}

export interface AskResponse {
  success: boolean;
  session_id: string;
  answer: string;
  audio_base64: string | null;
  topic: string | null;
  subtopic: string | null;
  progress: number;
  is_finished: boolean;
  status: string;
  inference_time: number | null;
}

export interface StatusResponse {
  success: boolean;
  session_id: string;
  status: string;
  current_topic: string | null;
  current_subtopic: string | null;
  progress: number;
  is_finished: boolean;
  topics_count: number;
  transcript_length: number;
  voice: string;
}

// ─── API calls ──────────────────────────────────────────────────

export const startSession = (
  topics: TopicInput[],
  voice?: string,
  sessionId?: string
) =>
  aiApi.post<StartSessionResponse>("/tutor/start", {
    topics,
    voice: voice || "en-US-JennyNeural",
    session_id: sessionId,
  });

export const continueSession = (
  sessionId: string,
  includeAudio: boolean = true
) =>
  aiApi.post<ContinueResponse>("/tutor/continue", {
    session_id: sessionId,
    include_audio: includeAudio,
  });

export const askQuestion = (
  sessionId: string,
  question: string,
  includeAudio: boolean = true
) =>
  aiApi.post<AskResponse>("/tutor/ask", {
    session_id: sessionId,
    question,
    include_audio: includeAudio,
  });

export const getSessionStatus = (sessionId: string) =>
  aiApi.get<StatusResponse>("/tutor/status", {
    params: { session_id: sessionId },
  });

export const stopSession = (sessionId: string) =>
  aiApi.post("/tutor/stop", { session_id: sessionId });
