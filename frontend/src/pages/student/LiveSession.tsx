import { Header } from '../../components/Header';
import { CodePanel, type CodePanelChallenge } from '../../components/CodePanel';
import { SlidesViewer } from '../../components/SlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { useParams, useNavigate } from 'react-router';
import { useState, useEffect, useCallback } from 'react';
import { getLesson, getModules, type LessonDetail } from '../../services/lessons';
import { getEnrollments } from '../../services/api';
import {
  getLessonCompletions,
  createLessonCompletion,
  markLessonComplete,
} from '../../services/progress';
import { Loader2 } from 'lucide-react';

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

        // Fetch module title for breadcrumb
        if (courseId) {
          try {
            const modules = await getModules(Number(courseId));
            const mod = modules.find((m) => m.id === lessonData.module);
            if (mod) setModuleTitle(mod.title);
          } catch {
            // non-critical
          }
        }

        // Try to get course title from enrollment
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
    return () => {
      cancelled = true;
    };
  }, [lessonId, courseId]);

  const handleComplete = useCallback(async () => {
    if (!lesson || !courseId) return;
    setIsCompleting(true);
    try {
      // Find the enrollment for this course
      const { data: raw } = await getEnrollments();
      const enrollments = Array.isArray(raw) ? raw : raw.results ?? [];
      const enrollment = enrollments.find(
        (e: { course: number }) => String(e.course) === String(courseId),
      );
      if (!enrollment) {
        alert('You are not enrolled in this course.');
        return;
      }

      // Check if completion record exists
      const completions = await getLessonCompletions(enrollment.id);
      const existing = completions.find(
        (c) => String(c.lesson) === String(lesson.id),
      );

      if (existing) {
        await markLessonComplete(existing.id);
      } else {
        const created = await createLessonCompletion({
          enrollment: enrollment.id,
          lesson: lesson.id,
          status: 'Completed',
        });
        await markLessonComplete(created.id);
      }

      navigate('/dashboard');
    } catch {
      alert('Failed to mark lesson as complete.');
    } finally {
      setIsCompleting(false);
    }
  }, [lesson, courseId, navigate]);

  // Build challenge for CodePanel from lesson data
  const challenge: CodePanelChallenge | undefined =
    lesson?.code_challenges?.[0]
      ? {
          problem_text: lesson.code_challenges[0].problem_text,
          starter_code: lesson.code_challenges[0].starter_code,
          hint_text: lesson.code_challenges[0].hint_text || undefined,
        }
      : undefined;

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

  const headerTitle = courseTitle
    ? `${courseTitle}: ${lesson.title}`
    : lesson.title;

  return (
    <>
      <Header
        title={headerTitle}
        backLink="/dashboard"
        backLabel="Dashboard"
      />

      <div className="flex-1 flex overflow-hidden gap-0">
        {/* Left Panel - Code Editor (30%) */}
        <CodePanel challenge={challenge} />

        {/* Center - Slides Viewer (50%) */}
        <SlidesViewer
          slides={lesson.slides}
          currentIndex={currentSlide}
          lessonTitle={lesson.title}
          moduleLabel={moduleTitle}
          onSlideChange={setCurrentSlide}
        />

        {/* Right Panel - Compact Tutor (20%) */}
        <CompactTutor />
      </div>

      {/* Bottom Controls */}
      <SessionControls
        currentSlide={currentSlide}
        totalSlides={Math.max(lesson.slides.length, 1)}
        onPrev={() => setCurrentSlide((i) => Math.max(0, i - 1))}
        onNext={() =>
          setCurrentSlide((i) => Math.min(lesson.slides.length - 1, i + 1))
        }
        onComplete={handleComplete}
        isCompleting={isCompleting}
      />
    </>
  );
}
