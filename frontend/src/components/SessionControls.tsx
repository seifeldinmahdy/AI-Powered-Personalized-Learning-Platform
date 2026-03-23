import { ChevronLeft, ChevronRight, Bookmark, CheckCircle2 } from 'lucide-react';

interface SessionControlsProps {
  currentSlide: number;
  totalSlides: number;
  onPrev: () => void;
  onNext: () => void;
  onComplete: () => void;
  isCompleting?: boolean;
}

export function SessionControls({
  currentSlide,
  totalSlides,
  onPrev,
  onNext,
  onComplete,
  isCompleting,
}: SessionControlsProps) {
  const isFirst = currentSlide === 0;
  const isLast = currentSlide >= totalSlides - 1;

  return (
    <div className="border-t-2 border-border bg-card shadow-lg">
      <div className="px-6 py-3">
        <div className="flex items-center justify-between">
          {/* Navigation */}
          <div className="flex items-center gap-2">
            <button
              onClick={onPrev}
              disabled={isFirst}
              className="px-4 py-2 border-2 border-border rounded-lg hover:border-secondary hover:text-secondary transition-colors flex items-center gap-2 font-medium text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={16} />
              <span>Previous</span>
            </button>
            <button
              onClick={onNext}
              disabled={isLast}
              className="px-4 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-lg font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <span>Next</span>
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Progress Indicator */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              {Array.from({ length: totalSlides }, (_, i) => (
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

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={onComplete}
              disabled={isCompleting}
              className="px-4 py-2 bg-primary text-white rounded-lg font-semibold hover:bg-primary/90 transition-colors flex items-center gap-2 text-sm disabled:opacity-50"
            >
              <CheckCircle2 size={16} />
              <span>{isCompleting ? 'Completing...' : 'Complete Lesson'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
