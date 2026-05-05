import { useParams, useNavigate } from 'react-router';
import { useState, useEffect, useRef } from 'react';
import { generatePathway, type PathwayPlan, type PathwaySession } from '../../services/pathway';
import api, { getEnrollments } from '../../services/api';
import { BookOpen, Clock, Layers, ChevronRight, Loader2, Sparkles } from 'lucide-react';

const LOADING_MESSAGES = [
  'Analyzing your placement results...',
  "Mapping the book's knowledge structure...",
  'Building your personalized curriculum...',
  'Ordering topics for optimal learning...',
  'Grouping content into focused sessions...',
  'Applying adaptive difficulty calibration...',
  'Finalizing your session plan...',
];

export default function CoursePathway() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();

  const [plan, setPlan] = useState<PathwayPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [messageIndex, setMessageIndex] = useState(0);
  const [fadingOut, setFadingOut] = useState(false);
  const [firstLessonId, setFirstLessonId] = useState<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cycle loading messages
  useEffect(() => {
    if (!loading) return;
    intervalRef.current = setInterval(() => {
      setFadingOut(true);
      setTimeout(() => {
        setMessageIndex((prev) => (prev + 1) % LOADING_MESSAGES.length);
        setFadingOut(false);
      }, 400);
    }, 25000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [loading]);

  // Generate pathway on mount
  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;

    async function run() {
      try {
        // Fetch first lesson ID from Django
        import('../../services/lessons').then(async ({ getModules, getLessons }) => {
          try {
            const mods = await getModules(Number(courseId));
            if (mods.length > 0) {
              mods.sort((a, b) => a.module_order - b.module_order);
              const firstMod = mods[0];
              const lessons = await getLessons(firstMod.id);
              if (lessons.length > 0) {
                lessons.sort((a, b) => a.lesson_order - b.lesson_order);
                if (!cancelled) setFirstLessonId(lessons[0].id);
              } else {
                if (!cancelled) setFirstLessonId(1); // fallback
              }
            } else {
              if (!cancelled) setFirstLessonId(1); // fallback
            }
          } catch (e) {
            console.error('Failed to load lessons for routing', e);
            if (!cancelled) setFirstLessonId(1); // fallback
          }
        });

        const authUser = localStorage.getItem('auth_user');
        const studentId = authUser ? JSON.parse(authUser).id : 'mvp_student_001';

        // Fetch real student context from persistence
        let contextProfile: any = null;
        try {
          const ctxRes = await fetch(`${import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001'}/student-context/${studentId}/${courseId}`);
          if (ctxRes.ok) {
            const ctx = await ctxRes.json();
            contextProfile = ctx.profile;
          }
        } catch (e) {
          console.warn('Could not fetch student context, using defaults', e);
        }

        const result = await generatePathway({
          student_id: contextProfile?.student_id || String(studentId),
          course_id: contextProfile?.course_id || 'pythonlearn',
          mastery_level: contextProfile?.mastery_level || 'Novice',
          composition_mode: contextProfile?.composition_mode || 'balanced',
          language_proficiency: contextProfile?.language_proficiency || 'Intermediate',
          strengths: contextProfile?.strengths || [],
          weaknesses: contextProfile?.weaknesses || [],
          topic_performance: contextProfile?.topic_performance || {},
          incorrectly_answered: contextProfile?.incorrectly_answered || [],
          use_synthetic_context: false,
        });

        if (!cancelled) {
          // Notify backend that pathway is ready
          try {
            const enrollRes = await getEnrollments();
            const list = Array.isArray(enrollRes.data) ? enrollRes.data : enrollRes.data?.results || [];
            const enrollment = list.find((e: any) => e.course === Number(courseId));

            if (enrollment) {
              await api.post(`/courses/enrollments/${enrollment.id}/save_pathway/`, {
                pathway: result
              });
            }
          } catch (backendError) {
            console.error("Failed to sync pathway to backend", backendError);
          }

          setPlan(result);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Pathway generation failed');
          setLoading(false);
        }
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  // ── Loading screen ───────────────────────────────────────────
  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-gradient-to-br from-[#0f0c29] via-[#302b63] to-[#24243e]">
        {/* Animated background particles */}
        <div className="absolute inset-0 overflow-hidden">
          {Array.from({ length: 20 }).map((_, i) => (
            <div
              key={i}
              className="absolute rounded-full bg-white/5 animate-pulse"
              style={{
                width: `${Math.random() * 6 + 2}px`,
                height: `${Math.random() * 6 + 2}px`,
                left: `${Math.random() * 100}%`,
                top: `${Math.random() * 100}%`,
                animationDuration: `${Math.random() * 3 + 2}s`,
                animationDelay: `${Math.random() * 2}s`,
              }}
            />
          ))}
        </div>

        {/* Central loading content */}
        <div className="relative z-10 flex flex-col items-center gap-8 max-w-lg px-6">
          {/* Spinning orb */}
          <div className="relative">
            <div className="w-24 h-24 rounded-full border-4 border-transparent border-t-purple-400 border-r-blue-400 animate-spin" />
            <div className="absolute inset-0 flex items-center justify-center">
              <Sparkles size={32} className="text-purple-300 animate-pulse" />
            </div>
          </div>

          {/* Title */}
          <div className="text-center">
            <h1 className="text-2xl font-bold text-white mb-2">
              Generating Your Learning Pathway
            </h1>
            <p className="text-white/50 text-sm">
              This may take a few minutes as we analyze the book and design your personalized curriculum
            </p>
          </div>

          {/* Rotating status message */}
          <div className="h-8 flex items-center justify-center">
            <p
              className={`text-purple-300 text-base font-medium transition-opacity duration-400 ${fadingOut ? 'opacity-0' : 'opacity-100'
                }`}
            >
              {LOADING_MESSAGES[messageIndex]}
            </p>
          </div>

          {/* Progress dots */}
          <div className="flex gap-2">
            {LOADING_MESSAGES.map((_, i) => (
              <div
                key={i}
                className={`h-1.5 rounded-full transition-all duration-300 ${i === messageIndex
                    ? 'bg-purple-400 w-8'
                    : i < messageIndex
                      ? 'bg-purple-600 w-1.5'
                      : 'bg-white/10 w-1.5'
                  }`}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────
  if (error || !plan) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8">
        <div className="w-16 h-16 rounded-2xl bg-destructive/10 flex items-center justify-center">
          <Sparkles size={32} className="text-destructive" />
        </div>
        <h2 className="text-lg font-semibold">Pathway Generation Failed</h2>
        <p className="text-muted-foreground text-sm text-center max-w-md">
          {error || 'Could not generate your learning pathway. Please try again.'}
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-6 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold text-sm hover:shadow-lg transition-all"
        >
          Retry
        </button>
      </div>
    );
  }

  // ── Session plan display ─────────────────────────────────────
  return (
    <div className="flex-1 overflow-y-auto bg-background">
      {/* Hero */}
      <div className="bg-gradient-to-br from-primary via-secondary to-accent text-white">
        <div className="max-w-5xl mx-auto px-6 py-10">
          <button
            onClick={() => navigate(-1)}
            className="text-white/70 hover:text-white text-sm mb-4 transition-colors"
          >
            &larr; Back
          </button>
          <h1 className="text-3xl font-bold mb-2">Your Personalized Learning Pathway</h1>
          <p className="text-white/80 text-base mb-4">
            Introduction to Programming with Python
          </p>
          <div className="flex flex-wrap gap-6 text-sm text-white/80">
            <span className="flex items-center gap-1.5">
              <Layers size={15} />
              {plan.total_sessions} sessions
            </span>
            <span className="flex items-center gap-1.5">
              <BookOpen size={15} />
              {plan.total_chunks} content chunks
            </span>
            <span className="flex items-center gap-1.5">
              <Clock size={15} />
              ~{Math.round((plan.total_chunks * 2) / 60)}h estimated
            </span>
          </div>
        </div>
      </div>

      {/* Session cards */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="space-y-4">
          {plan.sessions.map((session) => (
            <SessionCard key={session.session_number} session={session} />
          ))}
        </div>

        {/* Begin Course button */}
        <div className="mt-10 flex justify-center">
          <button
            disabled={firstLessonId === null}
            onClick={() => {
              sessionStorage.setItem('pathway_plan', JSON.stringify(plan));
              if (firstLessonId) {
                navigate(`/course/${courseId}/lesson/${firstLessonId}`);
              }
            }}
            className="px-8 py-4 bg-gradient-to-r from-primary to-secondary text-white rounded-2xl font-bold text-lg hover:shadow-xl hover:-translate-y-0.5 transition-all flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Sparkles size={20} />
            {firstLessonId === null ? 'Preparing Course...' : 'Begin Course'}
            <ChevronRight size={20} />
          </button>
        </div>
      </div>
    </div>
  );
}

function SessionCard({ session }: { session: PathwaySession }) {
  return (
    <div className="bg-card rounded-2xl border border-border shadow-sm hover:shadow-md hover:border-secondary/40 transition-all p-6">
      <div className="flex items-start gap-4">
        {/* Session number badge */}
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-secondary to-accent flex items-center justify-center text-white font-bold text-lg shrink-0">
          {session.session_number}
        </div>

        <div className="flex-1 min-w-0">
          {/* Title */}
          <h3 className="text-base font-semibold mb-1">{session.session_title}</h3>

          {/* Description */}
          <p className="text-sm text-muted-foreground mb-3">
            Learn about {session.topics_covered.slice(0, 3).join(', ')}
            {session.topics_covered.length > 3
              ? ` and ${session.topics_covered.length - 3} more topics`
              : ''}
            .
          </p>

          {/* Topics chips */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {session.topics_covered.slice(0, 5).map((topic, i) => (
              <span
                key={i}
                className="px-2 py-0.5 bg-secondary/10 text-secondary rounded text-xs font-medium"
              >
                {topic}
              </span>
            ))}
            {session.topics_covered.length > 5 && (
              <span className="px-2 py-0.5 bg-muted rounded text-xs text-muted-foreground">
                +{session.topics_covered.length - 5} more
              </span>
            )}
          </div>

          {/* Stats */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <BookOpen size={12} />
              {session.chunk_count} chunks
            </span>
            <span className="flex items-center gap-1">
              <Clock size={12} />
              ~{Math.max(1, Math.round(session.chunk_count * 2))} min
            </span>
            {session.book && (
              <span className="flex items-center gap-1">
                pp. {session.page_range_start}–{session.page_range_end}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
