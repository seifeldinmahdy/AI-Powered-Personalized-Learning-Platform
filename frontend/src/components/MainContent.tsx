import { Video } from 'lucide-react';

export function MainContent() {
  return (
    <div className="flex-1 relative bg-background p-8">
      {/* Slide Container */}
      <div className="h-full border border-border bg-secondary flex items-center justify-center relative">
        {/* Main Slide Content */}
        <div className="max-w-3xl w-full px-12">
          <div className="mb-12">
            <p className="text-sm opacity-70 mb-2">MODULE 2 · LESSON 3</p>
            <h1 className="mb-6">Intro to Python Variables</h1>
            <div className="w-16 h-1 bg-foreground mb-8"></div>
          </div>

          <div className="space-y-6">
            <div className="border-l-2 border-foreground pl-6">
              <h3 className="mb-3">What is a Variable?</h3>
              <p className="opacity-70">
                A variable is a container for storing data values. In Python, variables are 
                created when you assign a value to them.
              </p>
            </div>

            <div className="bg-background border border-border p-6">
              <p className="text-sm opacity-70 mb-2 font-mono">Example:</p>
              <pre className="font-mono text-base">
                <code>{`x = 5
name = "Python"
is_active = True`}</code>
              </pre>
            </div>

            <div className="grid grid-cols-3 gap-4 mt-8">
              <div className="border border-border p-4">
                <h5 className="mb-2">Numbers</h5>
                <code className="text-sm font-mono">int, float</code>
              </div>
              <div className="border border-border p-4">
                <h5 className="mb-2">Text</h5>
                <code className="text-sm font-mono">str</code>
              </div>
              <div className="border border-border p-4">
                <h5 className="mb-2">Boolean</h5>
                <code className="text-sm font-mono">True/False</code>
              </div>
            </div>
          </div>
        </div>

        {/* AI Tutor Stream - Floating in Top Right */}
        <div className="absolute top-6 right-6 w-64 border-2 border-foreground bg-background">
          {/* Header */}
          <div className="bg-foreground text-background px-4 py-2 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Video size={16} />
              <span className="text-sm">AI Tutor Stream</span>
            </div>
            <div className="w-2 h-2 bg-background rounded-full animate-pulse"></div>
          </div>
          
          {/* Video Area */}
          <div className="aspect-video bg-secondary border-b border-border flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 border-2 border-foreground rounded-full mx-auto mb-3 flex items-center justify-center">
                <div className="w-12 h-12 bg-foreground rounded-full flex items-center justify-center text-background">
                  AI
                </div>
              </div>
              <p className="text-xs opacity-70">Dr. Nova</p>
            </div>
          </div>
          
          {/* Controls */}
          <div className="px-4 py-2 flex items-center justify-between text-xs">
            <span className="opacity-70">Live</span>
            <div className="flex gap-2">
              <button className="px-2 py-1 border border-border hover:border-foreground transition-colors">
                Mute
              </button>
              <button className="px-2 py-1 border border-border hover:border-foreground transition-colors">
                Hide
              </button>
            </div>
          </div>
        </div>

        {/* Slide Number */}
        <div className="absolute bottom-6 left-6 text-sm opacity-70 font-mono">
          Slide 3 / 12
        </div>
      </div>
    </div>
  );
}
