import { useEffect, useState } from 'react';
import { Maximize2, Minimize2, ChevronLeft, ChevronRight, Eye, Copy, Check, Play, Terminal, Sparkles } from 'lucide-react';
import type { GeneratedSlide, SlideContentItem, SlideCodeBlock } from '../services/pathway';
import { VisualRenderer } from './VisualRenderer';

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

  // No wrap-around: the first slide can't go back (would circle to the last) and
  // the last slide can't go forward (would circle to the first). The deck stays
  // a linear path within the session.
  const atFirst = currentIndex <= 0;
  const atLast = currentIndex >= totalSlides - 1;

  const handlePrev = () => {
    if (navLocked || atFirst) return;
    onSlideChange?.(currentIndex - 1);
  };

  const handleNext = () => {
    if (navLocked || atLast) return;
    onSlideChange?.(currentIndex + 1);
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
        {/* Left arrow — hidden on the first slide (no wrap to last) */}
        <button
          onClick={handlePrev}
          aria-disabled={navLocked || atFirst}
          disabled={atFirst}
          style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', zIndex: 20, padding: 8, borderRadius: 8, background: 'var(--bg-surface)', border: '1px solid var(--hairline)', color: 'var(--text-primary)', cursor: atFirst ? 'default' : navCursor, opacity: atFirst ? 0 : navLocked ? 0.45 : 1, pointerEvents: atFirst ? 'none' : 'auto', display: 'flex' }}
          title={lockTitle ?? 'Previous slide'}
        >
          <ChevronLeft size={20} />
        </button>

        {/* Right arrow — hidden on the last slide (no wrap to first) */}
        <button
          onClick={handleNext}
          aria-disabled={navLocked || atLast}
          disabled={atLast}
          style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', zIndex: 20, padding: 8, borderRadius: 8, background: 'var(--bg-surface)', border: '1px solid var(--hairline)', color: 'var(--text-primary)', cursor: atLast ? 'default' : navCursor, opacity: atLast ? 0 : navLocked ? 0.45 : 1, pointerEvents: atLast ? 'none' : 'auto', display: 'flex' }}
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
                // key per slide → the subtree remounts on navigation, so each
                // slide's code block starts un-run; the output only appears when
                // the student clicks Run on the slide they're actually viewing.
                <SlideRenderer key={currentSlide.source_chunk_id || currentIndex} slide={currentSlide} />
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
  const hasBullets = slide.body_content.length > 0;

  // ── Code_Main: code sits in the visual slot (right), bullets left ──
  // The code block occupies where visuals usually sit, so a code slide reads
  // like any other two-column slide instead of pushing content around.
  if (layout === 'Code_Main' && slide.code_block) {
    if (hasBullets) {
      return (
        <>
          <SlideHeader title={slide.title} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'start' }}>
            <BulletList items={slide.body_content} />
            <div style={{ minWidth: 0 }}>
              <CodeBlockRenderer code={slide.code_block} />
            </div>
          </div>
        </>
      );
    }
    return (
      <>
        <SlideHeader title={slide.title} />
        <CodeBlockRenderer code={slide.code_block} />
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
      </>
    );
  }

  // ── List_View (default): plain text; a stray code block sits on the right ──
  return (
    <>
      <SlideHeader title={slide.title} />
      {slide.code_block ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'start' }}>
          <BulletList items={slide.body_content} />
          <div style={{ minWidth: 0 }}>
            <CodeBlockRenderer code={slide.code_block} />
          </div>
        </div>
      ) : (
        <>
          {hasBullets && (
            <div style={{ marginBottom: 32 }}>
              <BulletList items={slide.body_content} />
            </div>
          )}
          {slide.visual && <VisualRenderer visual={slide.visual} />}
        </>
      )}
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

  // Example (green accent) — rendered in the display font so it is visibly
  // distinct from the body text, but clearer than the previous serif italic.
  if (ht === 'example') {
    return (
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: 16, background: 'rgba(22,163,74,0.05)', border: '1px solid rgba(22,163,74,0.2)', borderRadius: 8 }}>
        <span className="t-label" style={{ color: 'var(--accent-success)', marginTop: 2, flexShrink: 0 }}>EXAMPLE</span>
        <p style={{ margin: 0, color: 'var(--text-primary)', fontFamily: 'var(--ff-display)', fontWeight: 500, fontSize: 15, lineHeight: 1.5, letterSpacing: '0.01em' }}>{item.text}</p>
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

// Minimal, dependency-free syntax highlighter (VS Code "Dark+" palette). Good
// enough to make Python/JS snippets read like real code on a slide.
const CODE_COLORS = {
  comment: '#6A9955',
  string: '#CE9178',
  number: '#B5CEA8',
  keyword: '#569CD6',
  builtin: '#4EC9B0',
  func: '#DCDCAA',
  plain: '#D4D4D4',
};

const CODE_TOKEN_RE = new RegExp(
  [
    '(#[^\\n]*|//[^\\n]*)',                                   // 1 comment
    '("(?:[^"\\\\]|\\\\.)*"|\'(?:[^\'\\\\]|\\\\.)*\'|`(?:[^`\\\\]|\\\\.)*`)', // 2 string
    '\\b(\\d+(?:\\.\\d+)?)\\b',                               // 3 number
    '\\b(def|class|return|if|elif|else|for|while|in|import|from|as|with|try|except|finally|raise|lambda|yield|pass|break|continue|and|or|not|is|None|True|False|const|let|var|function|new|typeof|async|await|of|export|default|this)\\b', // 4 keyword
    '\\b(print|len|range|int|str|float|bool|list|dict|set|tuple|sum|max|min|map|filter|sorted|enumerate|zip|abs|round|open|input|console|Math|JSON|Array|Object)\\b', // 5 builtin
    '([A-Za-z_]\\w*)(?=\\s*\\()',                             // 6 function call
  ].join('|'),
  'g',
);

function highlightCode(code: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  CODE_TOKEN_RE.lastIndex = 0;
  while ((m = CODE_TOKEN_RE.exec(code)) !== null) {
    if (m.index > last) out.push(code.slice(last, m.index));
    const full = m[0];
    const color = m[1] ? CODE_COLORS.comment
      : m[2] ? CODE_COLORS.string
      : m[3] ? CODE_COLORS.number
      : m[4] ? CODE_COLORS.keyword
      : m[5] ? CODE_COLORS.builtin
      : CODE_COLORS.func;
    out.push(<span key={key++} style={{ color }}>{full}</span>);
    last = m.index + full.length;
    if (m.index === CODE_TOKEN_RE.lastIndex) CODE_TOKEN_RE.lastIndex++; // guard zero-width
  }
  if (last < code.length) out.push(code.slice(last));
  return out;
}

function CodeBlockRenderer({ code }: { code: SlideCodeBlock }) {
  const [ran, setRan] = useState(false);
  const [copied, setCopied] = useState(false);
  // Output is demonstrative (LLM-written, not executed). Only offer Run when present.
  const hasOutput = !!code.runnable && typeof code.output === 'string';

  // Revert the "copied" affordance after a moment (cleaned up on unmount).
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);

  const handleCopy = () => {
    navigator.clipboard.writeText(code.code).then(() => setCopied(true)).catch(() => {});
  };

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
              onClick={handleCopy}
              className="t-label"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: copied ? 'rgba(34,197,94,0.12)' : 'transparent', border: `1px solid ${copied ? 'rgba(34,197,94,0.4)' : 'rgba(255,255,255,0.15)'}`, borderRadius: 6, color: copied ? '#4ADE80' : '#9CA3AF', padding: '4px 8px', cursor: 'pointer', transition: 'color 150ms ease, background 150ms ease, border-color 150ms ease' }}
            >
              {copied ? <Check size={11} /> : <Copy size={11} />} {copied ? 'COPIED' : 'COPY'}
            </button>
          </div>
        </div>
        {/* maxHeight keeps the block from overflowing the slide / pushing layout */}
        <pre className="codeblock" style={{ margin: 0, borderRadius: 0, overflowX: 'auto', maxHeight: 320, overflowY: 'auto' }}>
          <code style={{ color: CODE_COLORS.plain }}>{highlightCode(code.code)}</code>
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
