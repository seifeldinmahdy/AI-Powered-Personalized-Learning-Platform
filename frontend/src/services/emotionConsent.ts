/**
 * Emotion-capture consent (Batch 11b). Capture is OFF by default and requires
 * explicit, informed opt-in before the webcam is ever accessed. Revocable.
 */
import api from './api';

export interface EmotionConsentState {
  granted: boolean;
  granted_at: string | null;
  withdrawn_at: string | null;
  policy_version: string;
  required: boolean;
  current_policy_version: string;
  purged?: number | null;
}

export async function getEmotionConsent(): Promise<EmotionConsentState> {
  const { data } = await api.get<EmotionConsentState>('/progress/emotion-consent/');
  return data;
}

export async function grantEmotionConsent(policyVersion?: string): Promise<EmotionConsentState> {
  const { data } = await api.post<EmotionConsentState>('/progress/emotion-consent/grant/',
    policyVersion ? { policy_version: policyVersion } : {});
  return data;
}

export async function withdrawEmotionConsent(): Promise<EmotionConsentState> {
  const { data } = await api.post<EmotionConsentState>('/progress/emotion-consent/withdraw/', {});
  return data;
}
