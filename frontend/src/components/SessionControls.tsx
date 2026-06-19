import { ChevronLeft, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react';

interface SessionControlsProps {
  currentSlide: number;
  totalSlides: number;
  onPrev: () => void;
  onNext: () => void;
  // When true, slide navigation is locked (the tutor is speaking): the arrows
  // become non-interactive and show a not-allowed cursor on hover.
  navLocked?: boolean;
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
  navLocked = false,
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

  // While the tutor speaks we keep the buttons hoverable (so the not-allowed
  // cursor shows) but no-op the click — a `disabled` attribute would force the
  // default cursor and hide that affordance.
  const lockStyle = navLocked ? { cursor: 'not-allowed' as const, opacity: 0.45 } : {};
  const lockTitle = navLocked ? 'Wait for the tutor to finish speaking' : undefined;

  const prevLabel = isFirstSlide && hasPrevLesson ? '← PREV LESSON' : 'PREVIOUS';
  const nextLabel = isLastSlide && hasNextLesson ? 'NEXT LESSON →' : 'NEXT';

  // Slide-strip indicator (mirrors the personifai SlideStrip): the active slide
  // is a wide accent bar, visited slides are steel, upcoming are faint.
  const dotCount = Math.min(totalSlides, 12);

  return (
    <div className="codex" style={{ borderTop: '1px solid var(--hairline)', background: 'var(--bg-primary)' }}>
      <div style={{ padding: '12px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        {/* Navigation */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={navLocked ? undefined : onPrev}
            disabled={prevDisabled}
            aria-disabled={navLocked || prevDisabled}
            title={lockTitle}
            className="btn btn-ghost-dark"
            style={{ padding: '12px 18px', ...lockStyle }}
          >
            <ChevronLeft size={16} /> {prevLabel}
          </button>
          <button
            onClick={navLocked ? undefined : onNext}
            disabled={nextDisabled}
            aria-disabled={navLocked || nextDisabled}
            title={lockTitle}
            className="btn btn-paper"
            style={{ padding: '12px 18px', ...lockStyle }}
          >
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
