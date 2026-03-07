import { ChevronLeft, ChevronRight, Mic } from 'lucide-react';

export function BottomControlBar() {
  return (
    <div className="border-t border-border bg-background px-8 py-4">
      <div className="flex items-center justify-between">
        {/* Left - Navigation */}
        <div className="flex items-center gap-2">
          <button className="px-4 py-2 border border-border hover:border-foreground transition-colors flex items-center gap-2">
            <ChevronLeft size={18} />
            <span>Previous</span>
          </button>
          <button className="px-4 py-2 border border-border hover:border-foreground transition-colors flex items-center gap-2">
            <span>Next</span>
            <ChevronRight size={18} />
          </button>
        </div>

        {/* Center - Ask Question Button */}
        <button className="relative group">
          <div className="w-16 h-16 rounded-full bg-foreground text-background flex items-center justify-center border-4 border-background shadow-[0_0_0_2px_#000000] hover:shadow-[0_0_0_4px_#000000] transition-all">
            <Mic size={24} />
          </div>
          <span className="absolute -bottom-8 left-1/2 transform -translate-x-1/2 text-sm whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
            Ask Question
          </span>
        </button>

        {/* Right - Additional Controls */}
        <div className="flex items-center gap-2">
          <button className="px-4 py-2 border border-border hover:border-foreground transition-colors">
            Bookmark
          </button>
          <button className="px-4 py-2 border border-border hover:border-foreground transition-colors">
            Notes
          </button>
        </div>
      </div>
    </div>
  );
}
