import { Maximize2, Minimize2, ChevronLeft, ChevronRight, Bookmark, BookmarkCheck } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { createBookmark, deleteBookmark, type Bookmark as BookmarkType } from '../services/progress';
import type { Slide } from '../services/lessons';

interface SlidesViewerProps {
  slides: Slide[];
  currentIndex: number;
  lessonTitle: string;
  moduleLabel?: string;
  lessonId?: number;
  existingBookmarks?: BookmarkType[];
  onSlideChange?: (index: number) => void;
  isFullscreen?: boolean;
  onFullscreenToggle?: () => void;
}

export function SlidesViewer({
  slides,
  currentIndex,
  lessonTitle,
  moduleLabel,
  lessonId,
  existingBookmarks = [],
  onSlideChange,
  isFullscreen = false,
  onFullscreenToggle,
}: SlidesViewerProps) {
  const [bookmarks, setBookmarks] = useState<BookmarkType[]>(existingBookmarks);
  const [bookmarkLoading, setBookmarkLoading] = useState(false);
  const currentSlide = slides[currentIndex];
  const totalSlides = slides.length;

  const currentSlideBookmark = bookmarks.find(
    (b) => b.lesson === lessonId && b.slide_index === currentIndex
  );

  const handleBookmarkToggle = async () => {
    if (!lessonId || bookmarkLoading) return;
    setBookmarkLoading(true);
    try {
      if (currentSlideBookmark) {
        await deleteBookmark(currentSlideBookmark.id);
        setBookmarks((prev) => prev.filter((b) => b.id !== currentSlideBookmark.id));
        toast.success('Bookmark removed');
      } else {
        const bm = await createBookmark(lessonId, currentIndex);
        setBookmarks((prev) => [...prev, bm]);
        toast.success('Slide bookmarked!');
      }
    } catch {
      toast.error('Failed to update bookmark');
    } finally {
      setBookmarkLoading(false);
    }
  };

  const handlePrev = () => {
    // Wrap: pressing left on first goes to last
    const newIndex = currentIndex > 0 ? currentIndex - 1 : totalSlides - 1;
    onSlideChange?.(newIndex);
  };

  const handleNext = () => {
    // Wrap: pressing right on last goes to first
    const newIndex = currentIndex < totalSlides - 1 ? currentIndex + 1 : 0;
    onSlideChange?.(newIndex);
  };

  const arrowStyle = (side: 'left' | 'right'): React.CSSProperties => ({
    position: 'absolute', [side]: 12, top: '50%', transform: 'translateY(-50%)', zIndex: 20,
    padding: 8, borderRadius: 8, background: 'var(--bg-surface)', border: '1px solid var(--hairline)',
    color: 'var(--text-primary)', cursor: 'pointer', display: 'flex',
  });

  return (
    <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)', minHeight: 0 }}>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', minHeight: 0, padding: '24px 56px', ...(isFullscreen ? { paddingLeft: 360 } : {}) }}>
        {/* Left arrow */}
        {totalSlides > 1 && (
          <button onClick={handlePrev} style={arrowStyle('left')} title="Previous slide">
            <ChevronLeft size={20} />
          </button>
        )}

        {/* Right arrow */}
        {totalSlides > 1 && (
          <button onClick={handleNext} style={arrowStyle('right')} title="Next slide">
            <ChevronRight size={20} />
          </button>
        )}

        {/* Slide card — fixed to container height */}
        <div className="paper-card" style={{ width: '100%', maxWidth: 1024, height: '100%', borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Slide Header — fixed */}
          <div style={{ padding: '16px 32px', borderBottom: '1px solid var(--bg-paper-line)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <div>
              {moduleLabel && <div className="tag-steel" style={{ marginBottom: 6 }}>{moduleLabel}</div>}
              <h3 className="t-heading" style={{ margin: 0, fontSize: 18, color: 'var(--text-primary)' }}>{lessonTitle}</h3>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {lessonId && (
                <button
                  onClick={handleBookmarkToggle}
                  disabled={bookmarkLoading}
                  style={{ padding: 8, borderRadius: 8, border: '1px solid var(--bg-paper-line)', background: 'transparent', color: currentSlideBookmark ? 'var(--accent-primary)' : 'var(--text-primary)', cursor: 'pointer', display: 'flex', opacity: bookmarkLoading ? 0.5 : 1 }}
                  title={currentSlideBookmark ? 'Remove bookmark' : 'Bookmark this slide'}
                >
                  {currentSlideBookmark ? <BookmarkCheck size={18} /> : <Bookmark size={18} />}
                </button>
              )}
              <button
                onClick={onFullscreenToggle}
                style={{ padding: 8, borderRadius: 8, border: '1px solid var(--bg-paper-line)', background: 'transparent', color: 'var(--text-primary)', cursor: 'pointer', display: 'flex' }}
                title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
              >
                {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
              </button>
            </div>
          </div>

          {/* Slide Content — scrollable */}
          <div style={{ padding: 48, flex: '1 1 0%', minHeight: 0, overflowY: 'auto' }}>
            <div style={{ maxWidth: 768, marginInline: 'auto' }}>
              {currentSlide ? (
                <SlideContent content={currentSlide.content_json} />
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
                    onClick={() => onSlideChange?.(i)}
                    style={{ width: active ? 24 : 6, height: 4, borderRadius: 0, border: 'none', padding: 0, cursor: 'pointer', background: active ? 'var(--accent-primary)' : visited ? 'var(--steel-light)' : 'var(--steel)', opacity: visited || active ? 1 : 0.4, transition: 'width 200ms ease' }}
                  />
                );
              })}
            </div>
            <span className="t-mono steel" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{lessonTitle}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Renders slide content_json. Supports title, body, code, items, and callout fields. */
function SlideContent({ content }: { content: Record<string, unknown> }) {
  const title = content.title as string | undefined;
  const subtitle = content.subtitle as string | undefined;
  const body = content.body as string | undefined;
  const code = content.code as string | undefined;
  const codeLanguage = (content.code_language as string) || 'python';
  const items = content.items as string[] | undefined;
  const callout = content.callout as string | undefined;

  return (
    <>
      {title && (
        <div style={{ marginBottom: 40 }}>
          <div style={{ width: 80, height: 4, background: 'var(--accent-primary)', marginBottom: 24 }} />
          <h1 className="t-heading" style={{ fontSize: 'clamp(26px,4vw,34px)', color: 'var(--text-primary)', marginBottom: 16 }}>{title}</h1>
          {subtitle && <p className="t-body" style={{ fontSize: 19, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{subtitle}</p>}
        </div>
      )}

      {body && (
        <div style={{ marginBottom: 32, background: 'var(--bg-surface)', borderLeft: '3px solid var(--accent-primary)', borderRadius: '0 8px 8px 0', padding: 24 }}>
          <p className="t-body" style={{ margin: 0, color: 'var(--text-primary)', lineHeight: 1.6, fontSize: 17 }}>{body}</p>
        </div>
      )}

      {code && (
        <div style={{ marginBottom: 32 }}>
          <div style={{ background: 'var(--code-bg)', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--hairline)' }}>
            <div style={{ padding: '10px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
              <span className="t-mono" style={{ color: '#9CA3AF' }}>{codeLanguage}</span>
            </div>
            <pre className="codeblock" style={{ margin: 0, borderRadius: 0, fontSize: 14, overflowX: 'auto' }}>
              <code>{code}</code>
            </pre>
          </div>
        </div>
      )}

      {items && items.length > 0 && (
        <div style={{ marginBottom: 32, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
          {items.map((item, i) => (
            <div key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--hairline)', borderRadius: 8, padding: 20 }}>
              <p className="t-body" style={{ margin: 0, fontSize: 14, color: 'var(--text-primary)' }}>{item}</p>
            </div>
          ))}
        </div>
      )}

      {callout && (
        <div style={{ background: 'rgba(220,38,38,0.05)', border: '1px solid rgba(220,38,38,0.2)', borderRadius: 8, padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'var(--error-red)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: '#fff', fontWeight: 700 }}>!</div>
            <p className="t-body" style={{ margin: 0, fontSize: 14, color: 'var(--text-primary)' }}>{callout}</p>
          </div>
        </div>
      )}

      {/* Fallback: render raw JSON if none of the known fields are present */}
      {!title && !body && !code && !items && !callout && (
        <pre className="t-mono" style={{ color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
          {JSON.stringify(content, null, 2)}
        </pre>
      )}
    </>
  );
}
