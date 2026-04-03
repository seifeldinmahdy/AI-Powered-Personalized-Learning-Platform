import { Header } from '../../components/Header';
import { SlidesViewer } from '../../components/SlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { useParams, useNavigate } from 'react-router';
import { useState, useEffect, useCallback } from 'react';
import { getLesson, getModules, getLessons, type LessonDetail, type Lesson } from '../../services/lessons';
import { getEnrollments } from '../../services/api';
import {
  getLessonCompletions,
  createLessonCompletion,
  markLessonComplete,
} from '../../services/progress';
import { Loader2 } from 'lucide-react';
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
            const modules = await getModules(Number(courseId));
            const mod = modules.find((m) => m.id === lessonData.module);
            if (mod) setModuleTitle(mod.title);

            // Build ordered lesson list across all modules
            const lessonArrays = await Promise.all(
              modules
                .sort((a, b) => a.module_order - b.module_order)
                .map((m) => getLessons(m.id))
            );
            const ordered = lessonArrays.flat().sort((a, b) => {
              const aMod = modules.find((m) => m.id === a.module)?.module_order ?? 0;
              const bMod = modules.find((m) => m.id === b.module)?.module_order ?? 0;
              if (aMod !== bMod) return aMod - bMod;
              return a.lesson_order - b.lesson_order;
            });
            if (!cancelled) setAllLessons(ordered);
          } catch {
            // non-critical
          }
        }

        // Get course title from enrollment
        try {
          const { data: raw } = await getEnrollments();
          const enrollments = Array.isArray(raw) ? raw : raw.results ?? [];
          const enrollment = enrollments.find(
            (e: { course: number; course_title: string }) =>
              String(e.course) === String(courseId),
          );
          if (enrollment) setCourseTitle(enrollment.course_title);
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
      />

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
