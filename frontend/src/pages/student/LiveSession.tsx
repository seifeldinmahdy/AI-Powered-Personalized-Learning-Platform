import { Header } from '../../components/Header';
import { SlidesViewer } from '../../components/SlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { useParams, useNavigate } from 'react-router';
import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { getLesson, getModules, getLessons, type LessonDetail, type Lesson, type Module } from '../../services/lessons';
import { getEnrollments } from '../../services/api';
import {
  getLessonCompletions,
  createLessonCompletion,
  markLessonComplete,
} from '../../services/progress';
import { Loader2, BookOpen, CheckCircle2, PlayCircle, Lock, ChevronDown, ChevronRight, Camera, CameraOff } from 'lucide-react';
import { toast } from 'sonner';

import { logEmotionEvent, getSessionLog, getRecentFusedEmotion, clearSessionLog } from '../../services/emotionLogger';
import { fuseEmotions } from '../../services/emotionFusion';
import type { SERResult } from '../../services/tutor';

const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export default function LiveSession() {
  const { courseId, lessonId } = useParams();
  const navigate = useNavigate();

  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [moduleTitle, setModuleTitle] = useState('');
  const [courseTitle, setCourseTitle] = useState('');
  const [isCompleting, setIsCompleting] = useState(false);

  // Ordered list of all lessons in the course for prev/next navigation
  const [allLessons, setAllLessons] = useState<Lesson[]>([]);
  const [modules, setModules] = useState<Module[]>([]);
  const [completedLessonIds, setCompletedLessonIds] = useState<Set<number>>(new Set());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [expandedModules, setExpandedModules] = useState<Set<number>>(new Set());

  // ─── Emotion & FER state ──────────────────────────────────────
  const [fusedEmotion, setFusedEmotion] = useState<string | undefined>();
  const [cameraEnabled, setCameraEnabled] = useState(false);

  // ─── Student profile for Dr. Nova personalization ─────────────
  const [studentProfileSummary, setStudentProfileSummary] = useState<string | undefined>();

  const webcamStreamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ferIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const latestSERRef = useRef<SERResult | null>(null);
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
    if (!lessonId) return;
    const id = Number(lessonId);
    if (isNaN(id)) {
      setError('Invalid lesson ID');
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      try {
        const lessonData = await getLesson(id);
        if (cancelled) return;
        setLesson(lessonData);
        setCurrentSlide(0);

        if (courseId) {
          try {
            const mods = await getModules(Number(courseId));
            const mod = mods.find((m) => m.id === lessonData.module);
            if (mod) setModuleTitle(mod.title);
            if (!cancelled) {
              setModules(mods);
              // Auto-expand the module containing the current lesson
              setExpandedModules(new Set([lessonData.module]));
            }

            // Build ordered lesson list across all modules
            const lessonArrays = await Promise.all(
              mods
                .sort((a, b) => a.module_order - b.module_order)
                .map((m) => getLessons(m.id))
            );
            const ordered = lessonArrays.flat().sort((a, b) => {
              const aMod = mods.find((m) => m.id === a.module)?.module_order ?? 0;
              const bMod = mods.find((m) => m.id === b.module)?.module_order ?? 0;
              if (aMod !== bMod) return aMod - bMod;
              return a.lesson_order - b.lesson_order;
            });
            if (!cancelled) setAllLessons(ordered);
          } catch {
            // non-critical
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
              const completions = await getLessonCompletions(enrollment.id);
              const completedIds = new Set(
                completions
                  .filter((c) => c.status === 'Completed')
                  .map((c) => c.lesson as number)
              );
              if (!cancelled) setCompletedLessonIds(completedIds);
            } catch {
              // non-critical
            }
          }
        } catch {
          // non-critical
        }

        // Load student learning profile for Dr. Nova personalization (B4)
        try {
          const token = localStorage.getItem('token');
          if (token) {
            const profileRes = await fetch(`${API_URL}/progress/learning-profile/`, {
              headers: { Authorization: `Token ${token}` },
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

    // Clear emotion log at the start of each lesson
    clearSessionLog();

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
          const serData = latestSERRef.current
            ? { ser_emotion: latestSERRef.current.emotion, ser_confidence: latestSERRef.current.confidence }
            : {};

          const fusion = await fuseEmotions(
            { ...ferData, ...serData },
            {
              slide_index: currentSlide,
              subtopic: lesson?.title,
            },
          );

          setFusedEmotion(fusion.fused_emotion);

          // Log passive emotion event
          logEmotionEvent({
            timestamp: new Date().toISOString(),
            slide_index: currentSlide,
            subtopic: lesson?.title,
            fer_emotion: data.emotion,
            fer_confidence: data.confidence,
            ser_emotion: latestSERRef.current?.emotion,
            ser_confidence: latestSERRef.current?.confidence,
            fused_emotion: fusion.fused_emotion,
            event_type: 'passive',
          });
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

  // Toggle camera on/off
  const handleCameraToggle = useCallback(() => {
    if (cameraEnabled) {
      stopFERPolling();
      setCameraEnabled(false);
    } else {
      setCameraEnabled(true);
      startFERPolling();
    }
  }, [cameraEnabled, startFERPolling, stopFERPolling]);

  // Cleanup webcam on unmount
  useEffect(() => {
    return () => {
      stopFERPolling();
    };
  }, [stopFERPolling]);

  // ─── Session end: profile update + audit log (fire-and-forget) ─

  const fireAndForgetProfiler = useCallback(async () => {
    try {
      const log = getSessionLog();
      // Skip profiling if fewer than 3 events — not enough data
      if (log.length < 3) {
        clearSessionLog();
        return;
      }

      const token = localStorage.getItem('token');
      const authUser = localStorage.getItem('auth_user');
      const studentId = authUser ? JSON.parse(authUser).id : 0;

      // 1. GET existing learning profile from Django
      let existingProfileSummary = '';
      let existingProfileData = {};
      let existingSessionsCount = 0;
      if (token) {
        try {
          const existingRes = await fetch(`${API_URL}/progress/learning-profile/`, {
            headers: { Authorization: `Token ${token}` },
          });
          if (existingRes.ok) {
            const existing = await existingRes.json();
            existingProfileSummary = existing.profile_summary || '';
            existingProfileData = existing.profile_data || {};
            existingSessionsCount = existing.sessions_count || 0;
          }
        } catch {
          // No existing profile — first session
        }
      }

      // 2. Call POST /profiler/update on the AI service
      const profilerRes = await fetch(`${AI_URL}/profiler/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          student_id: studentId,
          lesson_title: lesson?.title || '',
          session_log: log,
          existing_profile_summary: existingProfileSummary,
          existing_profile_data: existingProfileData,
        }),
      });

      if (profilerRes.ok) {
        const profilerData = await profilerRes.json();

        // 3. POST to Django to overwrite the learning profile
        if (token) {
          await fetch(`${API_URL}/progress/learning-profile/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Token ${token}`,
            },
            body: JSON.stringify({
              sessions_count: existingSessionsCount + 1,
              profile_summary: profilerData.profile_summary || '',
              profile_data: {
                profile_summary: profilerData.profile_summary || '',
                ...(profilerData.profile_data || {}),
              },
            }),
          });
        }
      }

      // 4. Clear the session emotion cache
      clearSessionLog();
    } catch {
      // Fire-and-forget — entire block is non-blocking
      console.warn('[LiveSession] Profiler update failed (non-blocking)');
      clearSessionLog();
    }
  }, [lessonId, lesson]);

  // ─── Navigation callbacks ─────────────────────────────────────

  // Current lesson index in the full ordered list
  const currentLessonIndex = allLessons.findIndex((l) => l.id === Number(lessonId));
  const prevLesson = currentLessonIndex > 0 ? allLessons[currentLessonIndex - 1] : null;
  const nextLesson = currentLessonIndex >= 0 && currentLessonIndex < allLessons.length - 1
    ? allLessons[currentLessonIndex + 1]
    : null;

  const handlePrevSlideOrLesson = () => {
    if (currentSlide > 0) {
      setCurrentSlide((i) => i - 1);
    } else if (prevLesson) {
      navigate(`/course/${courseId}/lesson/${prevLesson.id}`);
    }
  };

  const handleNextSlideOrLesson = () => {
    if (lesson && currentSlide < lesson.slides.length - 1) {
      setCurrentSlide((i) => i + 1);
    } else if (nextLesson) {
      navigate(`/course/${courseId}/lesson/${nextLesson.id}`);
    }
  };

  const handleComplete = useCallback(async () => {
    if (!lesson || !courseId) return;
    setIsCompleting(true);

    // Fire-and-forget profiler before navigating away
    fireAndForgetProfiler();
    stopFERPolling();

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

      const completions = await getLessonCompletions(enrollment.id);
      const existing = completions.find(
        (c) => String(c.lesson) === String(lesson.id),
      );

      let result;
      if (existing) {
        result = await markLessonComplete(existing.id);
      } else {
        const created = await createLessonCompletion({
          enrollment: enrollment.id,
          lesson: lesson.id,
          status: 'Completed',
        });
        result = await markLessonComplete(created.id);
      }

      // Mark completed locally so drawer updates immediately
      setCompletedLessonIds((prev) => new Set([...prev, lesson.id]));

      // Show achievement toasts
      if (result.newly_earned_achievements?.length) {
        for (const ach of result.newly_earned_achievements) {
          toast.success(`${ach.icon_url} Achievement unlocked: ${ach.name} (+${ach.xp_reward} XP)`);
        }
      }

      // Go to next lesson if available, otherwise dashboard
      if (nextLesson) {
        navigate(`/course/${courseId}/lesson/${nextLesson.id}`);
      } else {
        toast.success('Course complete! Great work!');
        navigate('/dashboard');
      }
    } catch {
      toast.error('Failed to mark lesson as complete. Please try again.');
    } finally {
      setIsCompleting(false);
    }
  }, [lesson, courseId, navigate, nextLesson, fireAndForgetProfiler, stopFERPolling]);

  // ─── Callbacks for CompactTutor ───────────────────────────────

  const handleSessionStart = useCallback(() => {
    sessionStartedRef.current = true;
  }, []);

  const handleLatestSER = useCallback((ser: SERResult) => {
    latestSERRef.current = ser;
  }, []);

  // ─── Render ───────────────────────────────────────────────────

  if (loading) {
    return (
      <>
        <Header title="Loading..." backLink="/dashboard" backLabel="Dashboard" />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={40} className="animate-spin text-secondary" />
        </div>
      </>
    );
  }

  if (error || !lesson) {
    return (
      <>
        <Header title="Error" backLink="/dashboard" backLabel="Dashboard" />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-destructive">{error || 'Lesson not found.'}</p>
        </div>
      </>
    );
  }

  const headerTitle = courseTitle ? `${courseTitle}: ${lesson.title}` : lesson.title;

  const totalSlides = Math.max(lesson.slides.length, 1);
  const isLastSlideOfLastLesson = !nextLesson && currentSlide === totalSlides - 1;
  const currentSlideTitle = lesson.slides?.[currentSlide]?.content_json?.title;

  // Extract subtopics from slide titles for tutor self-reprompting
  const subtopics = lesson.slides
    .map((s) => (s.content_json?.title as string) || '')
    .filter(Boolean);


  return (
    <>
      <Header
        title={headerTitle}
        backLink={`/courses/${courseId}`}
        backLabel="Course"
        actionLeft={
          <button
            onClick={() => setDrawerOpen((o) => !o)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors"
          >
            <BookOpen size={15} />
            <span>Lessons</span>
          </button>
        }
      />

      {/* Slide-out Drawer — rendered into document.body via portal to escape overflow:hidden stacking context */}
      {drawerOpen && typeof document !== 'undefined' && createPortal(
        <div className="fixed inset-0 z-[9999]">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/30" onClick={() => setDrawerOpen(false)} />

          {/* Drawer panel */}
          <div className="absolute left-0 top-0 h-full w-72 bg-card border-r border-border flex flex-col shadow-2xl animate-in slide-in-from-left duration-200">
            {/* Drawer Header */}
            <div className="px-4 py-3 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <BookOpen size={15} className="text-secondary" />
                <span className="text-sm font-semibold text-foreground">Course Lessons</span>
              </div>
              <button onClick={() => setDrawerOpen(false)} className="text-muted-foreground hover:text-foreground transition-colors text-xl leading-none">&times;</button>
            </div>

            {/* Modules + Lessons */}
            <div className="flex-1 overflow-y-auto py-2">
              {modules
                .sort((a, b) => a.module_order - b.module_order)
                .map((mod) => {
                  const modLessons = allLessons.filter((l) => l.module === mod.id);
                  const isExpanded = expandedModules.has(mod.id);
                  return (
                    <div key={mod.id}>
                      {/* Module Header */}
                      <button
                        onClick={() => setExpandedModules((prev) => {
                          const next = new Set(prev);
                          next.has(mod.id) ? next.delete(mod.id) : next.add(mod.id);
                          return next;
                        })}
                        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-muted/40 transition-colors text-left"
                      >
                        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide truncate pr-2">{mod.title}</span>
                        {isExpanded
                          ? <ChevronDown size={13} className="text-muted-foreground shrink-0" />
                          : <ChevronRight size={13} className="text-muted-foreground shrink-0" />}
                      </button>

                      {/* Lessons */}
                      {isExpanded && (
                        <div className="pb-1">
                          {modLessons.map((l) => {
                            const isCurrent = l.id === Number(lessonId);
                            const isCompleted = completedLessonIds.has(l.id);
                            return (
                              <button
                                key={l.id}
                                onClick={() => {
                                  navigate(`/course/${courseId}/lesson/${l.id}`);
                                  setDrawerOpen(false);
                                }}
                                className={`w-full flex items-center gap-2.5 px-5 py-2 text-left transition-colors ${isCurrent
                                    ? 'bg-secondary/15 border-l-2 border-secondary'
                                    : 'hover:bg-muted/40 border-l-2 border-transparent'
                                  }`}
                              >
                                {isCompleted ? (
                                  <CheckCircle2 size={14} className="text-green-500 shrink-0" />
                                ) : isCurrent ? (
                                  <PlayCircle size={14} className="text-secondary shrink-0" />
                                ) : (
                                  <Lock size={14} className="text-muted-foreground/50 shrink-0" />
                                )}
                                <span className={`text-xs leading-snug truncate ${isCurrent ? 'font-semibold text-secondary' : isCompleted ? 'text-foreground' : 'text-muted-foreground'}`}>
                                  {l.title}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          </div>
        </div>,
        document.body!
      )}

      <div ref={contentRef} className="flex-1 flex overflow-hidden gap-0 relative bg-background">
        {/* Slides Viewer */}
        <SlidesViewer
          slides={lesson.slides}
          currentIndex={currentSlide}
          lessonTitle={lesson.title}
          moduleLabel={moduleTitle}
          onSlideChange={setCurrentSlide}
          isFullscreen={isFullscreen}
          onFullscreenToggle={toggleFullscreen}
        />

        {/* AI Tutor */}
        <CompactTutor
          key={lessonId}
          lessonTitle={lesson.title}
          subtopics={subtopics}
          fusedEmotion={fusedEmotion}
          currentSlideIndex={currentSlide}
          currentSlideTitle={currentSlideTitle as string}
          onSessionStart={handleSessionStart}
          onLatestSER={handleLatestSER}
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
        onComplete={handleComplete}
        isCompleting={isCompleting}
        hasPrevLesson={currentSlide === 0 && !!prevLesson}
        hasNextLesson={currentSlide === totalSlides - 1 && !!nextLesson}
        isLastLesson={isLastSlideOfLastLesson}
      />

      {/* Camera toggle button — small pill in bottom-right */}
      <button
        onClick={handleCameraToggle}
        className={`fixed bottom-20 right-4 z-50 flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium border shadow-md transition-all ${cameraEnabled
          ? 'bg-green-100 border-green-400 text-green-600'
          : 'bg-card border-border text-muted-foreground hover:border-secondary hover:text-foreground'
          }`}
        title={cameraEnabled ? 'Disable emotion tracking' : 'Enable emotion tracking (camera)'}
      >
        {cameraEnabled ? <Camera size={14} /> : <CameraOff size={14} />}
        <span>{cameraEnabled ? 'Tracking On' : 'Tracking Off'}</span>
      </button>

      {/* Hidden video and canvas for FER capture */}
      <video ref={videoRef} style={{ display: 'none' }} playsInline muted />
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </>
  );
}
