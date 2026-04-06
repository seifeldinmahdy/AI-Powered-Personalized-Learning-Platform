/**
 * Session Emotion Logger — in-memory store for emotion events during a live session.
 *
 * Events accumulate here while the student is in a LiveSession.
 * On session end the full log is sent to the profiler, then cleared.
 */

export interface EmotionEvent {
  timestamp: string;                // ISO 8601
  slide_index: number;              // which slide was active
  slide_title?: string;             // optional slide heading
  subtopic?: string;                // current Dr. Nova subtopic if available
  fer_emotion?: string;             // e.g. "happy", "confused", "neutral"
  fer_confidence?: number;
  ser_emotion?: string;             // e.g. "excited", "bored", "anxious"
  ser_confidence?: number;
  fused_emotion: string;            // always present — resolved from available signals
  event_type: 'passive' | 'question'; // passive = FER poll, question = student asked
  question_transcript?: string;     // only if event_type === "question"
  dr_nova_response_summary?: string; // optional, only for question events
}

// ── Module-scoped in-memory store ──
let _sessionLog: EmotionEvent[] = [];

/** Append an emotion event to the in-memory log. */
export function logEmotionEvent(event: EmotionEvent): void {
  _sessionLog.push(event);
  console.log(
    `%c[EmotionLogger] Event #${_sessionLog.length}`,
    'color: #a78bfa; font-weight: bold',
    { type: event.event_type, fused: event.fused_emotion, fer: event.fer_emotion, ser: event.ser_emotion, slide: event.slide_index }
  );
}

/** Return the full array of emotion events recorded so far. */
export function getSessionLog(): EmotionEvent[] {
  return [..._sessionLog];
}

/** Return the fused_emotion from the most recent event, or "neutral" if empty. */
export function getRecentFusedEmotion(): string {
  if (_sessionLog.length === 0) return 'neutral';
  return _sessionLog[_sessionLog.length - 1].fused_emotion;
}

/** Reset the log (call on session start or after persisting). */
export function clearSessionLog(): void {
  console.log(
    `%c[EmotionLogger] Clearing ${_sessionLog.length} events`,
    'color: #f59e0b; font-weight: bold'
  );
  _sessionLog = [];
}
