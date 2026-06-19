import { ChevronLeft, ChevronRight, CheckCircle2, Loader2, ClipboardCheck } from 'lucide-react';

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
  /** When set, overrides the NEXT button label (e.g. a pending knowledge check). */
  nextLabelOverride?: string;
  /** When set, overrides the COMPLETE button label (e.g. the END "Practice" check). */
  completeLabelOverride?: string;
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
  nextLabelOverride,
  completeLabelOverride,
}: SessionControlsProps) {
  const isFirstSlide = currentSlide === 0;
  const isLastSlide = currentSlide >= totalSlides - 1;

  // Prev is disabled only if it's the first slide AND there's no previous lesson
  const prevDisabled = isFirstSlide && !hasPrevLesson;
  // A pending knowledge check overrides NEXT and re-enables it even on the last
  // slide (so the student can reach the check before the lesson can advance).
  const nextDisabled = !nextLabelOverride && isLastSlide && !hasNextLesson;

  const prevLabel = isFirstSlide && hasPrevLesson ? '← PREV LESSON' : 'PREVIOUS';
  const nextLabel = nextLabelOverride
    ? nextLabelOverride
    : isLastSlide && hasNextLesson ? 'NEXT LESSON →' : 'NEXT';

  // Slide-strip indicator (mirrors the personifai SlideStrip): the active slide
  // is a wide accent bar, visited slides are steel, upcoming are faint.
  const dotCount = Math.min(totalSlides, 12);

  return (
    <div className="codex" style={{ borderTop: '1px solid var(--hairline)', background: 'var(--bg-primary)' }}>
      <div style={{ padding: '12px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        {/* Navigation */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button onClick={onPrev} disabled={prevDisabled} className="btn btn-ghost-dark" style={{ padding: '12px 18px' }}>
            <ChevronLeft size={16} /> {prevLabel}
          </button>
          <button onClick={onNext} disabled={nextDisabled} className="btn btn-paper" style={{ padding: '12px 18px' }}>
            {nextLabel} <ChevronRight size={16} />
          </button>
        </div>

        {/* Slide strip + counter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {Array.from({ length: dotCount }, (_, i) => {
              const active = i === currentSlide;
              const visited = i < currentSlide;
              return (
                <span
                  key={i}
                  style={{
                    width: active ? 28 : 16,
                    height: 4,
                    background: active ? 'var(--accent-primary)' : visited ? 'var(--steel-light)' : 'var(--steel)',
                    opacity: visited || active ? 1 : 0.4,
                    transition: 'width 200ms ease',
                  }}
                />
              );
            })}
          </div>
          <span className="t-mono steel">{currentSlide + 1} / {totalSlides}</span>
        </div>

        {/* Complete */}
        <button onClick={onComplete} disabled={isCompleting} className="btn btn-red" style={{ padding: '12px 18px' }}>
          {isCompleting ? (
            <><Loader2 size={16} className="animate-spin" /> COMPLETING…</>
          ) : completeLabelOverride ? (
            <><ClipboardCheck size={16} /> {completeLabelOverride}</>
          ) : isLastLesson ? (
            <><CheckCircle2 size={16} /> FINISH COURSE</>
          ) : (
            <><CheckCircle2 size={16} /> COMPLETE & NEXT</>
          )}
        </button>
      </div>
    </div>
  );
}
