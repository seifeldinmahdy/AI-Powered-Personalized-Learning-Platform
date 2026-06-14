/**
 * Pathway & Slide Generation service.
 * Talks to the AI service's /pathway and /slides endpoints.
 */

const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';

// ── Pathway types ──────────────────────────────────────────────

export interface PathwaySession {
  session_number: number;
  session_title: string;
  topics_covered: string[];
  concept_ids?: string[];   // provenance
  clo_codes?: string[];     // provenance
  estimated_token_count: number;
  chunk_count: number;
  book: string;
  page_range_start: number;
  page_range_end: number;
}

export interface PathwayPlan {
  student_id: string;
  course_id: string;
  total_sessions: number;
  total_chunks: number;
  generated_at: string;
  cached: boolean;
  plan_version: number;     // authoritative version (pins slide caches)
  sessions: PathwaySession[];
}

export interface GeneratePathwayRequest {
  student_id: string;
  course_id: string;
  mastery_level?: string;
  composition_mode?: string;
  language_proficiency?: string;
  strengths?: string[];
  weaknesses?: string[];
  // Authoritative concept-id sets for personalization (Django Concept.id).
  strength_concept_ids?: string[];
  weak_concept_ids?: string[];
  // DEPRECATED: parallel topic signal; concept data is the source of truth.
  topic_performance?: Record<string, number>;
  incorrectly_answered?: Array<{question: string; chosen_option: string; correct_option: string}>;
  use_synthetic_context?: boolean;
}

// ── Slide types ────────────────────────────────────────────────

export interface SlideContentItem {
  text: string;
  highlight_type: string;
  term?: string | null;
}

export interface SlideCodeBlock {
  language: string;
  code: string;
}

export interface SlideVisual {
  template: string;
  params: Record<string, unknown>;
}

export interface SlideEquationItem {
  latex: string;
  label: string;
  display: boolean;
}

export interface GeneratedSlide {
  slide_number: number;
  slide_type: string;
  layout: string;
  title: string;
  body_content: SlideContentItem[];
  visual?: SlideVisual | null;
  code_block?: SlideCodeBlock | null;
  equation_block?: SlideEquationItem[] | null;
  alt_text?: string | null;
  source_chunk_id: string;
  source_topic: string;
  source_page_start: number;
  source_page_end: number;
  visual_type: string;
}

export interface SlideGenerateResponse {
  session_number: number;
  session_title: string;
  total_slides: number;
  slides: GeneratedSlide[];
  generation_time_seconds: number;
}

export interface SessionChunk {
  chunk_id: string;
  raw_text: string;
  topic?: string;
  page_start?: number;
  page_end?: number;
}

export interface SlideGenerateRequest {
  session_number: number;
  session_title: string;
  topics_covered: string[];
  book: string;
  chunks: SessionChunk[];
  // Personalization (mastery_level / composition_mode / language_proficiency)
  // is derived server-side from the student's stored context. The client only
  // identifies the student; it never sends personalization literals.
  student_id: string;
  course_id: string;
  // Authoritative plan version that pins the persisted deck (Batch 5/10a).
  plan_version?: number;
}

// ── API calls ──────────────────────────────────────────────────

/** Read-only fetch of the CURRENT authoritative plan. Opening the pathway page
 *  must NOT generate — generation happens once, server-side, after placement. */
export async function getCurrentPathway(
  studentId: string,
  courseId: string,
): Promise<PathwayPlan> {
  const res = await fetch(
    `${AI_URL}/pathway/current?student_id=${encodeURIComponent(studentId)}&course_id=${encodeURIComponent(courseId)}`,
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`No pathway available: ${detail}`);
  }
  return res.json();
}

/** @deprecated Generation is server-side (post-placement) and service-key gated;
 *  the browser cannot call /pathway/generate. Use getCurrentPathway to read. */
export async function generatePathway(
  request: GeneratePathwayRequest,
): Promise<PathwayPlan> {
  const res = await fetch(`${AI_URL}/pathway/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Pathway generation failed: ${detail}`);
  }
  return res.json();
}

export async function generateSlides(
  request: SlideGenerateRequest,
): Promise<SlideGenerateResponse> {
  const res = await fetch(`${AI_URL}/slides/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Slide generation failed: ${detail}`);
  }
  return res.json();
}

/** Fetch a previously persisted deck (resume) so we don't regenerate after a
 *  restart / on another device. Returns null when none is saved. */
export async function getPersistedSlides(
  studentId: string,
  courseId: string,
  sessionNumber: number,
  planVersion: number,
): Promise<SlideGenerateResponse | null> {
  const params = new URLSearchParams({
    student_id: studentId,
    course_id: courseId,
    session_number: String(sessionNumber),
    plan_version: String(planVersion),
  });
  const res = await fetch(`${AI_URL}/slides/persisted?${params.toString()}`);
  if (!res.ok) return null;
  return res.json();
}

export async function checkPathwayHealth(): Promise<{
  status: string;
  indexed_chunks?: number;
  available_courses?: string[];
}> {
  const res = await fetch(`${AI_URL}/pathway/health`);
  return res.json();
}

export async function checkSlidesHealth(): Promise<{
  status: string;
  content_model?: string;
  classifier_model?: string;
}> {
  const res = await fetch(`${AI_URL}/slides/health`);
  return res.json();
}
