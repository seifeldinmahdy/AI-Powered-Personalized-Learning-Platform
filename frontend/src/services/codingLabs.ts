const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';

export interface LabSlideContext {
  title: string;
  content: string;
  code?: string;
}

export interface CodingLabGenerateRequest {
  student_id: string;
  course_id: string;
  lesson_id: string;
  lesson_title: string;
  session_id?: string;
  student_profile_summary?: string;
  slides?: LabSlideContext[];
  force_regenerate?: boolean;
}

export interface LabChecklistItem {
  id: string;
  item: string;
  reason: string;
}

export interface LabCell {
  id: string;
  cell_type: 'explanation' | 'code' | 'task';
  title: string;
  narrative?: string;
  code?: string;
  expected_output?: string;
  task_prompt?: string;
  starter_code?: string;
  success_criteria?: string[];
  tutor_script?: string;
  tips?: string[];
}

export interface CodingLab {
  title: string;
  intro: string;
  estimated_minutes: number;
  tutor_opening: string;
  cells: LabCell[];
  completion_message: string;
}

export interface CodingLabGenerateResponse {
  lab_id: string;
  cached: boolean;
  generated_at: string;
  checklist: LabChecklistItem[];
  lab: CodingLab;
}

export interface LabExplainResponse {
  success: boolean;
  text: string;
  audio_base64: string | null;
  blendshapes: { names: string[]; frames: number[][] } | null;
}

export interface LabRunResponse {
  success: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
}

export async function generateCodingLab(
  request: CodingLabGenerateRequest,
): Promise<CodingLabGenerateResponse> {
  const res = await fetch(`${AI_URL}/api/coding/labs/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Lab generation failed: ${detail}`);
  }
  return res.json();
}

export async function explainLabCell(request: {
  session_id?: string;
  lab_title: string;
  cell: LabCell;
  mode: 'explain' | 'tip';
  student_profile_summary?: string;
}): Promise<LabExplainResponse> {
  const res = await fetch(`${AI_URL}/api/coding/labs/explain`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Lab narration failed: ${detail}`);
  }
  return res.json();
}

export async function runLabCode(code: string): Promise<LabRunResponse> {
  const res = await fetch(`${AI_URL}/api/coding/labs/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Lab run failed: ${detail}`);
  }
  return res.json();
}
