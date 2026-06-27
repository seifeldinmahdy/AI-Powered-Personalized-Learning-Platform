import { SlidesViewer } from '../../components/SlidesViewer';
import { GeneratedSlidesViewer } from '../../components/GeneratedSlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { PathwayDrawer } from '../../components/PathwayDrawer';
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
import { Route, CheckCircle2, PlayCircle, Lock, Circle, Camera, CameraOff, X } from 'lucide-react';
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

const CHECKPOINT_LOADING_MESSAGES = [
  'Building your knowledge check...',
  'Picking questions at your level...',
  'Calibrating difficulty to your mastery...',
  'Almost ready...',
];

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

// Where to resume the deck: the last slide the student was on, per
// course+session+plan version (so a regenerated deck doesn't restore a stale
// index). Stored locally so it survives closing the tab / a different day.
const lastSlideKey = (courseId: string | number, sessionNum: number, planVersion: number) =>
  `learnpal:lastSlide:${courseId}:${sessionNum}:v${planVersion}`;

export default function LiveSession() {
  const { courseId, sessionNumber } = useParams();
  const lessonId = sessionNumber; // Legacy alias for backward compat during refactor
  const navigate = useNavigate();

  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [slides, setSlides] = useState<GeneratedSlide[]>([]);
  const [currentSlide, setCurrentSlide] = useState(0);
  // Resume support: where to jump to once the deck loads, and a gate so we don't
  // persist the transient slide-0 reset before the restore has run.
  const resumeSlideRef = useRef<number | null>(null);
  const restoreCompleteRef = useRef(false);
  // True while the tutor is narrating a chunk — slide navigation is locked so the
  // student can't skip ahead mid-sentence. The tutor's own auto-advance is
  // unaffected (it doesn't go through the nav buttons).
  const [isTutorSpeaking, setIsTutorSpeaking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // Set when the student opened a session they haven't unlocked yet (sequential
  // access). Drives a dedicated "Session locked" screen instead of generating.
  const [locked, setLocked] = useState<{ requested: number; allowed: number } | null>(null);
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
  const [expandedModules, setExpandedModules] = useState<Set<number>>(new Set());

  // ─── Emotion & FER state ──────────────────────────────────────
  const [fusedEmotion, setFusedEmotion] = useState<string | undefined>();
  const [cameraEnabled, setCameraEnabled] = useState(false);
  // Emotion-capture consent (Batch 11b): OFF by default, explicit opt-in.
  const [showConsentModal, setShowConsentModal] = useState(false);
  // ─── Student profile for LearnPal personalization ─────────────
  const [studentProfileSummary, setStudentProfileSummary] = useState<string | undefined>();

  // ─── In-session MCQ knowledge checkpoints ─────────────────────
  // Checkpoints are CONCEPT-BOUNDARY-driven, not positional: the deck is split
  // into concept segments (consecutive slides sharing concept_id, falling back
  // to source_topic when tagging is sparse). The student gets a "Knowledge
  // Check" after finishing each concept's slides, then a final "Practice" that
  // covers EVERY concept in the lecture at completion. Generation runs in the
  // BACKGROUND while the student reads (prefetch), so a checkpoint opens
  // instantly instead of blocking. Nothing fires until the session is started.
  const [checkpoint, setCheckpoint] = useState<{
    kind: 'mid' | 'end';
    key: string;            // 'seg-<i>' for a concept check, 'end' for the final
    checkpointIndex: number;
    questions: MCQQuestionData[];
  } | null>(null);
  const [checkpointLoading, setCheckpointLoading] = useState(false);
  // Which checkpoints have already been shown (keyed by 'seg-<i>' | 'end').
  const [doneCheckpoints, setDoneCheckpoints] = useState<Set<string>>(new Set());
  // Gate: no checkpoint (and no prefetch) until the student STARTS the session
  // (LearnPal's lecture begins). Opening a session without starting it must not
  // surface the final-MCQ button or trigger any generation, and leaves the deck
  // freely navigable (arrows/dots/next all work, no checks).
  const [sessionStarted, setSessionStarted] = useState(false);
  // Furthest slide the student has reached. Once the session is started, the
  // strip dots can only jump within what's been reached, so a forward jump can't
  // skip a concept's slides (and its check). Free-roam before start.
  const [maxSlideReached, setMaxSlideReached] = useState(0);
  // Prefetched checkpoint questions, keyed by checkpoint key — generation runs
  // in the background as the student reads so hitting a checkpoint is instant.
  const preparedRef = useRef<Map<string, {
    status: 'loading' | 'ready' | 'error';
    questions?: MCQQuestionData[];
    promise?: Promise<MCQQuestionData[]>;
  }>>(new Map());
  // Cache the session's raw chunks (fetched once, reused for every checkpoint).
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

  // ─── Resizable tutor panel ────────────────────────────────────
  // The docked tutor has a draggable left edge; the slides area is flex:1 so it
  // reflows automatically as the panel grows/shrinks. Width is clamped and
  // remembered across sessions.
  const TUTOR_MIN_W = 300;
  const TUTOR_MAX_W = 720;
  const [tutorWidth, setTutorWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem('tutor_panel_width'));
    return saved >= TUTOR_MIN_W && saved <= TUTOR_MAX_W ? saved : 320;
  });
  useEffect(() => {
    try { localStorage.setItem('tutor_panel_width', String(tutorWidth)); } catch { /* full */ }
  }, [tutorWidth]);

  const startTutorResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    const onMove = (ev: PointerEvent) => {
      if (!contentRef.current) return;
      const rect = contentRef.current.getBoundingClientRect();
      const next = Math.max(TUTOR_MIN_W, Math.min(TUTOR_MAX_W, rect.right - ev.clientX));
      setTutorWidth(next);
    };
    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
  }, []);

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
        // Hold off persisting the slide index until we've restored the saved one.
        restoreCompleteRef.current = false;
        resumeSlideRef.current = null;
        // Reset checkpoint state for the newly loaded session.
        setCheckpoint(null);
        setCheckpointLoading(false);
        setLocked(null);
        setDoneCheckpoints(new Set());
        setSessionStarted(false);
        sessionStartedRef.current = false;
        setMaxSlideReached(0);
        preparedRef.current.clear();
        sessionChunksRef.current = null;
        lessonStartTimeRef.current = Date.now();

        // ─── Access guard (sequential unlock) ─────────────────
        // A session is locked until the one before it is complete. The browser
        // can still point at any /session/<n> URL, so verify BEFORE generating
        // anything and bounce the student to their furthest-allowed session.
        // The Django proxy enforces the same rule server-side (the real lock);
        // this is the friendly redirect so they never hit a raw 403.
        try {
          const { data: rawEnr } = await getEnrollments();
          const enrs = Array.isArray(rawEnr) ? rawEnr : rawEnr.results ?? [];
          const enr = enrs.find((e: { course: number }) => String(e.course) === String(courseId));
          if (enr) {
            let allowed = enr.current_session_number || 1;
            try {
              const comps = await getSessionCompletions(enr.id);
              const done = comps
                .filter((c) => c.status === 'Completed')
                .map((c) => c.session_number as number);
              if (done.length) allowed = Math.max(allowed, Math.max(...done) + 1);
            } catch { /* fall back to current_session_number */ }
            if (sessionNum > allowed && !cancelled) {
              setLocked({ requested: sessionNum, allowed });
              return;
            }
          }
        } catch { /* can't verify enrollment — let the server-side gate handle it */ }

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
          // Look up where the student left off (applied once the deck loads).
          try {
            const saved = localStorage.getItem(lastSlideKey(courseId!, sessionNum, pathwayPlan.plan_version));
            resumeSlideRef.current = saved != null ? Number(saved) : null;
          } catch { resumeSlideRef.current = null; }
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

        // Load student learning profile for LearnPal personalization (B4)
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
            // 404 = no profile yet — LearnPal starts fresh
          }
        } catch {
          // non-critical — LearnPal starts fresh
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

  // ─── Knowledge-checkpoint segmentation (by concept boundary) ──────
  // Split the deck into CONCEPT SEGMENTS: runs of consecutive slides sharing a
  // concept (concept_id when tagged, else the source_topic so it still works
  // when admin concepts are sparse). Title/agenda/summary slides carry no
  // source_topic and are skipped. The student gets a check after each concept's
  // slides; the final check covers every topic.
  type CheckpointSegment = {
    index: number;     // 0-based order among concept segments
    conceptKey: string;
    startIdx: number;
    endIdx: number;    // last slide index belonging to this segment
    topics: string[];  // distinct source_topics seen in this segment
  };
  const segments: CheckpointSegment[] = (() => {
    const segs: CheckpointSegment[] = [];
    let cur: CheckpointSegment | null = null;
    for (let i = 0; i < slides.length; i++) {
      const topic = (slides[i].source_topic || '').trim();
      if (!topic) continue; // skip non-content slides (title/agenda/summary)
      const key = String((slides[i].concept_id || '').trim() || topic.toLowerCase());
      if (cur && cur.conceptKey === key) {
        cur.endIdx = i;
        if (!cur.topics.includes(topic)) cur.topics.push(topic);
      } else {
        if (cur) segs.push(cur);
        cur = { index: segs.length, conceptKey: key, startIdx: i, endIdx: i, topics: [topic] };
      }
    }
    if (cur) segs.push(cur);
    return segs;
  })();

  // Ordered unique topics across the whole deck — the final check covers these.
  const sessionTopics = (() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const s of slides) {
      const t = (s.source_topic || '').trim();
      if (t && !seen.has(t)) { seen.add(t); out.push(t); }
    }
    return out;
  })();
  const endTopics = sessionTopics;

  // The concept segment whose LAST slide we're sitting on (if any) — i.e. the
  // student just finished this concept. The final segment is intentionally
  // excluded: it is covered by the end-of-session "Practice" check instead.
  const segmentEndingAt = (slideIdx: number): CheckpointSegment | null =>
    segments.find((s) => s.endIdx === slideIdx && s.index < segments.length - 1) || null;

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

  // Resolve the student's coarse mastery (cached for the session) for difficulty.
  const masteryRef = useRef<'Novice' | 'Intermediate' | 'Expert' | null>(null);
  const resolveMastery = async (): Promise<'Novice' | 'Intermediate' | 'Expert'> => {
    if (masteryRef.current) return masteryRef.current;
    let mastery: 'Novice' | 'Intermediate' | 'Expert' = 'Intermediate';
    try {
      const ctx = await api.get(`/ai/student-context/${courseId}/`);
      const m = ctx.data?.profile?.mastery_level;
      if (m === 'Novice' || m === 'Intermediate' || m === 'Expert') mastery = m;
    } catch { /* default Intermediate */ }
    masteryRef.current = mastery;
    return mastery;
  };

  // Kick off (or reuse) BACKGROUND generation of one checkpoint's MCQs. Idempotent
  // per key — calling it repeatedly while the student reads is cheap. Returns the
  // questions promise so a trigger can await an in-flight prefetch if needed.
  const prepareCheckpoint = (
    key: string,
    topics: string[],
    questionsPerChunk: number,
    checkpointIndex: number,
  ): Promise<MCQQuestionData[]> => {
    const existing = preparedRef.current.get(key);
    if (existing && existing.status !== 'error') {
      return existing.promise ?? Promise.resolve(existing.questions ?? []);
    }
    const promise = (async () => {
      const chunks = await loadSessionChunks();
      const payloadChunks = repChunksForTopics(chunks, topics);
      if (payloadChunks.length === 0) {
        preparedRef.current.set(key, { status: 'ready', questions: [] });
        return [];
      }
      const mastery = await resolveMastery();
      const studentId = String(plan?.student_id ?? '');
      const resp = await generateSessionCheckpoint({
        chunks: payloadChunks,
        course_id: String(courseId),
        student_id: studentId,
        session_topic: currentSessionTitle,
        session_number: Number(sessionNumber),
        checkpoint_index: checkpointIndex,
        questions_per_chunk: questionsPerChunk,
        context: { mastery_level: mastery, student_id: studentId, course_id: String(courseId) },
      });
      preparedRef.current.set(key, { status: 'ready', questions: resp.questions });
      return resp.questions;
    })();
    preparedRef.current.set(key, { status: 'loading', promise });
    promise.catch((e) => {
      console.error('[LiveSession] checkpoint prefetch failed', e);
      preparedRef.current.set(key, { status: 'error' });
    });
    return promise;
  };

  // Open a checkpoint: use the prefetched questions if ready, otherwise show the
  // loader and await the in-flight (or freshly started) generation. On failure or
  // an empty quiz, mark it done and let the caller proceed — a generation hiccup
  // must never trap the student.
  const openCheckpoint = async (
    kind: 'mid' | 'end',
    key: string,
    checkpointIndex: number,
    topics: string[],
    questionsPerChunk: number,
    onFailProceed: () => void,
  ) => {
    if (checkpoint || checkpointLoading) return;
    const markDone = () => setDoneCheckpoints((prev) => new Set(prev).add(key));

    const prep = preparedRef.current.get(key);
    let questions: MCQQuestionData[];
    if (prep?.status === 'ready') {
      questions = prep.questions ?? [];
    } else {
      setCheckpointLoading(true);
      try {
        questions = await prepareCheckpoint(key, topics, questionsPerChunk, checkpointIndex);
      } catch {
        toast.error('Could not generate the knowledge check — continuing.');
        markDone();
        setCheckpointLoading(false);
        onFailProceed();
        return;
      }
      setCheckpointLoading(false);
    }

    if (!questions || questions.length === 0) { // nothing to test — skip silently
      markDone();
      onFailProceed();
      return;
    }
    setCheckpoint({ kind, key, checkpointIndex, questions });
  };

  // ─── Background checkpoint prefetch ───────────────────────────────
  // As the student reads, pre-generate the concept check they'll hit when they
  // finish the concept they're currently in, and — once they reach the last
  // concept — the final "Practice". Generation uses the local QG/DG models and
  // is slow, so doing it ahead of time makes the checkpoint open instantly
  // instead of blocking. Idempotent per key; gated on the session being started.
  useEffect(() => {
    if (!sessionStarted || slides.length === 0 || segments.length === 0) return;
    const here = segments.find((s) => currentSlide >= s.startIdx && currentSlide <= s.endIdx);
    if (here && here.index < segments.length - 1) {
      const key = `seg-${here.index}`;
      if (!doneCheckpoints.has(key)) prepareCheckpoint(key, here.topics, 2, here.index);
    }
    const last = segments[segments.length - 1];
    if (last && currentSlide >= last.startIdx && !doneCheckpoints.has('end') && endTopics.length > 0) {
      prepareCheckpoint('end', endTopics, 1, segments.length);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSlide, sessionStarted, slides.length]);

  // Track the furthest slide reached (drives how far the strip dots can jump).
  useEffect(() => {
    setMaxSlideReached((m) => Math.max(m, currentSlide));
  }, [currentSlide]);

  // Resume: once the deck is loaded, jump to where the student left off.
  useEffect(() => {
    if (slides.length === 0 || restoreCompleteRef.current) return;
    const target = resumeSlideRef.current;
    if (target != null) {
      const clamped = Math.min(Math.max(0, target), slides.length - 1);
      if (clamped > 0) {
        setCurrentSlide(clamped);
        setMaxSlideReached((m) => Math.max(m, clamped));
      }
    }
    resumeSlideRef.current = null;
    restoreCompleteRef.current = true;  // saving is now safe
  }, [slides]);

  // Persist the current slide so the session resumes here next time.
  useEffect(() => {
    if (!restoreCompleteRef.current || slides.length === 0) return;
    if (!courseId || !sessionNumber || plan?.plan_version == null) return;
    try {
      localStorage.setItem(lastSlideKey(courseId, Number(sessionNumber), plan.plan_version), String(currentSlide));
    } catch { /* storage full / unavailable — non-critical */ }
  }, [currentSlide, slides.length, courseId, sessionNumber, plan]);

  // Sync an arbitrary slide index to the backend (used by the strip-dot jumps).
  const syncSlideToBackend = (idx: number) => {
    if (slides.length === 0 || !slides[idx]) return;
    aiFetch(`${AI_URL}/session/${sessionIdRef.current}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_slide_index: idx,
        current_slide_title: slides[idx].title,
        current_slide_content: slides[idx].body_content?.map((i) => i.text).join('\n') || '',
        next_slide_title: slides[idx + 1]?.title || '',
        current_concept_id: slides[idx].concept_id || '',
        visited_slides_push: idx,
      }),
    }).catch(console.error);
  };

  // Strip-dot jump. Once started, refuse to jump PAST the furthest reached slide
  // (that would skip a concept's slides + its check); free-roam before start.
  const handleJumpToSlide = (idx: number) => {
    if (idx === currentSlide) return;
    if (sessionStarted && idx > maxSlideReached) return;
    setCurrentSlide(idx);
    syncSlideToBackend(idx);
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
    // CONCEPT checkpoint: about to leave the last slide of a concept segment —
    // test that concept before moving on (only once the session is started).
    if (sessionStarted) {
      const seg = segmentEndingAt(currentSlide);
      if (seg && !doneCheckpoints.has(`seg-${seg.index}`) && seg.topics.length > 0) {
        openCheckpoint('mid', `seg-${seg.index}`, seg.index, seg.topics, 2, advanceSlide);
        return;
      }
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
      // On the last slide of a STARTED session, advancing must not silently jump
      // to the next session and skip the final check + completion pipeline (lab,
      // problem set, profiler). Route through completion instead; the pipeline
      // ultimately lands the student in the next session. Unstarted → free jump.
      if (sessionStarted) { handleComplete(); return; }
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
      const sessionTitle = plan?.sessions.find(s => s.session_number === Number(sessionNumber))?.session_title;
      const nextLessonId = nextLesson ? nextLesson.session_number : null;
      // The session flow always runs the coding lab first, which then hands off to
      // the problem set (and on to the next session). Carry nextLessonId through so
      // that chain can complete. Only a session with no slide content at all skips
      // straight to the problem set.
      if (compactSlides.length > 0) {
        navigate(`/course/${courseId}/session/${sessionNumber}/lab`, {
          state: {
            sessionId: sessionIdRef.current,
            courseId: String(courseId),
            sessionTitle,
            lessonTitle: sessionTitle,
            studentProfileSummary,
            slides: compactSlides,
            nextLessonId,
          }
        });
      } else {
        navigate(`/course/${courseId}/session/${sessionNumber}/problem-set`, {
          state: {
            sessionId: sessionIdRef.current,
            sessionTitle,
            studentProfileSummary,
            slides: compactSlides,
            nextSessionId: nextLessonId ?? undefined,
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

  // Final "Practice" checkpoint (covers EVERY concept) intercepts completion —
  // but only when the session was actually started; opening a session and
  // hitting complete without starting it must not surface the final MCQ.
  const handleComplete = () => {
    if (sessionStarted && !doneCheckpoints.has('end') && endTopics.length > 0 && slides.length > 0) {
      openCheckpoint('end', 'end', segments.length, endTopics, 1, runComplete);
      return;
    }
    void runComplete();
  };

  // Called when the checkpoint modal is dismissed (finished or skipped): mark it
  // done and resume the flow it interrupted (advance for a concept check,
  // complete for the final check).
  const handleCheckpointClose = () => {
    const closed = checkpoint;
    setCheckpoint(null);
    if (!closed) return;
    setDoneCheckpoints((prev) => new Set(prev).add(closed.key));
    if (closed.kind === 'end') { void runComplete(); }
    else { advanceSlide(); }
  };

  // ─── Callbacks for CompactTutor ───────────────────────────────

  const handleSessionStart = useCallback(() => {
    sessionStartedRef.current = true;
    setSessionStarted(true);
  }, []);

  const handleLatestSER = useCallback((ser: SERResult) => {
    latestSERRef.current = { data: ser, timestamp: Date.now() };
  }, []);

  // ─── Render ───────────────────────────────────────────────────

  if (locked) {
    return (
      <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14, background: 'var(--bg-primary)', textAlign: 'center', padding: 24 }}>
        <div style={{ width: 56, height: 56, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-surface)', border: '1px solid var(--hairline)' }}>
          <Lock size={24} style={{ color: 'var(--accent-warm)' }} />
        </div>
        <div className="t-label" style={{ color: 'var(--accent-warm)' }}>SESSION LOCKED</div>
        <p className="t-heading" style={{ fontSize: 22, color: 'var(--text-primary)' }}>
          Session {locked.requested} isn’t available yet
        </p>
        <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', maxWidth: 440, lineHeight: 1.5 }}>
          Sessions unlock in order — finish the earlier ones first. You’re currently on
          {' '}Session {locked.allowed}.
        </p>
        <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
          <button
            onClick={() => navigate(`/course/${courseId}/session/${locked.allowed}`, { replace: true })}
            className="btn btn-primary"
            style={{ padding: '12px 22px' }}
          >
            GO TO SESSION {locked.allowed} →
          </button>
          <button onClick={() => navigate(`/course/${courseId}/pathway`)} className="btn btn-ghost-dark" style={{ padding: '12px 18px' }}>
            ← BACK TO PATHWAY
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <TypewriterLoader
        variant="fixed"
        label="BUILDING YOUR SESSION"
        caption="Generating personalized materials"
        messages={SLIDE_LOADING_MESSAGES}
      />
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

  // Titles of the sessions BEFORE this one — lets LearnPal call back to prior
  // lessons ("as we saw last lesson…") instead of treating each lesson in isolation.
  const priorTopics = (plan?.sessions || [])
    .filter((s) => s.session_number < currentLessonIndex + 1)
    .sort((a, b) => a.session_number - b.session_number)
    .map((s) => s.session_title)
    .filter(Boolean);

  // The course pathway nav now lives in <PathwayDrawer> (shared with the lab &
  // problem set); it fetches the plan + completions itself.

  return (
    <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg-primary)' }}>
      {/* Immersive session top bar (codex) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '0 24px', height: 52, borderBottom: '1px solid var(--hairline)', background: 'var(--bg-primary)', flexShrink: 0 }}>
        <PathwayDrawer
          courseId={String(courseId)}
          currentSessionNumber={Number(sessionNumber)}
          activeStage="slides"
          slideProgress={{ current: currentSlide, total: totalSlides, nowTitle: currentSlideTitle as string | undefined }}
        />
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

      <div ref={contentRef} style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden', position: 'relative', background: 'var(--bg-primary)' }}>
        {/* Slides Viewer */}
        {slides.length > 0 ? (
          <GeneratedSlidesViewer
            slides={slides}
            currentIndex={currentSlide}
            sessionTitle={plan?.sessions.find((s) => s.session_number === currentLessonIndex + 1)?.session_title || 'AI Session'}
            onSlideChange={handleJumpToSlide}
            onRequestNext={handleNextSlideOrLesson}
            onRequestPrev={handlePrevSlideOrLesson}
            maxReachableIndex={sessionStarted ? maxSlideReached : undefined}
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

        {/* Drag handle to resize the tutor panel (docked mode only — in
            fullscreen the tutor floats). The slides area is flex:1, so it
            reflows as the panel resizes. */}
        {!isFullscreen && (
          <div
            onPointerDown={startTutorResize}
            role="separator"
            aria-orientation="vertical"
            title="Drag to resize the tutor panel"
            style={{
              flexShrink: 0,
              width: 8,
              cursor: 'col-resize',
              background: 'var(--hairline)',
              borderLeft: '1px solid var(--bg-primary)',
              borderRight: '1px solid var(--bg-primary)',
              touchAction: 'none',
            }}
          />
        )}

        {/* AI Tutor */}
        <CompactTutor
          key={lessonId}
          dockedWidth={tutorWidth}
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
        // Once started, the last slide's forward exit is Complete (which runs the
        // final check + completion pipeline), so we don't offer a "NEXT LESSON →"
        // that would bypass it. Unstarted sessions keep the direct jump.
        hasNextLesson={currentSlide === totalSlides - 1 && !!nextLesson && !sessionStarted}
        isLastLesson={isLastSlideOfLastLesson}
        nextLabelOverride={
          sessionStarted && (() => {
            const seg = segmentEndingAt(currentSlide);
            return seg && !doneCheckpoints.has(`seg-${seg.index}`) && seg.topics.length > 0;
          })()
            ? 'GO TO KNOWLEDGE CHECK'
            : undefined
        }
        completeLabelOverride={
          sessionStarted && !doneCheckpoints.has('end') && endTopics.length > 0 && slides.length > 0
            ? 'PRACTICE'
            : undefined
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
        <TypewriterLoader
          variant="fixed"
          label="KNOWLEDGE CHECK"
          caption="A few quick questions to lock in what you've learned"
          messages={CHECKPOINT_LOADING_MESSAGES}
        />
      )}

      {/* In-session MCQ knowledge checkpoint (pop-up, blurs + blocks the lesson). */}
      {checkpoint && (
        <SessionCheckpoint
          questions={checkpoint.questions}
          kind={checkpoint.kind}
          checkpointIndex={checkpoint.checkpointIndex}
          courseId={String(courseId)}
          studentId={String(plan?.student_id ?? '')}
          sessionNumber={Number(sessionNumber)}
          sessionId={sessionIdRef.current}
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
