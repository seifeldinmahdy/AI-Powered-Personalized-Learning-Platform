import { Header } from '../../components/Header';
import { SlidesViewer } from '../../components/SlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { useParams, useNavigate } from 'react-router';
import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { getLesson, getModules, getLessons, type LessonDetail, type Lesson, type Module } from '../../services/lessons';
import { getEnrollments } from '../../services/api';
import {
  getLessonCompletions,
  createLessonCompletion,
  markLessonComplete,
} from '../../services/progress';
import { Loader2, BookOpen, CheckCircle2, PlayCircle, Lock, ChevronDown, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';

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
      } catch {
        if (!cancelled) setError('Failed to load lesson data.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [lessonId, courseId]);

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
  }, [lesson, courseId, navigate, nextLesson]);

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
                                className={`w-full flex items-center gap-2.5 px-5 py-2 text-left transition-colors ${
                                  isCurrent
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

      <div className="flex-1 flex overflow-hidden gap-0">
        {/* Slides Viewer (65%) */}
        <SlidesViewer
          slides={lesson.slides}
          currentIndex={currentSlide}
          lessonTitle={lesson.title}
          moduleLabel={moduleTitle}
          onSlideChange={setCurrentSlide}
        />

        {/* AI Tutor (35%) */}
        <CompactTutor key={lessonId} lessonTitle={lesson.title} />
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
    </>
  );
}
