import { useParams, useNavigate } from 'react-router';
import { useState, useEffect, useCallback, useRef } from 'react';
import { Header } from '../../components/Header';
import { GeneratedSlidesViewer } from '../../components/GeneratedSlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import {
  generateSlides,
  type PathwayPlan,
  type GeneratedSlide,
  type SlideGenerateResponse,
} from '../../services/pathway';
import { ChevronLeft, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react';
import type { SERResult } from '../../services/tutor';

const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';

const SLIDE_LOADING_MESSAGES = [
  'Generating your personalized slides...',
  'Running content through AI models...',
  'Classifying visual elements...',
  'Extracting code examples...',
  'Building your slide deck...',
  'Almost ready...',
];

export default function PathwaySession() {
  const { courseId, sessionNumber } = useParams<{
    courseId: string;
    sessionNumber: string;
  }>();
  const navigate = useNavigate();
  const sessionNum = Number(sessionNumber);

  const [plan, setPlan] = useState<PathwayPlan | null>(null);
  const [slides, setSlides] = useState<GeneratedSlide[]>([]);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [loadingMsg, setLoadingMsg] = useState(0);

  // Fullscreen
  const contentRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Tutor
  const [fusedEmotion, setFusedEmotion] = useState<string | undefined>();
  const latestSERRef = useRef<{ data: SERResult; timestamp: number } | null>(null);

  useEffect(() => {
    function onFsChange() {
      setIsFullscreen(!!document.fullscreenElement);
    }
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!contentRef.current) return;
    if (!document.fullscreenElement) {
      contentRef.current.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

  // Loading message cycling
  useEffect(() => {
    if (!loading) return;
    const iv = setInterval(() => {
      setLoadingMsg((p) => (p + 1) % SLIDE_LOADING_MESSAGES.length);
    }, 8000);
    return () => clearInterval(iv);
  }, [loading]);

  // Load plan + generate slides
  useEffect(() => {
    if (!courseId || isNaN(sessionNum)) return;
    let cancelled = false;

    async function run() {
      // 1. Load pathway plan from sessionStorage
      const raw = sessionStorage.getItem('pathway_plan');
      if (!raw) {
        setError('No pathway plan found. Please generate a pathway first.');
        setLoading(false);
        return;
      }

      const pathwayPlan: PathwayPlan = JSON.parse(raw);
      if (!cancelled) setPlan(pathwayPlan);

      const session = pathwayPlan.sessions.find(
        (s) => s.session_number === sessionNum,
      );
      if (!session) {
        setError(`Session ${sessionNum} not found in the pathway plan.`);
        setLoading(false);
        return;
      }

      // 2. Fetch session chunks from pathway (they're stored in the plan store)
      // For the MVP, we need to get the full chunks from the pathway endpoint
      // The plan summary only has chunk_count, not the actual text
      // We'll call the pathway/generate endpoint which returns the cached plan
      // But we need the actual chunk texts — let's fetch them via a dedicated call
      try {
        // Re-call generate (will return cached) to get the full plan with chunks
        const fullPlanRes = await fetch(`${AI_URL}/pathway/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            student_id: pathwayPlan.student_id,
            course_id: pathwayPlan.course_id,
            mastery_level: 'Novice',
            composition_mode: 'visual_heavy',
            language_proficiency: 'Elementary',
          }),
        });

        if (!fullPlanRes.ok) {
          throw new Error('Failed to fetch session data');
        }

        // The pathway /generate returns PlanSummary which doesn't include chunk texts
        // We need to get chunks from the stored plan. Let's call a session-specific endpoint.
        // Since the chunks are in the SQLite store, we need an endpoint that returns them.
        // For MVP: generate slides from the pathway session metadata
        // The session chunks come from ChromaDB and are stored in the plan.
        // We need to access them through a new endpoint or include them in the plan response.

        // Workaround: fetch chunks via the pathway's stored plan
        // The session plan's chunks have chunk_id and raw_text
        // Let's create a simple bridge: fetch chunks from the chroma reader using session topics

        const chunksRes = await fetch(`${AI_URL}/pathway/session-chunks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            student_id: pathwayPlan.student_id,
            course_id: pathwayPlan.course_id,
            session_number: sessionNum,
          }),
        });

        let chunks: Array<{
          chunk_id: string;
          raw_text: string;
          topic: string;
          page_start: number;
          page_end: number;
        }> = [];

        if (chunksRes.ok) {
          chunks = await chunksRes.json();
        } else {
          const errorText = await chunksRes.text();
          console.error('Chunks fetch failed:', chunksRes.status, errorText);
          throw new Error(`Failed to fetch session chunks: ${chunksRes.status} - ${errorText}`);
        }

        if (chunks.length === 0) {
          // Fallback: no chunks available, show error
          if (!cancelled) {
            setError('No content chunks available for this session.');
            setLoading(false);
          }
          return;
        }

        // 3. Generate slides
        const slideResponse = await generateSlides({
          session_number: sessionNum,
          session_title: session.session_title,
          topics_covered: session.topics_covered,
          book: session.book,
          chunks: chunks.map((c) => ({
            chunk_id: c.chunk_id,
            raw_text: c.raw_text,
            topic: c.topic,
            page_start: c.page_start,
            page_end: c.page_end,
          })),
          mastery_level: 'Novice',
          composition_mode: 'visual_heavy',
          language_proficiency: 'Elementary',
        });

        if (!cancelled) {
          setSlides(slideResponse.slides);
          setCurrentSlide(0);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Slide generation failed');
          setLoading(false);
        }
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, [courseId, sessionNum]);

  // Navigation
  const totalSlides = slides.length || 1;
  const session = plan?.sessions.find((s) => s.session_number === sessionNum);
  const totalSessions = plan?.total_sessions ?? 1;
  const hasPrevSession = sessionNum > 1;
  const hasNextSession = sessionNum < totalSessions;

  const handlePrev = () => {
    if (currentSlide > 0) {
      setCurrentSlide((i) => i - 1);
    } else if (hasPrevSession) {
      navigate(`/course/${courseId}/pathway/session/${sessionNum - 1}`);
    }
  };

  const handleNext = () => {
    if (currentSlide < totalSlides - 1) {
      setCurrentSlide((i) => i + 1);
    } else if (hasNextSession) {
      navigate(`/course/${courseId}/pathway/session/${sessionNum + 1}`);
    }
  };

  const handleComplete = () => {
    if (hasNextSession) {
      navigate(`/course/${courseId}/pathway/session/${sessionNum + 1}`);
    } else {
      navigate('/dashboard');
    }
  };

  // Tutor callbacks
  const handleLatestSER = useCallback((ser: SERResult) => {
    latestSERRef.current = { data: ser, timestamp: Date.now() };
  }, []);

  // ── Loading state ────────────────────────────────────────────
  if (loading) {
    return (
      <>
        <Header
          title="Loading Session..."
          backLink={`/course/${courseId}/pathway`}
          backLabel="Pathway"
        />
        <div className="flex-1 flex flex-col items-center justify-center bg-background p-8">
          <div className="w-full max-w-4xl aspect-[16/9] bg-card rounded-2xl border border-secondary/30 shadow-2xl shadow-secondary/10 overflow-hidden relative flex flex-col">
            {/* Immersive pulsing skeleton */}
            <div className="p-10 flex flex-col h-full gap-6">
              <div className="h-10 w-3/4 bg-gradient-to-r from-muted to-muted/30 rounded-xl animate-pulse" />
              <div className="h-6 w-1/3 bg-muted rounded-lg animate-pulse" style={{ animationDelay: '0.1s' }} />
              
              <div className="flex-1 flex flex-col gap-4 mt-8">
                <div className="h-4 w-full bg-muted/60 rounded-md animate-pulse" style={{ animationDelay: '0.2s' }} />
                <div className="h-4 w-11/12 bg-muted/60 rounded-md animate-pulse" style={{ animationDelay: '0.3s' }} />
                <div className="h-4 w-4/5 bg-muted/60 rounded-md animate-pulse" style={{ animationDelay: '0.4s' }} />
                <div className="h-4 w-full bg-muted/60 rounded-md animate-pulse" style={{ animationDelay: '0.5s' }} />
                <div className="h-4 w-3/4 bg-muted/60 rounded-md animate-pulse" style={{ animationDelay: '0.6s' }} />
              </div>
            </div>

            {/* Centered message overlay */}
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-card/70 backdrop-blur-md">
              <div className="p-6 bg-white/80 border border-secondary/30 rounded-2xl shadow-xl flex flex-col items-center text-center">
                <Loader2 size={48} className="animate-spin text-secondary mb-6" />
                <h3 className="text-xl font-bold bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent mb-2">
                  Building Your AI Course
                </h3>
                <p className="text-base font-semibold text-foreground/80 mb-1">
                  {SLIDE_LOADING_MESSAGES[loadingMsg]}
                </p>
                <p className="text-xs font-mono text-muted-foreground bg-muted/50 px-3 py-1.5 rounded-md mt-4 max-w-sm">
                  Please be patient. Running the local Large Language Models to generate your full interactive slide deck can take 3 to 5 minutes depending on your hardware.
                </p>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  }

  // ── Error state ──────────────────────────────────────────────
  if (error || slides.length === 0) {
    return (
      <>
        <Header
          title="Error"
          backLink={`/course/${courseId}/pathway`}
          backLabel="Pathway"
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-md px-6">
            <p className="text-destructive mb-4">{error || 'No slides generated.'}</p>
            <button
              onClick={() => window.location.reload()}
              className="px-6 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold text-sm"
            >
              Retry
            </button>
          </div>
        </div>
      </>
    );
  }

  // ── Main view ────────────────────────────────────────────────
  const headerTitle = session
    ? `Session ${sessionNum}: ${session.session_title}`
    : `Session ${sessionNum}`;

  const subtopics = slides
    .filter((s) => s.slide_type === 'Content')
    .map((s) => s.title)
    .filter(Boolean);

  const currentSlideTitle = slides[currentSlide]?.title;

  const isFirstSlide = currentSlide === 0;
  const isLastSlide = currentSlide >= totalSlides - 1;
  const prevDisabled = isFirstSlide && !hasPrevSession;
  const nextDisabled = isLastSlide && !hasNextSession;

  return (
    <>
      <Header
        title={headerTitle}
        backLink={`/course/${courseId}/pathway`}
        backLabel="Pathway"
      />

      <div ref={contentRef} className="flex-1 flex overflow-hidden gap-0 relative bg-background">
        {/* Slides Viewer */}
        <GeneratedSlidesViewer
          slides={slides}
          currentIndex={currentSlide}
          sessionTitle={session?.session_title ?? `Session ${sessionNum}`}
          onSlideChange={setCurrentSlide}
          isFullscreen={isFullscreen}
          onFullscreenToggle={toggleFullscreen}
        />

        {/* AI Tutor */}
        <CompactTutor
          key={`pathway-session-${sessionNum}`}
          lessonTitle={session?.session_title ?? ''}
          subtopics={subtopics}
          fusedEmotion={fusedEmotion}
          currentSlideIndex={currentSlide}
          currentSlideTitle={currentSlideTitle}
          onSessionStart={() => {}}
          onLatestSER={handleLatestSER}
          onUpdateFusedEmotion={setFusedEmotion}
          isFloating={isFullscreen}
        />
      </div>

      {/* Bottom Controls */}
      <div className="border-t-2 border-border bg-card shadow-lg">
        <div className="px-6 py-3">
          <div className="flex items-center justify-between">
            {/* Navigation */}
            <div className="flex items-center gap-2">
              <button
                onClick={handlePrev}
                disabled={prevDisabled}
                className="px-4 py-2 border-2 border-border rounded-lg hover:border-secondary hover:text-secondary transition-colors flex items-center gap-2 font-medium text-sm disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={16} />
                <span>
                  {isFirstSlide && hasPrevSession ? '← Prev Session' : 'Previous'}
                </span>
              </button>
              <button
                onClick={handleNext}
                disabled={nextDisabled}
                className="px-4 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-lg font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <span>
                  {isLastSlide && hasNextSession ? 'Next Session →' : 'Next'}
                </span>
                <ChevronRight size={16} />
              </button>
            </div>

            {/* Progress dots */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1">
                {Array.from(
                  { length: Math.min(totalSlides, 12) },
                  (_, i) => (
                    <div
                      key={i}
                      className={`h-2 rounded-full transition-all ${
                        i < currentSlide
                          ? 'bg-accent w-2'
                          : i === currentSlide
                          ? 'bg-secondary w-8'
                          : 'bg-muted w-2'
                      }`}
                    />
                  ),
                )}
              </div>
              <span className="text-sm font-mono text-foreground">
                {currentSlide + 1}/{totalSlides}
              </span>
            </div>

            {/* Complete */}
            <button
              onClick={handleComplete}
              className="px-4 py-2 bg-gradient-to-r from-primary to-secondary text-white rounded-lg font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm"
            >
              <CheckCircle2 size={16} />
              {hasNextSession ? 'Complete & Next Session' : 'Finish Course'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
