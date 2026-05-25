import { Maximize2, Minimize2, ChevronLeft, ChevronRight, Eye } from 'lucide-react';
import type { GeneratedSlide, SlideContentItem, SlideCodeBlock, SlideVisual, SlideEquationItem } from '../services/pathway';
import { VisualRenderer } from './VisualRenderer';
import { EquationRenderer } from './EquationRenderer';

interface GeneratedSlidesViewerProps {
  slides: GeneratedSlide[];
  currentIndex: number;
  sessionTitle: string;
  onSlideChange?: (index: number) => void;
  isFullscreen?: boolean;
  onFullscreenToggle?: () => void;
}

export function GeneratedSlidesViewer({
  slides,
  currentIndex,
  sessionTitle,
  onSlideChange,
  isFullscreen = false,
  onFullscreenToggle,
}: GeneratedSlidesViewerProps) {
  const currentSlide = slides[currentIndex];
  const totalSlides = slides.length;

  const handlePrev = () => {
    if (currentIndex > 0) {
      onSlideChange?.(currentIndex - 1);
    } else {
      // Wrap to last slide
      onSlideChange?.(totalSlides - 1);
    }
  };

  const handleNext = () => {
    if (currentIndex < totalSlides - 1) {
      onSlideChange?.(currentIndex + 1);
    } else {
      // Wrap to first slide
      onSlideChange?.(0);
    }
  };

  return (
    <div className="flex-1 flex flex-col bg-background" style={{ minHeight: 0 }}>
      <div
        className="flex-1 flex items-center justify-center bg-gradient-to-br from-muted/20 to-background relative"
        style={{ minHeight: 0, padding: '24px 56px', ...(isFullscreen ? { paddingLeft: 360 } : {}) }}
      >
        {/* Left arrow */}
        <button
          onClick={handlePrev}
          className="absolute z-20 p-2 rounded-full bg-card/80 border border-border shadow-md hover:bg-card hover:border-secondary transition-all"
          style={{ left: 12, top: '50%', transform: 'translateY(-50%)' }}
          title="Previous slide"
        >
          <ChevronLeft size={20} />
        </button>

        {/* Right arrow */}
        <button
          onClick={handleNext}
          className="absolute z-20 p-2 rounded-full bg-card/80 border border-border shadow-md hover:bg-card hover:border-secondary transition-all"
          style={{ right: 12, top: '50%', transform: 'translateY(-50%)' }}
          title="Next slide"
        >
          <ChevronRight size={20} />
        </button>

        {/* Slide card - fixed to container height */}
        <div className="w-full max-w-5xl bg-card rounded-2xl shadow-2xl border-2 border-border flex flex-col" style={{ height: '100%', overflow: 'hidden' }}>
          {/* Slide Header - fixed */}
          <div className="px-8 py-4 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5 flex items-center justify-between" style={{ flexShrink: 0 }}>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="inline-block px-2 py-0.5 bg-secondary/10 text-secondary rounded text-xs font-semibold">
                  {currentSlide?.slide_type ?? 'Content'}
                </span>
                {currentSlide?.visual_type && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-accent/10 text-accent rounded text-xs font-semibold">
                    <Eye size={10} />
                    {currentSlide.visual_type}
                  </span>
                )}
              </div>
              <h3 className="mb-0">{sessionTitle}</h3>
            </div>
            <button
              onClick={onFullscreenToggle}
              className="p-2 rounded-lg border border-border hover:border-secondary transition-colors"
              title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          </div>

          {/* Slide Content - SCROLLABLE */}
          <div className="p-12" style={{ flex: '1 1 0%', minHeight: 0, overflowY: 'auto' }}>
            <div className="max-w-3xl mx-auto">
              {currentSlide ? (
                <SlideRenderer slide={currentSlide} />
              ) : (
                <div className="text-center text-muted-foreground py-20">
                  <p>No slide content available.</p>
                </div>
              )}
            </div>
          </div>

          {/* Slide Footer - fixed */}
          <div className="px-8 py-3 border-t border-border bg-muted/20 flex items-center justify-between" style={{ flexShrink: 0 }}>
            <span className="text-sm text-muted-foreground font-mono">
              Slide {currentIndex + 1} of {totalSlides}
            </span>
            <div className="flex gap-2">
              {slides.map((_, i) => (
                <button
                  key={i}
                  onClick={() => onSlideChange?.(i)}
                  className={`h-1.5 rounded-full transition-all cursor-pointer ${
                    i === currentIndex
                      ? 'bg-secondary w-6'
                      : i < currentIndex
                      ? 'bg-accent w-1.5'
                      : 'bg-muted w-1.5'
                  }`}
                />
              ))}
            </div>
            <span className="text-sm text-muted-foreground">{sessionTitle}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Slide type-specific rendering ──────────────────────────────

function SlideRenderer({ slide }: { slide: GeneratedSlide }) {
  switch (slide.slide_type) {
    case 'Title':
      return <TitleSlide slide={slide} />;
    case 'Agenda':
      return <AgendaSlide slide={slide} />;
    case 'Summary':
      return <SummarySlide slide={slide} />;
    default:
      return <ContentSlide slide={slide} />;
  }
}

function TitleSlide({ slide }: { slide: GeneratedSlide }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] text-center">
      <div className="w-24 h-1.5 bg-gradient-to-r from-secondary to-accent rounded-full mb-8" />
      <h1 className="text-4xl font-bold mb-6 bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text">
        {slide.title}
      </h1>
      {slide.body_content.map((item, i) => (
        <p key={i} className="text-lg text-foreground/60 mb-2">
          {item.text}
        </p>
      ))}
    </div>
  );
}

function AgendaSlide({ slide }: { slide: GeneratedSlide }) {
  return (
    <>
      <div className="mb-8">
        <div className="w-16 h-1.5 bg-gradient-to-r from-secondary to-accent rounded-full mb-4" />
        <h1 className="text-2xl font-bold">{slide.title}</h1>
      </div>
      <div className="space-y-3">
        {slide.body_content.map((item, i) => (
          <div
            key={i}
            className="flex items-center gap-4 p-4 bg-gradient-to-r from-secondary/5 to-transparent rounded-xl border border-border/50"
          >
            <div className="w-8 h-8 rounded-lg bg-secondary/10 flex items-center justify-center text-secondary font-bold text-sm shrink-0">
              {i + 1}
            </div>
            <span className="text-foreground/80">{item.text}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function SummarySlide({ slide }: { slide: GeneratedSlide }) {
  return (
    <>
      <div className="mb-8">
        <div className="w-16 h-1.5 bg-gradient-to-r from-accent to-primary rounded-full mb-4" />
        <h1 className="text-2xl font-bold">{slide.title}</h1>
      </div>
      <div className="space-y-3">
        {slide.body_content.map((item, i) => (
          <div
            key={i}
            className="flex items-start gap-3 p-4 bg-accent/5 border border-accent/20 rounded-xl"
          >
            <div className="w-6 h-6 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold shrink-0 mt-0.5">
              {i + 1}
            </div>
            <p className="text-foreground/80">{item.text}</p>
          </div>
        ))}
      </div>
    </>
  );
}

// ── Slide header shared by all content layouts ─────────────────

function SlideHeader({ title }: { title: string }) {
  if (!title) return null;
  return (
    <div className="mb-6">
      <div className="w-20 h-1.5 bg-gradient-to-r from-secondary to-accent rounded-full mb-4" />
      <h1 className="text-2xl font-bold">{title}</h1>
    </div>
  );
}

function BulletList({ items }: { items: GeneratedSlide['body_content'] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="space-y-3">
      {items.map((item, i) => (
        <ContentItemRenderer key={i} item={item} />
      ))}
    </div>
  );
}

// ── Layout-aware content slide ─────────────────────────────────

function ContentSlide({ slide }: { slide: GeneratedSlide }) {
  const layout = slide.layout ?? 'List_View';
  const hasEquations = slide.equation_block && slide.equation_block.length > 0;

  // ── Equation_Focus: bullets first, equations below ────────────
  if (layout === 'Equation_Focus') {
    return (
      <>
        <SlideHeader title={slide.title} />

        {/* Text content first */}
        {slide.body_content.length > 0 && (
          <div className="mb-6">
            <BulletList items={slide.body_content} />
          </div>
        )}

        {/* Equations below the text */}
        {hasEquations && (
          <div className="p-5 rounded-2xl border border-indigo-400/20 bg-gradient-to-br from-indigo-500/5 to-purple-500/5">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-1.5 h-4 rounded-full bg-gradient-to-b from-indigo-400 to-purple-500" />
              <span className="text-xs font-semibold tracking-widest uppercase text-indigo-400/80">
                Key Equations
              </span>
            </div>
            <EquationRenderer equations={slide.equation_block!} />
          </div>
        )}
      </>
    );
  }

  // ── Equation_Visual: equations left, diagram right ─────────────
  if (layout === 'Equation_Visual') {
    return (
      <>
        <SlideHeader title={slide.title} />

        <div className="grid grid-cols-2 gap-6 items-start">
          {/* Left column: equations + bullets */}
          <div className="space-y-4">
            {hasEquations && (
              <div className="p-4 rounded-xl border border-indigo-400/20 bg-gradient-to-br from-indigo-500/5 to-purple-500/5">
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-1.5 h-4 rounded-full bg-gradient-to-b from-indigo-400 to-purple-500" />
                  <span className="text-xs font-semibold tracking-widest uppercase text-indigo-400/80">
                    Equations
                  </span>
                </div>
                <EquationRenderer equations={slide.equation_block!} />
              </div>
            )}
            {slide.body_content.length > 0 && (
              <BulletList items={slide.body_content} />
            )}
          </div>

          {/* Right column: diagram */}
          <div className="flex items-start justify-center">
            {slide.visual && <VisualRenderer visual={slide.visual} />}
          </div>
        </div>
      </>
    );
  }

  // ── Code_Main: code is primary ─────────────────────────────────
  if (layout === 'Code_Main') {
    return (
      <>
        <SlideHeader title={slide.title} />
        {slide.code_block && <CodeBlockRenderer code={slide.code_block} />}
        {slide.body_content.length > 0 && (
          <div className="mt-6">
            <BulletList items={slide.body_content} />
          </div>
        )}
        {hasEquations && <EquationRenderer equations={slide.equation_block!} />}
      </>
    );
  }

  // ── Content_Visual: bullets + diagram ─────────────────────────
  if (layout === 'Content_Visual') {
    return (
      <>
        <SlideHeader title={slide.title} />
        <div className="grid grid-cols-2 gap-6 items-start">
          <BulletList items={slide.body_content} />
          <div className="flex items-start justify-center">
            {slide.visual && <VisualRenderer visual={slide.visual} />}
          </div>
        </div>
        {hasEquations && (
          <div className="mt-6">
            <EquationRenderer equations={slide.equation_block!} />
          </div>
        )}
      </>
    );
  }

  // ── List_View (default): plain text ───────────────────────────
  return (
    <>
      <SlideHeader title={slide.title} />
      {slide.body_content.length > 0 && (
        <div className="mb-8">
          <BulletList items={slide.body_content} />
        </div>
      )}
      {slide.code_block && <CodeBlockRenderer code={slide.code_block} />}
      {slide.visual && <VisualRenderer visual={slide.visual} />}
      {hasEquations && <EquationRenderer equations={slide.equation_block!} />}
    </>
  );
}

// ── Content item rendering with highlight types ────────────────

function ContentItemRenderer({ item }: { item: SlideContentItem }) {
  const ht = item.highlight_type;

  // Definition: term + description
  if (ht === 'definition' && item.term) {
    return (
      <div className="bg-gradient-to-r from-blue-500/10 via-blue-400/5 to-transparent border-l-4 border-blue-500 rounded-r-xl p-5">
        <span className="font-bold text-blue-600 dark:text-blue-400">
          {item.term}
        </span>
        <span className="text-foreground/80 ml-2">{item.text}</span>
      </div>
    );
  }

  // Key concept
  if (ht === 'key_concept') {
    return (
      <div className="flex items-start gap-3 p-4 bg-secondary/5 border border-secondary/20 rounded-xl">
        <div className="w-2 h-2 rounded-full bg-secondary mt-2 shrink-0" />
        <p className="text-foreground/90 font-medium">{item.text}</p>
      </div>
    );
  }

  // Example
  if (ht === 'example') {
    return (
      <div className="flex items-start gap-3 p-4 bg-emerald-500/5 border border-emerald-500/20 rounded-xl">
        <span className="text-emerald-600 font-semibold text-xs mt-0.5 shrink-0">
          Example:
        </span>
        <p className="text-foreground/80 italic">{item.text}</p>
      </div>
    );
  }

  // Attention / warning
  if (ht === 'attention') {
    return (
      <div className="flex items-start gap-3 p-4 bg-amber-500/5 border border-amber-500/20 rounded-xl">
        <div className="w-6 h-6 rounded-full bg-amber-500 flex items-center justify-center text-white text-xs font-bold shrink-0">
          !
        </div>
        <p className="text-foreground/80 font-medium">{item.text}</p>
      </div>
    );
  }

  // Default bullet
  return (
    <div className="flex items-start gap-3 pl-2">
      <div className="w-1.5 h-1.5 rounded-full bg-foreground/30 mt-2.5 shrink-0" />
      <p className="text-foreground/80">{item.text}</p>
    </div>
  );
}

// ── Code block rendering ───────────────────────────────────────

function CodeBlockRenderer({ code }: { code: SlideCodeBlock }) {
  return (
    <div className="mb-8">
      <div className="bg-[#1e1e1e] rounded-xl overflow-hidden shadow-lg border border-[#3e3e42]">
        <div className="px-6 py-3 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
          <span className="text-sm font-mono text-[#cccccc]">{code.language}</span>
          <button
            onClick={() => navigator.clipboard.writeText(code.code)}
            className="text-xs text-[#888] hover:text-white transition-colors px-2 py-1 rounded border border-[#3e3e42] hover:border-[#555]"
          >
            Copy
          </button>
        </div>
        <pre className="p-6 text-sm font-mono text-[#d4d4d4] overflow-x-auto">
          <code>{code.code}</code>
        </pre>
      </div>
    </div>
  );
}

