const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';

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

export async function startTutorSession(
  lessonTitle: string,
  subtopics: string[] = [],
  voice = 'en-US-JennyNeural',
): Promise<TutorSession> {
  const res = await fetch(`${AI_URL}/tutor/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topics: [{ name: lessonTitle, subtopics }],
      voice,
    }),
  });
  if (!res.ok) throw new Error('Failed to start tutor session');
  return res.json();
}

export async function continueTutorSession(
  session_id: string,
  include_audio = true,
): Promise<LectureChunk> {
  const res = await fetch(`${AI_URL}/tutor/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, include_audio }),
  });
  if (!res.ok) throw new Error('Failed to continue tutor session');
  return res.json();
}

export async function askTutor(
  session_id: string,
  question: string,
  include_audio = true,
): Promise<AskResponse> {
  const res = await fetch(`${AI_URL}/tutor/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, question, include_audio }),
  });
  if (!res.ok) throw new Error('Failed to ask tutor');
  return res.json();
}

export async function stopTutorSession(session_id: string): Promise<void> {
  await fetch(`${AI_URL}/tutor/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id }),
  });
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
