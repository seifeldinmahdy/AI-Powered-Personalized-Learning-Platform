import { useState } from 'react';
import { Maximize2, Minimize2, ChevronLeft, ChevronRight, Eye, Copy, Play, Terminal, Sparkles } from 'lucide-react';
import type { GeneratedSlide, SlideContentItem, SlideCodeBlock } from '../services/pathway';
import { VisualRenderer } from './VisualRenderer';
import { EquationRenderer } from './EquationRenderer';

interface GeneratedSlidesViewerProps {
  slides: GeneratedSlide[];
  currentIndex: number;
  sessionTitle: string;
  onSlideChange?: (index: number) => void;
  // When true, slide navigation is locked (the tutor is speaking): the arrows
  // and the slide-strip dots become non-interactive with a not-allowed cursor.
  navLocked?: boolean;
  isFullscreen?: boolean;
  onFullscreenToggle?: () => void;
}

export function GeneratedSlidesViewer({
  slides,
  currentIndex,
  sessionTitle,
  onSlideChange,
  navLocked = false,
  isFullscreen = false,
  onFullscreenToggle,
}: GeneratedSlidesViewerProps) {
  const currentSlide = slides[currentIndex];
  const totalSlides = slides.length;

  const handlePrev = () => {
    if (navLocked) return;
    if (currentIndex > 0) onSlideChange?.(currentIndex - 1);
    else onSlideChange?.(totalSlides - 1); // wrap to last
  };

  const handleNext = () => {
    if (navLocked) return;
    if (currentIndex < totalSlides - 1) onSlideChange?.(currentIndex + 1);
    else onSlideChange?.(0); // wrap to first
  };

  // Hoverable-but-inert styling while locked (a `disabled` attribute would hide
  // the not-allowed cursor affordance).
  const navCursor = navLocked ? 'not-allowed' : 'pointer';
  const lockTitle = navLocked ? 'Wait for the tutor to finish speaking' : undefined;

  return (
    <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)', minHeight: 0 }}>
      <div
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', minHeight: 0, padding: '24px 56px', ...(isFullscreen ? { paddingLeft: 360 } : {}) }}
      >
        {/* Left arrow */}
        <button
          onClick={handlePrev}
          aria-disabled={navLocked}
          style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', zIndex: 20, padding: 8, borderRadius: 8, background: 'var(--bg-surface)', border: '1px solid var(--hairline)', color: 'var(--text-primary)', cursor: navCursor, opacity: navLocked ? 0.45 : 1, display: 'flex' }}
          title={lockTitle ?? 'Previous slide'}
        >
          <ChevronLeft size={20} />
        </button>

        {/* Right arrow */}
        <button
          onClick={handleNext}
          aria-disabled={navLocked}
          style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', zIndex: 20, padding: 8, borderRadius: 8, background: 'var(--bg-surface)', border: '1px solid var(--hairline)', color: 'var(--text-primary)', cursor: navCursor, opacity: navLocked ? 0.45 : 1, display: 'flex' }}
          title={lockTitle ?? 'Next slide'}
        >
          <ChevronRight size={20} />
        </button>

        {/* Slide card — fixed to container height */}
        <div className="paper-card" style={{ width: '100%', maxWidth: 1024, height: '100%', borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Slide Header — fixed */}
          <div style={{ padding: '16px 32px', borderBottom: '1px solid var(--bg-paper-line)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span className="tag-steel">{currentSlide?.slide_type ?? 'Content'}</span>
                {currentSlide?.visual_type && (
                  <span className="tag-steel" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--accent-primary)', borderColor: 'var(--accent-primary)' }}>
                    <Eye size={10} /> {currentSlide.visual_type}
                  </span>
                )}
              </div>
              <h3 className="t-label" style={{ margin: 0, color: 'var(--accent-primary)' }}>{sessionTitle}</h3>
            </div>
            <button
              onClick={onFullscreenToggle}
              style={{ padding: 8, borderRadius: 8, border: '1px solid var(--bg-paper-line)', background: 'transparent', color: 'var(--text-primary)', cursor: 'pointer', display: 'flex' }}
              title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          </div>

          {/* Slide Content — scrollable */}
          <div style={{ padding: 48, flex: '1 1 0%', minHeight: 0, overflowY: 'auto' }}>
            <div style={{ maxWidth: 768, marginInline: 'auto' }}>
              {currentSlide ? (
                <SlideRenderer slide={currentSlide} />
              ) : (
                <div className="t-body steel" style={{ textAlign: 'center', padding: '80px 0' }}>No slide content available.</div>
              )}
            </div>
          </div>

          {/* Slide Footer — fixed */}
          <div style={{ padding: '12px 32px', borderTop: '1px solid var(--bg-paper-line)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <span className="t-mono steel">SLIDE {currentIndex + 1} / {totalSlides}</span>
            <div style={{ display: 'flex', gap: 4 }}>
              {slides.map((_, i) => {
                const active = i === currentIndex;
                const visited = i < currentIndex;
                return (
                  <button
                    key={i}
                    onClick={navLocked ? undefined : () => onSlideChange?.(i)}
                    aria-disabled={navLocked}
                    title={lockTitle}
                    style={{ width: active ? 24 : 6, height: 4, borderRadius: 0, border: 'none', padding: 0, cursor: navCursor, background: active ? 'var(--accent-primary)' : visited ? 'var(--steel-light)' : 'var(--steel)', opacity: navLocked ? (visited || active ? 0.5 : 0.25) : (visited || active ? 1 : 0.4), transition: 'width 200ms ease' }}
                  />
                );
              })}
            </div>
            <span className="t-mono steel" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sessionTitle}</span>
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
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 400, textAlign: 'center' }}>
      <div style={{ width: 96, height: 4, background: 'var(--accent-primary)', marginBottom: 32 }} />
      <h1 className="t-display" style={{ fontSize: 'clamp(34px,5vw,48px)', color: 'var(--text-primary)', marginBottom: 24 }}>{slide.title}</h1>
      {slide.body_content.map((item, i) => (
        <p key={i} className="t-body" style={{ fontSize: 18, color: 'var(--text-secondary)', marginBottom: 8 }}>{item.text}</p>
      ))}
    </div>
  );
}

function AgendaSlide({ slide }: { slide: GeneratedSlide }) {
  return (
    <>
      <SlideHeader title={slide.title} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {slide.body_content.map((item, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 16, padding: 16, background: 'var(--bg-surface)', border: '1px solid var(--hairline)', borderRadius: 8 }}>
            <div className="t-mono" style={{ width: 32, height: 32, flexShrink: 0, borderRadius: 8, background: 'rgba(37,99,235,0.08)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>{i + 1}</div>
            <span className="t-body" style={{ fontSize: 15, color: 'var(--text-primary)' }}>{item.text}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function SummarySlide({ slide }: { slide: GeneratedSlide }) {
  return (
    <>
      <SlideHeader title={slide.title} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {slide.body_content.map((item, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: 16, background: 'rgba(22,163,74,0.05)', border: '1px solid rgba(22,163,74,0.2)', borderRadius: 8 }}>
            <div style={{ width: 24, height: 24, flexShrink: 0, marginTop: 2, borderRadius: 6, background: 'var(--accent-success)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>{i + 1}</div>
            <p className="t-body" style={{ margin: 0, fontSize: 15, color: 'var(--text-primary)' }}>{item.text}</p>
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
    <div style={{ marginBottom: 24 }}>
      <div style={{ width: 80, height: 4, background: 'var(--accent-primary)', marginBottom: 16 }} />
      <h1 className="t-heading" style={{ fontSize: 'clamp(24px,3.5vw,30px)', color: 'var(--text-primary)' }}>{title}</h1>
    </div>
  );
}

function BulletList({ items }: { items: GeneratedSlide['body_content'] }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
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
        {slide.body_content.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <BulletList items={slide.body_content} />
          </div>
        )}
        {hasEquations && (
          <div style={{ padding: 20, borderRadius: 8, border: '1px solid var(--hairline)', borderLeft: '2px solid var(--accent-primary)', background: 'var(--bg-surface)' }}>
            <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 12 }}>KEY EQUATIONS</div>
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'start' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {hasEquations && (
              <div style={{ padding: 16, borderRadius: 8, border: '1px solid var(--hairline)', borderLeft: '2px solid var(--accent-primary)', background: 'var(--bg-surface)' }}>
                <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 12 }}>EQUATIONS</div>
                <EquationRenderer equations={slide.equation_block!} />
              </div>
            )}
            {slide.body_content.length > 0 && <BulletList items={slide.body_content} />}
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
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
          <div style={{ marginTop: 24 }}>
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'start' }}>
          <BulletList items={slide.body_content} />
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
            {slide.visual && <VisualRenderer visual={slide.visual} />}
          </div>
        </div>
        {hasEquations && (
          <div style={{ marginTop: 24 }}>
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
        <div style={{ marginBottom: 32 }}>
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

  // Definition: term + description (blue accent — the "define" callout)
  if (ht === 'definition' && item.term) {
    return (
      <div style={{ background: 'rgba(37,99,235,0.05)', borderLeft: '3px solid var(--accent-primary)', borderRadius: '0 8px 8px 0', padding: 18 }}>
        <span style={{ fontWeight: 700, color: 'var(--accent-primary)' }}>{item.term}</span>
        <span className="t-body" style={{ color: 'var(--text-primary)', marginLeft: 8 }}>{item.text}</span>
      </div>
    );
  }

  // Key concept
  if (ht === 'key_concept') {
    return (
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: 16, background: 'var(--bg-surface)', border: '1px solid var(--hairline)', borderRadius: 8 }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent-primary)', marginTop: 8, flexShrink: 0 }} />
        <p className="t-body" style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 500 }}>{item.text}</p>
      </div>
    );
  }

  // Example (green accent)
  if (ht === 'example') {
    return (
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: 16, background: 'rgba(22,163,74,0.05)', border: '1px solid rgba(22,163,74,0.2)', borderRadius: 8 }}>
        <span className="t-label" style={{ color: 'var(--accent-success)', marginTop: 2, flexShrink: 0 }}>EXAMPLE</span>
        <p className="t-body" style={{ margin: 0, color: 'var(--text-primary)', fontStyle: 'italic', fontFamily: 'var(--ff-editorial)' }}>{item.text}</p>
      </div>
    );
  }

  // Attention / warning (red accent)
  if (ht === 'attention') {
    return (
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: 16, background: 'rgba(220,38,38,0.05)', border: '1px solid rgba(220,38,38,0.2)', borderRadius: 8 }}>
        <div style={{ width: 24, height: 24, borderRadius: '50%', background: 'var(--error-red)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, flexShrink: 0 }}>!</div>
        <p className="t-body" style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 500 }}>{item.text}</p>
      </div>
    );
  }

  // Default bullet — square bullet, editorial restraint
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, paddingLeft: 4 }}>
      <span className="sq-bullet" style={{ marginTop: 9 }} />
      <p className="t-body" style={{ margin: 0, color: 'var(--text-primary)' }}>{item.text}</p>
    </div>
  );
}

// ── Code block rendering ───────────────────────────────────────

function CodeBlockRenderer({ code }: { code: SlideCodeBlock }) {
  const [ran, setRan] = useState(false);
  // Output is demonstrative (LLM-written, not executed). Only offer Run when present.
  const hasOutput = !!code.runnable && typeof code.output === 'string';

  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ background: 'var(--code-bg)', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--hairline)' }}>
        <div style={{ padding: '10px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className="t-mono" style={{ color: '#9CA3AF', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            {code.language}
            {code.generated && (
              <span className="t-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#A78BFA', border: '1px solid rgba(167,139,250,0.3)', borderRadius: 5, padding: '1px 6px' }}>
                <Sparkles size={10} /> EXAMPLE
              </span>
            )}
          </span>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            {hasOutput && (
              <button
                onClick={() => setRan((v) => !v)}
                className="t-label"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: ran ? 'rgba(34,197,94,0.12)' : 'transparent', border: `1px solid ${ran ? 'rgba(34,197,94,0.4)' : 'rgba(255,255,255,0.15)'}`, borderRadius: 6, color: ran ? '#4ADE80' : '#9CA3AF', padding: '4px 8px', cursor: 'pointer' }}
              >
                <Play size={11} /> {ran ? 'HIDE OUTPUT' : 'RUN'}
              </button>
            )}
            <button
              onClick={() => navigator.clipboard.writeText(code.code)}
              className="t-label"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'transparent', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 6, color: '#9CA3AF', padding: '4px 8px', cursor: 'pointer' }}
            >
              <Copy size={11} /> COPY
            </button>
          </div>
        </div>
        {/* maxHeight keeps the block from overflowing the slide / pushing layout */}
        <pre className="codeblock" style={{ margin: 0, borderRadius: 0, overflowX: 'auto', maxHeight: 320, overflowY: 'auto' }}>
          <code>{code.code}</code>
        </pre>
        {hasOutput && ran && (
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', background: 'rgba(0,0,0,0.25)' }}>
            <div style={{ padding: '6px 18px', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Terminal size={11} style={{ color: '#6B7280' }} />
              <span className="t-label" style={{ color: '#6B7280' }}>OUTPUT</span>
            </div>
            <pre className="codeblock" style={{ margin: 0, borderRadius: 0, overflowX: 'auto', maxHeight: 160, overflowY: 'auto', background: 'transparent' }}>
              <code style={{ color: '#D1FAE5' }}>{code.output || '(no output)'}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
