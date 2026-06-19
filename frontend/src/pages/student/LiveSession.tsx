import { SlidesViewer } from '../../components/SlidesViewer';
import { GeneratedSlidesViewer } from '../../components/GeneratedSlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { TypewriterLoader } from '../../components/personifai/TypewriterLoader';
import { useParams, useNavigate } from 'react-router';
import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { getLesson, getModules, getLessons, type LessonDetail, type Lesson, type Module } from '../../services/lessons';
import api, { getEnrollments } from '../../services/api';
import {
  getSessionCompletions,
  createSessionCompletion,
} from '../../services/progress';
import { Loader2, Route, CheckCircle2, PlayCircle, Lock, Circle, Camera, CameraOff, X } from 'lucide-react';
import { toast } from 'sonner';

import {
  generateSlides,
  getCurrentPathway,
  getPersistedSlides,
  type PathwayPlan,
  type GeneratedSlide,
} from '../../services/pathway';

import { aiFetch } from '../../services/aiClient';
import { fuseEmotions } from '../../services/emotionFusion';
import { getEmotionConsent, grantEmotionConsent, withdrawEmotionConsent } from '../../services/emotionConsent';
import type { SERResult } from '../../services/tutor';
import { SessionCheckpoint } from '../../components/SessionCheckpoint';
import { generateSessionCheckpoint, type MCQQuestionData } from '../../services/assessments';

const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const SLIDE_LOADING_MESSAGES = [
  'Generating your personalized slides...',
  'Running content through AI models...',
  'Classifying visual elements...',
  'Extracting code examples...',
  'Building your slide deck...',
  'Almost ready...',
];

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

export default function LiveSession() {
  const { courseId, sessionNumber } = useParams();
  const lessonId = sessionNumber; // Legacy alias for backward compat during refactor
  const navigate = useNavigate();

  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [slides, setSlides] = useState<GeneratedSlide[]>([]);
  const [currentSlide, setCurrentSlide] = useState(0);
  // True while the tutor is narrating a chunk — slide navigation is locked so the
  // student can't skip ahead mid-sentence. The tutor's own auto-advance is
  // unaffected (it doesn't go through the nav buttons).
  const [isTutorSpeaking, setIsTutorSpeaking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [moduleTitle, setModuleTitle] = useState('');
  const [courseTitle, setCourseTitle] = useState('');
  const [isCompleting, setIsCompleting] = useState(false);
  const [plan, setPlan] = useState<PathwayPlan | null>(null);

  const sessionIdRef = useRef<string>(generateUUID());

  // Ordered list of all lessons in the course for prev/next navigation
  const [allLessons, setAllLessons] = useState<Lesson[]>([]);
  const [modules, setModules] = useState<Module[]>([]);
  const [completedLessonIds, setCompletedLessonIds] = useState<Set<number>>(new Set());
  const [maxAllowedSessionNumber, setMaxAllowedSessionNumber] = useState(1);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [expandedModules, setExpandedModules] = useState<Set<number>>(new Set());

  // ─── Emotion & FER state ──────────────────────────────────────
  const [fusedEmotion, setFusedEmotion] = useState<string | undefined>();
  const [cameraEnabled, setCameraEnabled] = useState(false);
  // Emotion-capture consent (Batch 11b): OFF by default, explicit opt-in.
  const [showConsentModal, setShowConsentModal] = useState(false);
  // ─── Student profile for Dr. Nova personalization ─────────────
  const [studentProfileSummary, setStudentProfileSummary] = useState<string | undefined>();

  // ─── In-session MCQ knowledge checkpoints ─────────────────────
  // Two per session: a MID check (2 questions per topic covered so far) at the
  // slide midpoint, and an END "Practice" check (1 question per session topic)
  // at completion. Segmentation is by slide source_topic (always present), not
  // admin concept_id — so the checkpoint always fires regardless of tagging.
  const [checkpoint, setCheckpoint] = useState<{
    kind: 'mid' | 'end';
    index: number;
    questions: MCQQuestionData[];
  } | null>(null);
  const [checkpointLoading, setCheckpointLoading] = useState(false);
  const [midDone, setMidDone] = useState(false);
  const [endDone, setEndDone] = useState(false);
  // Cache the session's raw chunks (fetched once, reused for both checkpoints).
  const sessionChunksRef = useRef<Array<{ raw_text: string; topic: string; concept_id?: string; page_start: number }> | null>(null);

  const lessonStartTimeRef = useRef<number>(Date.now());

  const webcamStreamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ferIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const latestSERRef = useRef<{ data: SERResult; timestamp: number } | null>(null);
  const sessionStartedRef = useRef(false);

  // ─── Fullscreen state ─────────────────────────────────────────
  const contentRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    function onFsChange() { setIsFullscreen(!!document.fullscreenElement); }
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!contentRef.current) return;
    if (!document.fullscreenElement) {
      contentRef.current.requestFullscreen().catch(() => { });
    } else {
      document.exitFullscreen().catch(() => { });
    }
  }, []);

  useEffect(() => {
    if (!sessionNumber) return;
    const sessionNum = Number(sessionNumber);
    if (isNaN(sessionNum)) {
      setError('Invalid session number');
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      try {
        setCurrentSlide(0);
        // Reset checkpoint state for the newly loaded session.
        setCheckpoint(null);
        setCheckpointLoading(false);
        setMidDone(false);
        setEndDone(false);
        sessionChunksRef.current = null;
        lessonStartTimeRef.current = Date.now();

        // ─── AI Slide Generation (with cache) ─────────────────
        // Read the CURRENT authoritative plan (single source of truth) — not a
        // sessionStorage copy. The slide cache is pinned to plan_version, so a
        // version bump makes stale slides structurally unreachable.
        let pathwayPlan: PathwayPlan | null = null;
        try {
          if (courseId) {
            pathwayPlan = await getCurrentPathway(String(courseId));
          }
        } catch {
          // No current plan yet — leave pathwayPlan null (handled below).
        }
        if (pathwayPlan) {
          if (!cancelled) setPlan(pathwayPlan);
          const currentSession = pathwayPlan.sessions.find(s => s.session_number === sessionNum);
          if (currentSession) {
            // Cache key pinned to plan_version (not just lessonId).
            const cacheKey = `slides_cache_${courseId}_v${pathwayPlan.plan_version}_${sessionNum}`;
            const cachedSlides = sessionStorage.getItem(cacheKey);
            if (cachedSlides) {
              try {
                const parsed = JSON.parse(cachedSlides);
                if (!cancelled && parsed.length > 0) {
                  setSlides(parsed);

                  // Re-initialize backend session context from cached slides
                  await aiFetch(`${AI_URL}/session/${sessionIdRef.current}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      current_slide_index: 0,
                      current_slide_title: parsed[0].title,
                      current_slide_content: parsed[0].body_content?.map((i: any) => i.text).join('\n') || '',
                      next_slide_title: parsed[1]?.title || '',
                      current_concept_id: parsed[0].concept_id || '',
                      current_topic: currentSession.session_title,
                      visited_slides_push: 0
                    })
                  }).catch(console.error);
                }
              } catch {
                sessionStorage.removeItem(cacheKey); // corrupted cache
              }
            }

            // On a local-cache miss, try the durably PERSISTED deck before
            // regenerating — this is the resume path (survives restart / works
            // on another device). Pinned to plan_version, so never stale.
            let loadedFromPersisted = false;
            if (!cachedSlides) {
              try {
                const persisted = await getPersistedSlides(
                  String(pathwayPlan.course_id), sessionNum, pathwayPlan.plan_version,
                );
                if (persisted && persisted.slides?.length > 0 && !cancelled) {
                  setSlides(persisted.slides);
                  try { sessionStorage.setItem(cacheKey, JSON.stringify(persisted.slides)); } catch { /* full */ }
                  await aiFetch(`${AI_URL}/session/${sessionIdRef.current}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      current_slide_index: 0,
                      current_slide_title: persisted.slides[0].title,
                      current_slide_content: persisted.slides[0].body_content?.map(i => i.text).join('\n') || '',
                      next_slide_title: persisted.slides[1]?.title || '',
                      current_concept_id: persisted.slides[0].concept_id || '',
                      current_topic: currentSession.session_title,
                      visited_slides_push: 0,
                    }),
                  }).catch(console.error);
                  loadedFromPersisted = true;
                }
              } catch { /* no persisted deck — fall through to generation */ }
            }

            // Only generate if we loaded from neither cache nor persisted store
            if (!cachedSlides && !loadedFromPersisted) {
              try {
                const chunksRes = await api.post('/ai/pathway/session-chunks/', {
                  course_id: pathwayPlan.course_id,
                  session_number: sessionNum,
                });

                {
                  const chunks = chunksRes.data;
                  if (chunks.length > 0) {
                    // Personalization (mastery / composition / language) is
                    // derived server-side from the student's stored context —
                    // we only identify the student here.
                    const slideResponse = await generateSlides({
                      session_number: sessionNum,
                      session_title: currentSession.session_title,
                      topics_covered: currentSession.topics_covered,
                      book: currentSession.book,
                      chunks: chunks.map((c: any) => ({
                        chunk_id: c.chunk_id,
                        raw_text: c.raw_text,
                        topic: c.topic,
                        // Forward the chunk's concept so the generator resolves
                        // per-concept mastery instead of falling back to global.
                        concept_id: c.concept_id || '',
                        page_start: c.page_start,
                        page_end: c.page_end,
                      })),
                      course_id: pathwayPlan.course_id,
                      plan_version: pathwayPlan.plan_version,
                    });

                    if (!cancelled) {
                      setSlides(slideResponse.slides);

                      // Cache the generated slides
                      try {
                        sessionStorage.setItem(cacheKey, JSON.stringify(slideResponse.slides));
                      } catch { /* storage full — non-critical */ }

                      // Initialize backend session context
                      if (slideResponse.slides.length > 0) {
                        await aiFetch(`${AI_URL}/session/${sessionIdRef.current}`, {
                          method: 'PATCH',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            current_slide_index: 0,
                            current_slide_title: slideResponse.slides[0].title,
                            current_slide_content: slideResponse.slides[0].body_content?.map(i => i.text).join('\n') || '',
                            next_slide_title: slideResponse.slides[1]?.title || '',
                            current_concept_id: slideResponse.slides[0].concept_id || '',
                            current_topic: currentSession.session_title,
                            visited_slides_push: 0
                          })
                        }).catch(console.error);
                      }
                    }
                  }
                }
              } catch (e) {
                console.error("Failed to generate AI slides", e);
              }
            }
          }
        }

        // Get course title + completions from enrollment
        try {
          const { data: raw } = await getEnrollments();
          const enrollments = Array.isArray(raw) ? raw : raw.results ?? [];
          const enrollment = enrollments.find(
            (e: { course: number; course_title: string }) =>
              String(e.course) === String(courseId),
          );
          if (enrollment) {
            setCourseTitle(enrollment.course_title);
            try {
              const completions = await getSessionCompletions(enrollment.id);
              const completedIds = new Set(
                completions
                  .filter((c) => c.status === 'Completed')
                  .map((c) => c.session_number as number)
              );
              if (!cancelled) {
                setCompletedLessonIds(completedIds);
                const maxCompleted = completedIds.size > 0 ? Math.max(...Array.from(completedIds)) : 0;
                setMaxAllowedSessionNumber(Math.max(enrollment.current_session_number || 1, maxCompleted + 1));
              }
            } catch {
              // non-critical
            }
          }
        } catch {
          // non-critical
        }

        // Load student learning profile for Dr. Nova personalization (B4)
        try {
          const token = localStorage.getItem('access_token');
          if (token) {
            const profileRes = await fetch(`${API_URL}/progress/learning-profile/`, {
              headers: { Authorization: `Bearer ${token}` },
            });
            if (profileRes.ok) {
              const profileData = await profileRes.json();
              if (profileData.profile_summary) {
                setStudentProfileSummary(profileData.profile_summary);
              }
            }
            // 404 = no profile yet — Dr. Nova starts fresh
          }
        } catch {
          // non-critical — Dr. Nova starts fresh
        }
      } catch {
        if (!cancelled) setError('Failed to load lesson data.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    // Backend now tracks sessions automatically via SharedSessionStore

    load();
    return () => { cancelled = true; };
  }, [lessonId, courseId]);

  // ─── Webcam & FER polling ─────────────────────────────────────

  const startFERPolling = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      webcamStreamRef.current = stream;

      // Attach to hidden video element
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => { });
      }

      // Poll every 25 seconds
      ferIntervalRef.current = setInterval(async () => {
        if (!videoRef.current || !canvasRef.current) return;

        const video = videoRef.current;
        const canvas = canvasRef.current;

        // Ensure video has dimensions
        if (video.videoWidth === 0 || video.videoHeight === 0) return;

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        ctx.drawImage(video, 0, 0);

        // Convert to JPEG blob
        const blob = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob(resolve, 'image/jpeg', 0.8)
        );
        if (!blob) return;

        try {
          // Send to FER — field name is "image" per fer.py
          const formData = new FormData();
          formData.append('image', blob, 'frame.jpg');
          const res = await fetch(`${AI_URL}/fer/predict`, {
            method: 'POST',
            body: formData,
          });
          if (!res.ok) return;
          const data = await res.json();

          if (!data.face_detected) return;

          // Fuse with latest SER result
          const ferData = { fer_emotion: data.emotion, fer_confidence: data.confidence };

          let serData = {};
          if (latestSERRef.current && Date.now() - latestSERRef.current.timestamp < 30000) {
            serData = {
              ser_emotion: latestSERRef.current.data.emotion,
              ser_confidence: latestSERRef.current.data.confidence
            };
          }

          const fusion = await fuseEmotions(
            { ...ferData, ...serData },
            {
              slide_index: currentSlide,
              subtopic: lesson?.title,
              session_id: sessionIdRef.current,
              course_id: String(courseId ?? ''),
            },
          );

          setFusedEmotion(fusion.fused_emotion);

          // Passive emotion events are now tracked implicitly by the backend via fuseEmotions -> profiler

        } catch {
          // FER/fusion errors are non-critical
        }
      }, 25_000);
    } catch {
      toast.error('Camera access denied. Emotion tracking disabled.');
      setCameraEnabled(false);
    }
  }, [lesson, currentSlide]);

  const stopFERPolling = useCallback(() => {
    if (ferIntervalRef.current) {
      clearInterval(ferIntervalRef.current);
      ferIntervalRef.current = null;
    }
    if (webcamStreamRef.current) {
      webcamStreamRef.current.getTracks().forEach((t) => t.stop());
      webcamStreamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  // Toggle camera on/off. Enabling requires explicit emotion-capture consent —
  // off by default; we never call getUserMedia without a prior opt-in.
  const handleCameraToggle = useCallback(async () => {
    if (cameraEnabled) {
      stopFERPolling();
      setCameraEnabled(false);
      return;
    }
    try {
      const consent = await getEmotionConsent();
      if (consent.granted) {
        setCameraEnabled(true);
        startFERPolling();
      } else {
        setShowConsentModal(true);  // ask for informed opt-in first
      }
    } catch {
      // Fail closed: if we can't confirm consent, don't capture.
      setShowConsentModal(true);
    }
  }, [cameraEnabled, startFERPolling, stopFERPolling]);

  const handleGrantConsent = useCallback(async () => {
    try {
      await grantEmotionConsent();
      setShowConsentModal(false);
      setCameraEnabled(true);
      startFERPolling();
    } catch {
      toast.error('Could not record consent. Please try again.');
    }
  }, [startFERPolling]);

  const handleWithdrawConsent = useCallback(async () => {
    stopFERPolling();
    setCameraEnabled(false);
    setShowConsentModal(false);
    try {
      await withdrawEmotionConsent();
      toast.success('Emotion tracking withdrawn and your emotion data deleted.');
    } catch {
      toast.error('Could not withdraw consent. Please try again.');
    }
  }, [stopFERPolling]);

  // Cleanup webcam on unmount
  useEffect(() => {
    return () => {
      stopFERPolling();
    };
  }, [stopFERPolling]);

  // ─── Session end: consolidate this session's learning profile ─
  // AWAITED at completion so the lab generated next reads the updated profile.

  const consolidateSessionProfile = useCallback(async () => {
    try {
      // The frontend NO LONGER reads/merges/overwrites the profile, and no longer
      // sends a student_id. It just asks the server (through Django, which sets the
      // verified identity) to consolidate this session's DURABLE event log. The
      // single server-side writer applies the resulting claims additively.
      await api.post('/ai/profiler/run-session/', {
        session_id: sessionIdRef.current,
        lesson_title: lesson?.title || plan?.sessions.find(s => s.session_number === 1)?.session_title || '',
      });
    } catch {
      // Fire-and-forget — entire block is non-blocking
      console.warn('[LiveSession] Profiler update failed (non-blocking)');
    }
  }, [lessonId, lesson, plan]);

  // ─── Navigation callbacks ─────────────────────────────────────

  // Current lesson index in the full ordered list
  const currentLessonIndex = (plan?.sessions?.findIndex(s => s.session_number === Number(sessionNumber)) ?? -1);
  const prevLesson = currentLessonIndex > 0 ? plan?.sessions[currentLessonIndex - 1] : null;
  const nextLesson = currentLessonIndex >= 0 && currentLessonIndex < (plan?.sessions?.length ?? 0) - 1
    ? plan?.sessions[currentLessonIndex + 1]
    : null;

  // ─── Knowledge-checkpoint segmentation (by slide source_topic) ────
  // Ordered unique topics across the AI slides — the spine the pathway itself
  // is built on, so it's always present even when admin concepts are sparse.
  const sessionTopics = (() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const s of slides) {
      const t = (s.source_topic || '').trim();
      if (t && !seen.has(t)) { seen.add(t); out.push(t); }
    }
    return out;
  })();

  // Fire the MID check on the last slide of the first half — but only when the
  // session is long enough and spans >1 topic (otherwise the END check alone).
  const midTriggerIndex =
    slides.length >= 4 && sessionTopics.length >= 2
      ? Math.floor(slides.length / 2) - 1
      : -1;

  // Topics covered up to (and including) a slide index.
  const topicsUpTo = (slideIdx: number): string[] => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (let i = 0; i <= slideIdx && i < slides.length; i++) {
      const t = (slides[i].source_topic || '').trim();
      if (t && !seen.has(t)) { seen.add(t); out.push(t); }
    }
    return out;
  };

  const midTopics = midTriggerIndex >= 0 ? topicsUpTo(midTriggerIndex) : [];
  const endTopics = sessionTopics;

  const currentSessionTitle =
    plan?.sessions.find((s) => s.session_number === Number(sessionNumber))?.session_title
    || courseTitle || 'Session';

  // Advance one slide forward (mirrors handleNextSlideOrLesson's slide step),
  // used to resume after a MID checkpoint closes.
  const advanceSlide = () => {
    const totalSlides = slides.length;
    if (currentSlide < totalSlides - 1) {
      const nextIdx = currentSlide + 1;
      setCurrentSlide(nextIdx);
      if (slides.length > 0) {
        fetch(`${AI_URL}/session/${sessionIdRef.current}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            current_slide_index: nextIdx,
            current_slide_title: slides[nextIdx].title,
            current_slide_content: slides[nextIdx].body_content?.map((i) => i.text).join('\n') || '',
            next_slide_title: slides[nextIdx + 1]?.title || '',
            current_concept_id: slides[nextIdx].concept_id || '',
            visited_slides_push: nextIdx,
          }),
        }).catch(console.error);
      }
    } else if (nextLesson) {
      navigate(`/course/${courseId}/session/${nextLesson.session_number}`);
    }
  };

  // Fetch (once) and cache this session's raw chunks for checkpoint generation.
  const loadSessionChunks = async () => {
    if (sessionChunksRef.current) return sessionChunksRef.current;
    const res = await api.post('/ai/pathway/session-chunks/', {
      course_id: String(courseId),
      session_number: Number(sessionNumber),
    });
    const chunks = Array.isArray(res.data) ? res.data : [];
    sessionChunksRef.current = chunks;
    return chunks;
  };

  // Pick ONE representative chunk per topic (earliest page) limited to topicSet.
  const repChunksForTopics = (
    chunks: Array<{ raw_text: string; topic: string; concept_id?: string; page_start: number }>,
    topicSet: string[],
  ) => {
    const wanted = new Set(topicSet.map((t) => t.trim().toLowerCase()));
    const best: Record<string, { raw_text: string; topic: string; concept_id?: string; page_start: number }> = {};
    for (const c of chunks) {
      const key = (c.topic || '').trim().toLowerCase();
      if (!wanted.has(key) || !c.raw_text) continue;
      if (!best[key] || c.page_start < best[key].page_start) best[key] = c;
    }
    // Preserve the topic order the student saw them in.
    return topicSet
      .map((t) => best[t.trim().toLowerCase()])
      .filter((c): c is NonNullable<typeof c> => Boolean(c))
      .map((c) => ({ text: c.raw_text, topic: c.topic, concept_id: c.concept_id || undefined }));
  };

  // Generate + open a knowledge checkpoint. On failure, mark it done and let the
  // caller proceed — a generation hiccup must never trap the student.
  const openCheckpoint = async (kind: 'mid' | 'end', onFailProceed: () => void) => {
    if (checkpointLoading) return;
    setCheckpointLoading(true);
    try {
      const chunks = await loadSessionChunks();
      const topics = kind === 'mid' ? midTopics : endTopics;
      const payloadChunks = repChunksForTopics(chunks, topics);
      if (payloadChunks.length === 0) { // nothing to test — skip silently
        if (kind === 'mid') setMidDone(true); else setEndDone(true);
        onFailProceed();
        return;
      }

      let mastery: 'Novice' | 'Intermediate' | 'Expert' = 'Intermediate';
      try {
        const ctx = await api.get(`/ai/student-context/${courseId}/`);
        const m = ctx.data?.profile?.mastery_level;
        if (m === 'Novice' || m === 'Intermediate' || m === 'Expert') mastery = m;
      } catch { /* default Intermediate */ }

      const studentId = String(plan?.student_id ?? '');
      const resp = await generateSessionCheckpoint({
        chunks: payloadChunks,
        course_id: String(courseId),
        student_id: studentId,
        session_topic: currentSessionTitle,
        session_number: Number(sessionNumber),
        checkpoint_index: kind === 'mid' ? 0 : 1,
        questions_per_chunk: kind === 'mid' ? 2 : 1, // 2 per topic mid, 1 per topic end
        context: {
          mastery_level: mastery,
          student_id: studentId,
          course_id: String(courseId),
        },
      });
      setCheckpoint({ kind, index: kind === 'mid' ? 0 : 1, questions: resp.questions });
    } catch (e) {
      console.error('[LiveSession] checkpoint generation failed', e);
      toast.error('Could not generate the knowledge check — continuing.');
      if (kind === 'mid') setMidDone(true); else setEndDone(true);
      onFailProceed();
    } finally {
      setCheckpointLoading(false);
    }
  };

  const handlePrevSlideOrLesson = () => {
    if (currentSlide > 0) {
      const nextIdx = currentSlide - 1;
      setCurrentSlide(nextIdx);
      // Sync backward navigation to backend session state
      if (slides.length > 0) {
        aiFetch(`${AI_URL}/session/${sessionIdRef.current}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            current_slide_index: nextIdx,
            current_slide_title: slides[nextIdx].title,
            current_slide_content: slides[nextIdx].body_content?.map((i) => i.text).join('\n') || '',
            next_slide_title: slides[nextIdx + 1]?.title || '',
            current_concept_id: slides[nextIdx].concept_id || '',
            visited_slides_push: nextIdx
          })
        }).catch(console.error);
      }
    } else if (prevLesson) {
      navigate(`/course/${courseId}/session/${prevLesson.session_number}`);
    }
  };

  const handleNextSlideOrLesson = () => {
    // MID knowledge checkpoint: about to leave the first-half boundary slide.
    if (!midDone && midTriggerIndex >= 0 && currentSlide === midTriggerIndex && midTopics.length > 0) {
      openCheckpoint('mid', advanceSlide);
      return;
    }
    const totalSlides = slides.length > 0 ? slides.length : 0;
    if (currentSlide < totalSlides - 1) {
      const nextIdx = currentSlide + 1;
      setCurrentSlide(nextIdx);
      // Sync forward navigation to backend session state
      if (slides.length > 0) {
        aiFetch(`${AI_URL}/session/${sessionIdRef.current}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            current_slide_index: nextIdx,
            current_slide_title: slides[nextIdx].title,
            current_slide_content: slides[nextIdx].body_content?.map((i) => i.text).join('\n') || '',
            next_slide_title: slides[nextIdx + 1]?.title || '',
            current_concept_id: slides[nextIdx].concept_id || '',
            visited_slides_push: nextIdx
          })
        }).catch(console.error);
      }
    } else if (nextLesson) {
      navigate(`/course/${courseId}/session/${nextLesson.session_number}`);
    }
  };

  const runComplete = useCallback(async () => {
    if (!courseId || !sessionNumber) return;
    setIsCompleting(true);
    stopFERPolling();

    // Consolidate this session's profile and AWAIT it, so the lab we navigate to
    // next is generated against the UPDATED learning profile (no stale-profile race).
    await consolidateSessionProfile();

    try {
      const { data: raw } = await getEnrollments();
      const enrollments = Array.isArray(raw) ? raw : raw.results ?? [];
      const enrollment = enrollments.find(
        (e: { course: number }) => String(e.course) === String(courseId),
      );
      if (!enrollment) {
        toast.error('You are not enrolled in this course.');
        return;
      }


      const timeSpentMinutes = Math.max(1, Math.round((Date.now() - lessonStartTimeRef.current) / 60000));

      const timeSpentMins = Math.max(1, Math.round((Date.now() - lessonStartTimeRef.current) / 60000));
      const score = 100; // Placeholder for session completion metric

      try {
        await createSessionCompletion(Number(courseId), {
          session_number: Number(sessionNumber),
          score: Math.round(score),
          time_spent_minutes: timeSpentMins,
        });
      } catch {
        toast.error('Failed to save completion status. Your progress might not be fully recorded.');
      }

      const compactSlides = slides.length > 0
        ? slides.map((slide) => ({
          title: slide.title,
          content: slide.body_content?.map((item) => item.text).join('\n') || '',
          code: slide.code_block?.code || '',
        }))
        : (lesson?.slides || []).map((slide, index) => ({
          title: String(slide.content_json?.title || `Slide ${index + 1}`),
          content: JSON.stringify(slide.content_json || {}),
          code: String((slide.content_json?.code as string | undefined) || ''),
        }));
      if (compactSlides.length > 0 && compactSlides.some(s => s.code)) {
        navigate(`/course/${courseId}/session/${sessionNumber}/lab`, {
          state: {
            sessionId: sessionIdRef.current,
            sessionTitle: plan?.sessions.find(s => s.session_number === Number(sessionNumber))?.session_title,
            studentProfileSummary,
            slides: compactSlides,
          }
        });
      } else {
        navigate(`/course/${courseId}/session/${sessionNumber}/problem-set`, {
          state: {
            sessionId: sessionIdRef.current,
            sessionTitle: plan?.sessions.find(s => s.session_number === Number(sessionNumber))?.session_title,
            studentProfileSummary,
            slides: compactSlides,
            nextSessionId: nextLesson ? nextLesson.session_number : undefined,
          }
        });
      }
      if (!nextLesson) {
        toast.success('Final session complete. Finish the lab and coding question to wrap up.');
      }
    } catch {
      toast.error('Failed to mark session as complete. Please try again.');
    } finally {
      setIsCompleting(false);
    }
  }, [lesson, courseId, navigate, nextLesson, consolidateSessionProfile, stopFERPolling, slides, studentProfileSummary, sessionNumber, plan]);

  // END "Practice" checkpoint intercepts completion: run it first, then finish.
  const handleComplete = () => {
    if (!endDone && endTopics.length > 0 && slides.length > 0) {
      openCheckpoint('end', runComplete);
      return;
    }
    void runComplete();
  };

  // Called when the checkpoint modal is dismissed (finished or skipped): mark it
  // done and resume the flow it interrupted (advance for MID, complete for END).
  const handleCheckpointClose = () => {
    const kind = checkpoint?.kind;
    setCheckpoint(null);
    if (kind === 'mid') { setMidDone(true); advanceSlide(); }
    else if (kind === 'end') { setEndDone(true); void runComplete(); }
  };

  // ─── Callbacks for CompactTutor ───────────────────────────────

  const handleSessionStart = useCallback(() => {
    sessionStartedRef.current = true;
  }, []);

  const handleLatestSER = useCallback((ser: SERResult) => {
    latestSERRef.current = { data: ser, timestamp: Date.now() };
  }, []);

  // ─── Render ───────────────────────────────────────────────────

  if (loading) {
    if (sessionStorage.getItem('pathway_plan')) {
      return (
        <TypewriterLoader
          variant="fixed"
          label="BUILDING YOUR SESSION"
          caption="Generating personalized materials"
          messages={SLIDE_LOADING_MESSAGES}
        />
      );
    }
    return (
      <div className="codex" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)' }}>
        <Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
      </div>
    );
  }

  if (error || (!lesson && slides.length === 0)) {
    return (
      <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14, background: 'var(--bg-primary)', textAlign: 'center', padding: 24 }}>
        <div className="t-label" style={{ color: 'var(--error-red)' }}>SESSION UNAVAILABLE</div>
        <p className="t-heading" style={{ fontSize: 22, color: 'var(--text-primary)' }}>{error || 'Lesson not found.'}</p>
        <button onClick={() => navigate('/dashboard')} className="btn btn-ghost-dark">← DASHBOARD</button>
      </div>
    );
  }

  const headerTitle = courseTitle ? `${courseTitle}: ${lesson?.title || 'Session'}` : (lesson?.title || 'Session');

  const totalSlides = slides.length > 0 ? slides.length : Math.max(lesson?.slides.length || 0, 1);
  const isLastSlideOfLastLesson = !nextLesson && currentSlide === totalSlides - 1;
  const currentSlideTitle = slides.length > 0
    ? slides[currentSlide]?.title
    : lesson?.slides?.[currentSlide]?.content_json?.title;

  // Extract subtopics from slide titles for tutor self-reprompting
  const subtopics = (slides.length > 0
    ? slides.map((s) => s.title)
    : (lesson?.slides.map((s) => (s.content_json?.title as string) || '') || []))
    .filter(Boolean);

  // Titles of the sessions BEFORE this one — lets Dr. Nova call back to prior
  // lessons ("as we saw last lesson…") instead of treating each lesson in isolation.
  const priorTopics = (plan?.sessions || [])
    .filter((s) => s.session_number < currentLessonIndex + 1)
    .sort((a, b) => a.session_number - b.session_number)
    .map((s) => s.session_title)
    .filter(Boolean);

  // ─── Course pathway for the left nav ──────────────────────────
  // Session N maps to the Nth lesson in course order; titles/topics come from
  // the authoritative plan.
  const pathwaySessions = plan?.sessions.map((ps, i) => {
    return {
      lessonId: String(ps.session_number),
      number: ps.session_number,
      title: ps.session_title,
      topics: ps.topics_covered ?? [],
      completed: completedLessonIds.has(ps.session_number),
    };
  }) || [];
  const totalSessions = pathwaySessions.length;
  const completedSessions = pathwaySessions.filter((s) => s.completed).length;
  const currentSessionNo = currentLessonIndex >= 0 ? currentLessonIndex + 1 : 1;
  const sessionProgressPct = totalSlides > 0 ? Math.round(((currentSlide + 1) / totalSlides) * 100) : 0;
  const pad2 = (n: number) => String(n).padStart(2, '0');

  return (
    <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg-primary)' }}>
      {/* Immersive session top bar (codex) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '0 24px', height: 52, borderBottom: '1px solid var(--hairline)', background: 'var(--bg-primary)', flexShrink: 0 }}>
        <button
          onClick={() => setDrawerOpen((o) => !o)}
          className="t-label"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'transparent', border: '1px solid var(--hairline)', borderRadius: 8, color: 'var(--text-secondary)', padding: '8px 12px', cursor: 'pointer' }}
        >
          <Route size={14} /> PATHWAY
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="t-label" style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{headerTitle}</div>
        </div>
        <button
          onClick={() => navigate(`/courses/${courseId}`)}
          className="t-label"
          style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
        >
          EXIT →
        </button>
      </div>

      {/* Slide-out Drawer — rendered into document.body via portal to escape overflow:hidden stacking context */}
      {drawerOpen && typeof document !== 'undefined' && createPortal(
        <div className="codex" style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'transparent' }}>
          {/* Backdrop */}
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)' }} onClick={() => setDrawerOpen(false)} />

          {/* Drawer panel — course pathway */}
          <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: 324, background: 'var(--bg-surface)', borderRight: '1px solid var(--hairline)', display: 'flex', flexDirection: 'column', boxShadow: '2px 0 24px rgba(0,0,0,0.12)' }}>
            {/* Drawer Header */}
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
              <span className="t-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: 'var(--accent-primary)' }}>
                <Route size={14} /> COURSE PATHWAY
              </span>
              <button onClick={() => setDrawerOpen(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex' }}><X size={16} /></button>
            </div>

            {/* Overall progress */}
            <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--hairline)', flexShrink: 0 }}>
              {courseTitle && <div className="t-mono steel" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{courseTitle.toUpperCase()}</div>}
              <div className="t-label" style={{ color: 'var(--text-primary)', marginTop: 6 }}>SESSION {pad2(currentSessionNo)} OF {pad2(Math.max(totalSessions, 1))}</div>
              <div className="progress" style={{ marginTop: 12 }}><i style={{ width: `${totalSessions > 0 ? Math.max(2, (completedSessions / totalSessions) * 100) : 2}%` }} /></div>
              <div className="t-mono" style={{ color: 'var(--accent-primary)', marginTop: 8 }}>{completedSessions} OF {totalSessions} COMPLETE</div>
            </div>

            {/* Pathway sessions */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
              {pathwaySessions.length === 0 ? (
                <div className="t-mono steel" style={{ padding: '24px 18px', textAlign: 'center' }}>NO SESSIONS YET</div>
              ) : (
                pathwaySessions.map((s, i) => {
                  const isCurrent = s.number === Number(sessionNumber);
                  const isLocked = s.number > maxAllowedSessionNumber;
                  const isCompleted = s.completed;
                  
                  // status colour: done → green, current → blue, prior-not-done → steel, upcoming/locked → faded steel
                  const accent = isCompleted ? 'var(--accent-success)'
                    : isCurrent ? 'var(--accent-primary)'
                      : isLocked ? 'var(--steel)' : 'var(--steel-light)';
                  const statusTag = isCompleted ? 'DONE' : isCurrent ? 'IN PROGRESS' : isLocked ? 'LOCKED' : 'REVISIT';
                  const titleColor = isCurrent ? 'var(--accent-primary)' : isLocked ? 'var(--text-secondary)' : 'var(--text-primary)';
                  
                  return (
                    <button
                      key={s.lessonId}
                      onClick={() => { 
                        if (isLocked) {
                          toast.error('Complete previous sessions to unlock this one.');
                          return;
                        }
                        navigate(`/course/${courseId}/session/${s.number}`); 
                        setDrawerOpen(false); 
                      }}
                      style={{
                        width: '100%', display: 'block', textAlign: 'left', cursor: isLocked ? 'not-allowed' : 'pointer',
                        padding: '12px 16px 12px 14px',
                        background: isCurrent ? 'rgba(37,99,235,0.06)' : 'transparent',
                        borderTop: 'none', borderRight: 'none', borderBottom: '1px solid var(--hairline)',
                        borderLeft: `3px solid ${isCurrent ? 'var(--accent-primary)' : isCompleted ? 'var(--accent-success)' : 'transparent'}`,
                        opacity: isLocked ? 0.6 : 1,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                        {isCompleted ? <CheckCircle2 size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />
                          : isCurrent ? <PlayCircle size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />
                            : isLocked ? <Lock size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />
                              : <Circle size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                            <span className="t-mono steel">SESSION {pad2(s.number)}</span>
                            <span className="t-mono" style={{ color: accent, fontSize: 9 }}>{statusTag}</span>
                          </div>
                          <div style={{ fontFamily: 'var(--ff-body)', fontSize: 13, lineHeight: 1.35, marginTop: 3, fontWeight: isCurrent ? 600 : 400, color: titleColor, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                            {s.title}
                          </div>

                          {/* Current session: live slide progress + topic being explained */}
                          {isCurrent && (
                            <div style={{ marginTop: 10 }}>
                              <div className="progress"><i style={{ width: `${Math.max(2, sessionProgressPct)}%` }} /></div>
                              <div className="t-mono" style={{ color: 'var(--accent-primary)', marginTop: 6 }}>
                                SLIDE {pad2(currentSlide + 1)} / {pad2(totalSlides)} · {sessionProgressPct}%
                              </div>
                              {Boolean(currentSlideTitle) && (
                                <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                                  <span className="sq-bullet" style={{ marginTop: 6, background: 'var(--accent-primary)' }} />
                                  <span className="t-body" style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                                    <span className="t-mono steel">NOW · </span>{String(currentSlideTitle)}
                                  </span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </div>,
        document.body!
      )}

      <div ref={contentRef} style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden', position: 'relative', background: 'var(--bg-primary)' }}>
        {/* Slides Viewer */}
        {slides.length > 0 ? (
          <GeneratedSlidesViewer
            slides={slides}
            currentIndex={currentSlide}
            sessionTitle={plan?.sessions.find((s) => s.session_number === currentLessonIndex + 1)?.session_title || 'AI Session'}
            onSlideChange={setCurrentSlide}
            navLocked={isTutorSpeaking}
            isFullscreen={isFullscreen}
            onFullscreenToggle={toggleFullscreen}
          />
        ) : (
          <SlidesViewer
            slides={lesson?.slides || []}
            currentIndex={currentSlide}
            lessonTitle={lesson?.title || ''}
            moduleLabel={moduleTitle}
            lessonId={lessonId ? Number(lessonId) : undefined}
            onSlideChange={setCurrentSlide}
            isFullscreen={isFullscreen}
            onFullscreenToggle={toggleFullscreen}
          />
        )}

        {/* AI Tutor */}
        <CompactTutor
          key={lessonId}
          lessonTitle={slides.length > 0 ? plan?.sessions.find((s) => s.session_number === currentLessonIndex + 1)?.session_title || 'AI Session' : lesson?.title || ''}
          lessonId={lessonId ? Number(lessonId) : undefined}
          courseId={courseId}
          sessionId={sessionIdRef.current}
          subtopics={subtopics}
          priorTopics={priorTopics}
          fusedEmotion={fusedEmotion}
          currentSlideIndex={currentSlide}
          currentSlideTitle={currentSlideTitle as string}
          currentSlideContent={slides.length > 0 ? slides[currentSlide]?.body_content?.map((i) => i.text).join('\n') : undefined}
          onSessionStart={handleSessionStart}
          onLatestSER={handleLatestSER}
          onUpdateFusedEmotion={setFusedEmotion}
          onNextSlide={handleNextSlideOrLesson}
          onSpeakingChange={setIsTutorSpeaking}
          studentProfileSummary={studentProfileSummary}
          isFloating={isFullscreen}
        />
      </div>

      {/* Bottom Controls */}
      <SessionControls
        currentSlide={currentSlide}
        totalSlides={totalSlides}
        onPrev={handlePrevSlideOrLesson}
        onNext={handleNextSlideOrLesson}
        navLocked={isTutorSpeaking}
        onComplete={handleComplete}
        isCompleting={isCompleting}
        hasPrevLesson={currentSlide === 0 && !!prevLesson}
        hasNextLesson={currentSlide === totalSlides - 1 && !!nextLesson}
        isLastLesson={isLastSlideOfLastLesson}
        nextLabelOverride={
          !midDone && midTriggerIndex >= 0 && currentSlide === midTriggerIndex && midTopics.length > 0
            ? 'GO TO KNOWLEDGE CHECK'
            : undefined
        }
        completeLabelOverride={
          !endDone && endTopics.length > 0 && slides.length > 0 ? 'PRACTICE' : undefined
        }
      />

      {/* Camera toggle button — small pill in bottom-right */}
      <button
        onClick={handleCameraToggle}
        className="t-label"
        style={{
          position: 'fixed', bottom: 80, right: 16, zIndex: 50,
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '8px 14px', borderRadius: 999, cursor: 'pointer',
          boxShadow: '0 4px 14px rgba(0,0,0,0.12)',
          background: cameraEnabled ? 'rgba(22,163,74,0.1)' : 'var(--bg-surface)',
          border: `1px solid ${cameraEnabled ? 'var(--accent-success)' : 'var(--hairline)'}`,
          color: cameraEnabled ? 'var(--accent-success)' : 'var(--text-secondary)',
        }}
        title={cameraEnabled ? 'Disable emotion tracking' : 'Enable emotion tracking (camera)'}
      >
        {cameraEnabled ? <Camera size={14} /> : <CameraOff size={14} />}
        <span>{cameraEnabled ? 'TRACKING ON' : 'TRACKING OFF'}</span>
      </button>

      {/* Knowledge-checkpoint generation overlay — blurs the lesson while the
          MCQs are being generated, before the modal itself opens. */}
      {checkpointLoading && !checkpoint && (
        <div
          className="codex"
          style={{
            position: 'fixed', inset: 0, zIndex: 10000, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 16, padding: 20,
            background: 'rgba(19,16,13,0.55)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)',
          }}
        >
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
          <div className="t-label" style={{ color: 'var(--bg-paper)' }}>BUILDING YOUR KNOWLEDGE CHECK…</div>
        </div>
      )}

      {/* In-session MCQ knowledge checkpoint (pop-up, blurs + blocks the lesson). */}
      {checkpoint && (
        <SessionCheckpoint
          questions={checkpoint.questions}
          kind={checkpoint.kind}
          checkpointIndex={checkpoint.index}
          courseId={String(courseId)}
          studentId={String(plan?.student_id ?? '')}
          sessionNumber={Number(sessionNumber)}
          onClose={handleCheckpointClose}
        />
      )}

      {/* Emotion-capture consent modal (Batch 11b) — informed opt-in before any
          webcam access. Off by default; revocable. (Styling intentionally minimal.) */}
      {showConsentModal && (
        <div className="codex" style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', padding: 16 }}>
          <div style={{ maxWidth: 460, width: '100%', background: 'var(--bg-surface)', border: '1px solid var(--hairline)', borderRadius: 12, padding: 28 }}>
            <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 10 }}>EMOTION-AWARE TUTORING</div>
            <h2 className="t-heading" style={{ fontSize: 22, color: 'var(--text-primary)', marginBottom: 14 }}>Enable emotion-aware tutoring?</h2>
            <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 14 }}>
              With your permission, the tutor can use your webcam to read
              facial-expression-derived <strong style={{ color: 'var(--text-primary)' }}>emotion labels</strong> (e.g. “engaged”,
              “confused”) about every 25 seconds, to adapt how it explains things.
            </p>
            <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 22 }}>
              <li className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'flex', gap: 8 }}><span className="sq-bullet" style={{ marginTop: 7 }} /><span><strong style={{ color: 'var(--text-primary)' }}>No video or images are stored</strong> — only short-lived emotion labels.</span></li>
              <li className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'flex', gap: 8 }}><span className="sq-bullet" style={{ marginTop: 7 }} /><span>Used <strong style={{ color: 'var(--text-primary)' }}>only</strong> to adapt tutor delivery. It <strong style={{ color: 'var(--text-primary)' }}>never affects your grades</strong>, scores, mastery, or certificate.</span></li>
              <li className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'flex', gap: 8 }}><span className="sq-bullet" style={{ marginTop: 7 }} /><span>Raw signals are deleted after the session; you can withdraw anytime (which deletes your emotion data).</span></li>
            </ul>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button onClick={() => setShowConsentModal(false)} className="btn btn-ghost-dark" style={{ padding: '10px 16px' }}>NOT NOW</button>
              <button onClick={handleWithdrawConsent} className="btn btn-ghost-dark" style={{ padding: '10px 16px', color: 'var(--text-secondary)' }}>WITHDRAW &amp; DELETE</button>
              <button onClick={handleGrantConsent} className="btn btn-red" style={{ padding: '10px 16px' }}>I CONSENT</button>
            </div>
          </div>
        </div>
      )}

      {/* Hidden video and canvas for FER capture */}
      <video ref={videoRef} style={{ display: 'none' }} playsInline muted />
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}
