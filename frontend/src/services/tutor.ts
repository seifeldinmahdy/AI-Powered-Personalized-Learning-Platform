const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export interface TutorSession {
  session_id: string;
  topics_count: number;
  total_items: number;
  status: string;
  voice: string;
}

export interface BlendshapeData {
  names: string[];
  frames: number[][];
}

export interface LectureChunk {
  success: boolean;
  session_id: string;
  text: string;
  audio_base64: string | null;
  blendshapes: BlendshapeData | null;
  topic: string;
  subtopic: string | null;
  progress: number;
  is_finished: boolean;
  status: string;
}

export interface AskResponse {
  success: boolean;
  session_id: string;
  answer: string;
  audio_base64: string | null;
  blendshapes: BlendshapeData | null;
  topic: string;
  subtopic: string | null;
  progress: number;
  is_finished: boolean;
  status: string;
  grounded?: boolean;
}

export interface SERResult {
  emotion: string;
  confidence: number;
}

export async function startTutorSession(
  lessonTitle: string,
  subtopics: string[] = [],
  voice = 'en-US-GuyNeural',
  student_profile_summary?: string,
  session_id?: string,
): Promise<TutorSession> {
  const body: Record<string, unknown> = {
    topics: [{ name: lessonTitle, subtopics }],
    voice,
  };
  if (student_profile_summary) {
    body.student_profile_summary = student_profile_summary;
  }
  if (session_id) {
    body.session_id = session_id;
  }
  const res = await fetch(`${AI_URL}/tutor/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Failed to start tutor session');
  return res.json();
}

export async function continueTutorSession(
  session_id: string,
  include_audio = true,
  student_emotion?: string,
): Promise<LectureChunk> {
  const res = await fetch(`${AI_URL}/tutor/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, include_audio, student_emotion }),
  });
  if (!res.ok) throw new Error('Failed to continue tutor session');
  return res.json();
}

export async function askTutor(
  session_id: string,
  question: string,
  include_audio = true,
  student_emotion?: string,
  grounding?: RAGPassage[],
): Promise<AskResponse> {
  const res = await fetch(`${AI_URL}/tutor/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // `grounding` carries the RAW retrieved passages; the tutor grounds on these
    // primary excerpts rather than a pre-generated RAG answer.
    body: JSON.stringify({ session_id, question, include_audio, student_emotion, grounding }),
  });
  if (!res.ok) throw new Error('Failed to ask tutor');
  return res.json();
}

export interface IntentPrediction {
  intent_name: string;
  label_id: number;
  confidence: number;
  probabilities: Record<string, number>;
  raw_prediction?: string | null;
  raw_confidence?: number | null;
}

export interface ChatLogEntry {
  id: number;
  transcript_text: string;
  ai_response_text: string;
  created_at: string;
  predicted_intent?: string;
  confidence?: number;
  intent_probabilities?: Record<string, number>;
  feedback?: 'thumbs_up' | 'thumbs_down' | null;
}

export interface PersistChatLogPayload {
  lesson: number;
  transcript_text: string;
  ai_response_text: string;
  session_id?: string;
  session_context?: string;
  predicted_intent?: string;
  confidence?: number;
  intent_probabilities?: Record<string, number>;
}

export async function getChatHistory(lessonId: number): Promise<ChatLogEntry[]> {
  const token = localStorage.getItem('access_token');
  if (!token) return [];
  try {
    const res = await fetch(`${API_URL}/progress/chat-logs/?lesson_id=${lessonId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : data.results ?? [];
  } catch {
    return [];
  }
}

export async function persistChatLog(payload: PersistChatLogPayload): Promise<ChatLogEntry | null> {
  const token = localStorage.getItem('access_token');
  if (!token || !payload.lesson) return null;
  const res = await fetch(`${API_URL}/progress/chat-logs/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
  if (!res.ok) return null;
  return res.json() as Promise<ChatLogEntry>;
}

export type FeedbackValue = 'thumbs_up' | 'thumbs_down';

export interface FeedbackResponse {
  id: number;
  feedback: FeedbackValue;
  feedback_at: string;
  retraining_counter: number;
  threshold: number;
  retraining_recommended: boolean;
}

export async function submitFeedback(
  chatLogId: number,
  feedback: FeedbackValue,
  correctedIntent?: string,
): Promise<FeedbackResponse | null> {
  const token = localStorage.getItem('access_token');
  if (!token) return null;
  const body: Record<string, unknown> = { feedback };
  if (correctedIntent) {
    body.corrected_intent = correctedIntent;
  }
  const res = await fetch(`${API_URL}/progress/chat-logs/${chatLogId}/feedback/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) return null;
  return res.json() as Promise<FeedbackResponse>;
}

export async function stopTutorSession(session_id: string): Promise<void> {
  await fetch(`${AI_URL}/tutor/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id }),
  });
}

export async function setTutorPace(session_id: string, pace: 'slow' | 'normal' | 'fast'): Promise<void> {
  const res = await fetch(`${AI_URL}/tutor/set-pace`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, pace }),
  });
  if (!res.ok) throw new Error('Failed to set tutor pace');
}

export async function transcribeAudio(audioBlob: Blob): Promise<string> {
  const formData = new FormData();
  formData.append('audio_file', audioBlob, 'recording.wav');
  formData.append('language', 'en');
  const res = await fetch(`${AI_URL}/asr/transcribe`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error('Failed to transcribe audio');
  const data = await res.json();
  return data.transcription as string;
}

export interface RAGSource {
  book: string;
  page_start: number;
  page_end: number;
  topic: string;
  relevance_score: number;
}

/** A raw retrieved source passage: primary text + citation. */
export interface RAGPassage extends RAGSource {
  chunk_id: string;
  text: string;
}

export interface RAGResult {
  question: string;
  passages: RAGPassage[];
  grounded: boolean;
}

/** Retrieve RAW textbook passages for a question, scoped to the course corpus.
 *  `courseId` is the Django course id — the AI service resolves it to the
 *  course's corpus scope server-side so the tutor can only cite this course. */
export async function askRag(question: string, courseId: string): Promise<RAGResult> {
  const res = await fetch(`${AI_URL}/rag/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, course_id: String(courseId), top_k: 5 }),
  });
  if (!res.ok) throw new Error('RAG unavailable');
  return res.json();
}

export async function checkRelevance(question: string, lessonTitle: string): Promise<boolean> {
  try {
    const res = await fetch(`${AI_URL}/tutor/relevance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, lesson_title: lessonTitle }),
    });
    if (!res.ok) return true;
    const data = await res.json();
    return data.relevant as boolean;
  } catch {
    return true; // fail open
  }
}

export type IntentName = 'On-Topic Question' | 'Off-Topic Question' | 'Emotional-State' | 'Pace-Related' | 'Repeat/clarification';

export async function classifyIntent(text: string, sessionId = ''): Promise<IntentPrediction | null> {
  try {
    const res = await fetch(`${AI_URL}/intent/classify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // Send only the real session_id. The AI service auto-fills the classifier
      // context (topic / emotion / pace / ability / slides) from
      // SharedSessionStore, so we never build a client-side context string.
      body: JSON.stringify({ student_input: text, session_id: sessionId }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const pred = data.predictions?.[0];
    if (!pred) return null;
    return pred as IntentPrediction;
  } catch {
    return null;
  }
}

/**
 * Analyze speech emotion from an audio blob via the SER service.
 * Endpoint: POST /ser/predict  (field name: "audio")
 */
export async function analyzeSpeechEmotion(audioBlob: Blob): Promise<SERResult> {
  const formData = new FormData();
  formData.append('audio', audioBlob, 'recording.wav');
  const res = await fetch(`${AI_URL}/ser/predict`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error('SER analysis failed');
  const data = await res.json();
  return { emotion: data.emotion, confidence: data.confidence };
}

export function playAudioBase64(base64: string): HTMLAudioElement {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: 'audio/mpeg' });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  return audio;
}

export async function synthesizeAudio(text: string, emotion?: string, session_id?: string | null): Promise<string> {
  if (session_id) {
    const res = await fetch(`${AI_URL}/tutor/synthesize-audio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id, text, student_emotion: emotion }),
    });
    if (!res.ok) throw new Error('Failed to synthesize tutor audio');
    const data = await res.json();
    if (data.audio_base64) {
      return data.audio_base64;
    }
  }

  // Fallback if no session_id
  const res = await fetch(`${AI_URL}/tts/synthesize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      voice: 'en-US-GuyNeural',
      rate: emotion === 'calm' ? '-10%' : '+0%',
      pitch: '+0Hz',
    }),
  });
  if (!res.ok) throw new Error('Failed to synthesize audio');
  const blob = await res.blob();
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}
