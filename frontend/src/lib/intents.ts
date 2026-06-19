/**
 * Canonical intent labels used by the TinyBERT-CNN intent classifier.
 *
 * These must stay in sync with:
 *   - backend/apps/progress/models.py INTENT_CHOICES
 *   - ai_service/services/intent_service.py intent_names
 *
 * The backend is the source of truth for descriptions via
 * GET /api/progress/intent-choices/. This module provides a lightweight
 * frontend mirror for type safety and offline fallback.
 */

export const INTENT_LABELS = [
  'On-Topic Question',
  'Off-Topic Question',
  'Emotional-State',
  'Pace-Related',
  'Repeat/clarification',
  'Debugging/Code-Sharing',
] as const;

export type IntentName = (typeof INTENT_LABELS)[number];

export interface IntentOption {
  value: IntentName;
  label: string;
  description: string;
}

export const INTENT_OPTIONS: IntentOption[] = [
  {
    value: 'On-Topic Question',
    label: 'On-Topic Question',
    description:
      'Asking about the current material — explanations, examples, or conceptual questions without a specific broken code artifact.',
  },
  {
    value: 'Off-Topic Question',
    label: 'Off-Topic',
    description: 'Completely unrelated to the lesson or programming.',
  },
  {
    value: 'Emotional-State',
    label: 'Emotional State',
    description:
      'Expressing a feeling or internal state such as frustration, confusion, excitement, boredom, or anxiety.',
  },
  {
    value: 'Pace-Related',
    label: 'Pace-Related',
    description:
      'Wants to change speed — slow down, speed up, skip, take a break, or ask about timing.',
  },
  {
    value: 'Repeat/clarification',
    label: 'Repeat / Clarification',
    description:
      'Wants something repeated or explained again — signals like "again", "repeat", "missed", or "go back".',
  },
  {
    value: 'Debugging/Code-Sharing',
    label: 'Debugging / Code',
    description:
      'Sharing a broken code artifact, error message, traceback, or asking for debugging help.',
  },
];

export function isIntentName(value: string): value is IntentName {
  return (INTENT_LABELS as readonly string[]).includes(value);
}
