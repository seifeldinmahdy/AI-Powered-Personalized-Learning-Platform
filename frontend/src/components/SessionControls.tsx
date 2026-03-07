import { ChevronLeft, ChevronRight, Bookmark, CheckCircle2 } from 'lucide-react';

export function SessionControls() {
  const slides = [
    { id: 1, title: 'Introduction', completed: true },
    { id: 2, title: 'What are Variables?', completed: true },
    { id: 3, title: 'Data Types', completed: false, active: true },
    { id: 4, title: 'Type Conversion', completed: false },
    { id: 5, title: 'Practice', completed: false },
  ];

  return (
    <div className="border-t-2 border-border bg-card shadow-lg">
      <div className="px-6 py-3">
        <div className="flex items-center justify-between">
          {/* Navigation */}
          <div className="flex items-center gap-2">
            <button className="px-4 py-2 border-2 border-border rounded-lg hover:border-secondary hover:text-secondary transition-colors flex items-center gap-2 font-medium text-sm">
              <ChevronLeft size={16} />
              <span>Previous</span>
            </button>
            <button className="px-4 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-lg font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm">
              <span>Next</span>
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Progress Indicator */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              {slides.map((slide) => (
                <div
                  key={slide.id}
                  className={`h-2 rounded-full transition-all ${
                    slide.completed
                      ? 'bg-accent w-2'
                      : slide.active
                      ? 'bg-secondary w-8'
                      : 'bg-muted w-2'
                  }`}
                  title={slide.title}
                />
              ))}
            </div>
            <span className="text-sm font-mono text-foreground">3/5</span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button className="px-4 py-2 border-2 border-border rounded-lg hover:border-accent transition-colors flex items-center gap-2 font-medium text-sm">
              <Bookmark size={16} />
              <span>Save</span>
            </button>
            <button className="px-4 py-2 bg-primary text-white rounded-lg font-semibold hover:bg-primary/90 transition-colors flex items-center gap-2 text-sm">
              <CheckCircle2 size={16} />
              <span>Complete</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}