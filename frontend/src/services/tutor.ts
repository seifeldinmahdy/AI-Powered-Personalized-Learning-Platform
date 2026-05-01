const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export interface TutorSession {
  session_id: string;
  topics_count: number;
  total_items: number;
  status: string;
  voice: string;
}

export interface LectureChunk {
  success: boolean;
  session_id: string;
  text: string;
  audio_base64: string | null;
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
  topic: string;
  subtopic: string | null;
  progress: number;
  is_finished: boolean;
  status: string;
}

export interface SERResult {
  emotion: string;
  confidence: number;
}

export async function startTutorSession(
  lessonTitle: string,
  subtopics: string[] = [],
  voice = 'en-US-JennyNeural',
  student_profile_summary?: string,
): Promise<TutorSession> {
  const body: Record<string, unknown> = {
    topics: [{ name: lessonTitle, subtopics }],
    voice,
  };
  if (student_profile_summary) {
    body.student_profile_summary = student_profile_summary;
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
): Promise<AskResponse> {
  const res = await fetch(`${AI_URL}/tutor/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, question, include_audio, student_emotion }),
  });
  if (!res.ok) throw new Error('Failed to ask tutor');
  return res.json();
}

export interface ChatLogEntry {
  id: number;
  transcript_text: string;
  ai_response_text: string;
  created_at: string;
}

export async function getChatHistory(lessonId: number): Promise<ChatLogEntry[]> {
  const token = localStorage.getItem('token');
  if (!token) return [];
  try {
    const res = await fetch(`${API_URL}/progress/chat-logs/?lesson_id=${lessonId}`, {
      headers: { Authorization: `Token ${token}` },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : data.results ?? [];
  } catch {
    return [];
  }
}

export function persistChatLog(lessonId: number, transcriptText: string, aiResponseText: string): void {
  const token = localStorage.getItem('token');
  if (!token || !lessonId) return;
  fetch(`${API_URL}/progress/chat-logs/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Token ${token}` },
    body: JSON.stringify({ lesson: lessonId, transcript_text: transcriptText, ai_response_text: aiResponseText }),
  }).catch(() => {/* fire-and-forget */});
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

export interface RAGAnswer {
  answer: string;
  sources: RAGSource[];
}

export async function askRag(question: string, topic?: string): Promise<RAGAnswer> {
  const res = await fetch(`${AI_URL}/rag/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, topic, top_k: 5 }),
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

export async function classifyIntent(text: string, sessionContext = ''): Promise<IntentName> {
  try {
    const res = await fetch(`${AI_URL}/intent/classify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_input: text, session_context: sessionContext }),
    });
    if (!res.ok) return 'On-Topic Question';
    const data = await res.json();
    return data.predictions?.[0]?.intent_name as IntentName ?? 'On-Topic Question';
  } catch {
    return 'On-Topic Question';
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
      voice: 'en-US-JennyNeural',
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


