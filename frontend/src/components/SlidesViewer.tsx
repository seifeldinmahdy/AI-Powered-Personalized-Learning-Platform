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

  return (
    <div className="flex-1 flex flex-col bg-background relative">
      <div className="flex-1 flex items-center justify-center p-8 bg-gradient-to-br from-muted/20 to-background" style={isFullscreen ? { paddingLeft: 360 } : undefined}>
        {/* Left navigation arrow */}
        {totalSlides > 1 && (
          <button
            onClick={handlePrev}
            className="absolute left-4 z-10 p-2 rounded-full bg-card/80 border border-border shadow-md hover:bg-card hover:border-secondary transition-all"
            title="Previous slide"
          >
            <ChevronLeft size={20} />
          </button>
        )}

        {/* Right navigation arrow */}
        {totalSlides > 1 && (
          <button
            onClick={handleNext}
            className="absolute z-10 p-2 rounded-full bg-card/80 border border-border shadow-md hover:bg-card hover:border-secondary transition-all"
            style={isFullscreen ? { right: '16px' } : { right: '340px' }}
            title="Next slide"
          >
            <ChevronRight size={20} />
          </button>
        )}

        <div className="w-full h-full max-w-5xl bg-card rounded-2xl shadow-2xl border-2 border-border overflow-hidden flex flex-col">
          {/* Slide Header */}
          <div className="px-8 py-4 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5 flex items-center justify-between">
            <div>
              {moduleLabel && (
                <div className="inline-block px-2 py-1 bg-secondary/10 text-secondary rounded text-xs font-semibold mb-1">
                  {moduleLabel}
                </div>
              )}
              <h3 className="mb-0">{lessonTitle}</h3>
            </div>
            <div className="flex items-center gap-2">
              {lessonId && (
                <button
                  onClick={handleBookmarkToggle}
                  disabled={bookmarkLoading}
                  className="p-2 rounded-lg border border-border hover:border-secondary transition-colors disabled:opacity-50"
                  title={currentSlideBookmark ? 'Remove bookmark' : 'Bookmark this slide'}
                >
                  {currentSlideBookmark
                    ? <BookmarkCheck size={18} className="text-secondary" />
                    : <Bookmark size={18} />}
                </button>
              )}
              <button
                onClick={onFullscreenToggle}
                className="p-2 rounded-lg border border-border hover:border-secondary transition-colors"
                title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
              >
                {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
              </button>
            </div>
          </div>

          {/* Slide Content */}
          <div className="flex-1 overflow-y-auto p-12">
            <div className="max-w-3xl mx-auto">
              {currentSlide ? (
                <SlideContent content={currentSlide.content_json} />
              ) : (
                <div className="text-center text-muted-foreground py-20">
                  <p>No slide content available.</p>
                </div>
              )}
            </div>
          </div>

          {/* Slide Footer */}
          <div className="px-8 py-3 border-t border-border bg-muted/20 flex items-center justify-between">
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
            <span className="text-sm text-muted-foreground">{lessonTitle}</span>
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
        <div className="mb-12">
          <div className="w-20 h-1.5 bg-gradient-to-r from-secondary to-accent rounded-full mb-6" />
          <h1 className="mb-4">{title}</h1>
          {subtitle && (
            <p className="text-xl text-foreground/70 leading-relaxed">{subtitle}</p>
          )}
        </div>
      )}

      {body && (
        <div className="mb-10 bg-gradient-to-r from-primary/10 via-secondary/10 to-accent/10 border-l-4 border-secondary rounded-r-2xl p-6">
          <p className="text-foreground/80 leading-relaxed text-lg">{body}</p>
        </div>
      )}

      {code && (
        <div className="mb-10">
          <div className="bg-[#1e1e1e] rounded-xl overflow-hidden shadow-lg border border-[#3e3e42]">
            <div className="px-6 py-3 bg-[#252526] border-b border-[#3e3e42]">
              <span className="text-sm font-mono text-[#cccccc]">{codeLanguage}</span>
            </div>
            <pre className="p-6 text-base font-mono text-[#d4d4d4]">
              <code>{code}</code>
            </pre>
          </div>
        </div>
      )}

      {items && items.length > 0 && (
        <div className="mb-10 grid grid-cols-1 md:grid-cols-2 gap-4">
          {items.map((item, i) => (
            <div
              key={i}
              className="bg-card border-2 border-border rounded-xl p-5 hover:border-secondary hover:shadow-lg transition-all"
            >
              <p className="text-sm text-foreground/80">{item}</p>
            </div>
          ))}
        </div>
      )}

      {callout && (
        <div className="bg-accent/5 border border-accent/20 rounded-xl p-6">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center flex-shrink-0 text-white font-bold">
              !
            </div>
            <p className="text-sm text-foreground/80">{callout}</p>
          </div>
        </div>
      )}

      {/* Fallback: render raw JSON if none of the known fields are present */}
      {!title && !body && !code && !items && !callout && (
        <pre className="text-sm text-foreground/70 whitespace-pre-wrap">
          {JSON.stringify(content, null, 2)}
        </pre>
      )}
    </>
  );
}
