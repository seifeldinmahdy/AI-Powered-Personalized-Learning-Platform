import { Maximize2, Minimize2 } from 'lucide-react';
import { useState } from 'react';

export function SlidesViewer() {
  const [isFullscreen, setIsFullscreen] = useState(false);

  return (
    <div className="flex-1 flex flex-col bg-background relative">
      {/* Slide Container */}
      <div className="flex-1 flex items-center justify-center p-8 bg-gradient-to-br from-muted/20 to-background">
        <div className="w-full h-full max-w-5xl bg-card rounded-2xl shadow-2xl border-2 border-border overflow-hidden flex flex-col">
          {/* Slide Header */}
          <div className="px-8 py-4 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5 flex items-center justify-between">
            <div>
              <div className="inline-block px-2 py-1 bg-secondary/10 text-secondary rounded text-xs font-semibold mb-1">
                MODULE 2 · LESSON 3
              </div>
              <h3 className="mb-0">Intro to Python Variables</h3>
            </div>
            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="p-2 rounded-lg border border-border hover:border-secondary transition-colors"
              title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          </div>

          {/* Slide Content */}
          <div className="flex-1 overflow-y-auto p-12">
            <div className="max-w-3xl mx-auto">
              {/* Title */}
              <div className="mb-12">
                <div className="w-20 h-1.5 bg-gradient-to-r from-secondary to-accent rounded-full mb-6" />
                <h1 className="mb-4">What is a Variable?</h1>
                <p className="text-xl text-foreground/70 leading-relaxed">
                  A container for storing data values in your program
                </p>
              </div>

              {/* Key Concept */}
              <div className="mb-10 bg-gradient-to-r from-primary/10 via-secondary/10 to-accent/10 border-l-4 border-secondary rounded-r-2xl p-6">
                <h3 className="mb-3 text-primary">Core Concept</h3>
                <p className="text-foreground/80 leading-relaxed text-lg">
                  Variables are like labeled boxes where you can store different types of information. 
                  You give them a name and assign them a value using the equals sign (=).
                </p>
              </div>

              {/* Code Example */}
              <div className="mb-10">
                <h4 className="mb-4">Example:</h4>
                <div className="bg-[#1e1e1e] rounded-xl overflow-hidden shadow-lg border border-[#3e3e42]">
                  <div className="px-6 py-3 bg-[#252526] border-b border-[#3e3e42]">
                    <span className="text-sm font-mono text-[#cccccc]">Python Code</span>
                  </div>
                  <pre className="p-6 text-base font-mono text-[#d4d4d4]">
                    <code>{`# Creating variables
x = 5                    # Integer (whole number)
name = "Python"          # String (text)
is_active = True         # Boolean (True/False)

# Using variables
print(x)                 # Output: 5
print(name)              # Output: Python`}</code>
                  </pre>
                </div>
              </div>

              {/* Data Types Grid */}
              <div className="mb-8">
                <h4 className="mb-5">Common Data Types:</h4>
                <div className="grid grid-cols-3 gap-5">
                  <div className="bg-card border-2 border-primary/20 rounded-xl p-6 hover:border-primary hover:shadow-lg transition-all">
                    <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center mb-4">
                      <span className="text-3xl">🔢</span>
                    </div>
                    <h4 className="mb-2">Numbers</h4>
                    <p className="text-sm text-muted-foreground mb-2">Integers & Decimals</p>
                    <code className="text-xs font-mono text-primary">int, float</code>
                  </div>

                  <div className="bg-card border-2 border-secondary/20 rounded-xl p-6 hover:border-secondary hover:shadow-lg transition-all">
                    <div className="w-14 h-14 rounded-xl bg-secondary/10 flex items-center justify-center mb-4">
                      <span className="text-3xl">📝</span>
                    </div>
                    <h4 className="mb-2">Text</h4>
                    <p className="text-sm text-muted-foreground mb-2">Characters & Words</p>
                    <code className="text-xs font-mono text-secondary">str</code>
                  </div>

                  <div className="bg-card border-2 border-accent/20 rounded-xl p-6 hover:border-accent hover:shadow-lg transition-all">
                    <div className="w-14 h-14 rounded-xl bg-accent/10 flex items-center justify-center mb-4">
                      <span className="text-3xl">✓</span>
                    </div>
                    <h4 className="mb-2">Boolean</h4>
                    <p className="text-sm text-muted-foreground mb-2">True or False</p>
                    <code className="text-xs font-mono text-accent">bool</code>
                  </div>
                </div>
              </div>

              {/* Key Takeaway */}
              <div className="bg-accent/5 border border-accent/20 rounded-xl p-6">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center flex-shrink-0 text-white font-bold">
                    !
                  </div>
                  <div>
                    <h5 className="mb-2 text-accent">Remember:</h5>
                    <p className="text-sm text-foreground/80">
                      Variable names should be descriptive and follow Python naming conventions 
                      (lowercase with underscores for spaces).
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Slide Footer */}
          <div className="px-8 py-3 border-t border-border bg-muted/20 flex items-center justify-between">
            <span className="text-sm text-muted-foreground font-mono">Slide 3 of 12</span>
            <div className="flex gap-2">
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((num) => (
                <div
                  key={num}
                  className={`w-1.5 h-1.5 rounded-full ${
                    num === 3 ? 'bg-secondary w-6' : num < 3 ? 'bg-accent' : 'bg-muted'
                  }`}
                />
              ))}
            </div>
            <span className="text-sm text-muted-foreground">Python 101</span>
          </div>
        </div>
      </div>
    </div>
  );
}
