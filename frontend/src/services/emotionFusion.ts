/**
 * Emotion Fusion — resolves FER (facial) and SER (speech) into one fused emotion.
 *
 * Agreement   → use that emotion directly.
 * Conflict    → ask the AI service (Groq LLM) to arbitrate, 3 s timeout.
 * One missing → use whichever is present.
 * Both missing→ "neutral".
 */

import api from './api';

export interface FusionInput {
  fer_emotion?: string;
  fer_confidence?: number;
  ser_emotion?: string;
  ser_confidence?: number;
}

export interface FusionContext {
  slide_index?: number;
  slide_title?: string;
  subtopic?: string;
  session_id?: string;
  // student_id is no longer sent by the browser — Django sets the verified
  // identity server-side for consent/attribution (Track 1 / Approach A).
  course_id?: string;
}

export interface FusionResult {
  fused_emotion: string;
  reasoning?: string;
}

export async function fuseEmotions(
  input: FusionInput,
  context: FusionContext = {},
): Promise<FusionResult> {
  const { fer_emotion, fer_confidence, ser_emotion, ser_confidence } = input;

  // Both missing → neutral
  if (!fer_emotion && !ser_emotion) {
    return { fused_emotion: 'neutral', reasoning: 'No emotion data available' };
  }

  // Only one modality
  if (!fer_emotion) {
    return { fused_emotion: ser_emotion!, reasoning: 'Only SER available' };
  }
  if (!ser_emotion) {
    return { fused_emotion: fer_emotion, reasoning: 'Only FER available' };
  }

  // Both present and agree
  if (fer_emotion.toLowerCase() === ser_emotion.toLowerCase()) {
    // If they agree, we still want to log it if session_id is present
    if (context.session_id) {
      try {
        api.post('/ai/profiler/fuse-emotions', {
          fer_emotion,
          fer_confidence: fer_confidence ?? 0,
          ser_emotion,
          ser_confidence: ser_confidence ?? 0,
          slide_index: context.slide_index ?? 0,
          slide_title: context.slide_title ?? '',
          subtopic: context.subtopic ?? '',
          session_id: context.session_id,
          course_id: context.course_id ?? '',
        }).catch(console.error);
      } catch {}
    }
    return { fused_emotion: fer_emotion, reasoning: 'FER and SER agree' };
  }

  // Conflict — ask the AI service (through Django) with a 3 s timeout
  try {
    const res = await api.post('/ai/profiler/fuse-emotions', {
      fer_emotion,
      fer_confidence: fer_confidence ?? 0,
      ser_emotion,
      ser_confidence: ser_confidence ?? 0,
      slide_index: context.slide_index ?? 0,
      slide_title: context.slide_title ?? '',
      subtopic: context.subtopic ?? '',
      session_id: context.session_id,
      course_id: context.course_id ?? '',
    }, { timeout: 3000 });

    if (res.status >= 200 && res.status < 300) {
      return {
        fused_emotion: res.data.fused_emotion,
        reasoning: res.data.reasoning,
      };
    }
  } catch {
    // Timeout or network error — fall through to confidence-based fallback
  }

  // Fallback: use whichever modality has higher confidence
  const ferConf = fer_confidence ?? 0;
  const serConf = ser_confidence ?? 0;
  const fallback = ferConf >= serConf
    ? { fused_emotion: fer_emotion, reasoning: 'Fallback: FER has higher confidence' }
    : { fused_emotion: ser_emotion, reasoning: 'Fallback: SER has higher confidence' };
  return fallback;
}
