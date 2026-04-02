import { ChevronLeft, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react';

interface SessionControlsProps {
  currentSlide: number;
  totalSlides: number;
  onPrev: () => void;
  onNext: () => void;
  onComplete: () => void;
  isCompleting?: boolean;
  hasPrevLesson?: boolean;
  hasNextLesson?: boolean;
  isLastLesson?: boolean;
}

export function SessionControls({
  currentSlide,
  totalSlides,
  onPrev,
  onNext,
  onComplete,
  isCompleting,
  hasPrevLesson,
  hasNextLesson,
  isLastLesson,
}: SessionControlsProps) {
  const isFirstSlide = currentSlide === 0;
  const isLastSlide = currentSlide >= totalSlides - 1;

  // Prev is disabled only if it's the first slide AND there's no previous lesson
  const prevDisabled = isFirstSlide && !hasPrevLesson;
  // Next is disabled only if it's the last slide AND there's no next lesson
  const nextDisabled = isLastSlide && !hasNextLesson;

  const prevLabel = isFirstSlide && hasPrevLesson ? '← Prev Lesson' : 'Previous';
  const nextLabel = isLastSlide && hasNextLesson ? 'Next Lesson →' : 'Next';

  return (
    <div className="border-t-2 border-border bg-card shadow-lg">
      <div className="px-6 py-3">
        <div className="flex items-center justify-between">
          {/* Navigation */}
          <div className="flex items-center gap-2">
            <button
              onClick={onPrev}
              disabled={prevDisabled}
              className="px-4 py-2 border-2 border-border rounded-lg hover:border-secondary hover:text-secondary transition-colors flex items-center gap-2 font-medium text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={16} />
              <span>{prevLabel}</span>
            </button>
            <button
              onClick={onNext}
              disabled={nextDisabled}
              className="px-4 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-lg font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <span>{nextLabel}</span>
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Progress dots */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              {Array.from({ length: Math.min(totalSlides, 12) }, (_, i) => (
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
              ))}
            </div>
            <span className="text-sm font-mono text-foreground">
              {currentSlide + 1}/{totalSlides}
            </span>
          </div>

          {/* Complete */}
          <button
            onClick={onComplete}
            disabled={isCompleting}
            className="px-4 py-2 bg-gradient-to-r from-primary to-secondary text-white rounded-lg font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm disabled:opacity-50"
          >
            {isCompleting ? (
              <><Loader2 size={16} className="animate-spin" /> Completing…</>
            ) : isLastLesson ? (
              <><CheckCircle2 size={16} /> Finish Course</>
            ) : (
              <><CheckCircle2 size={16} /> Complete & Next</>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
