import { Volume2, VolumeX, Maximize2, Minimize2, MessageCircle } from 'lucide-react';
import { useState } from 'react';

export function TutorPanel() {
  const [isMuted, setIsMuted] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="flex-1 flex flex-col bg-gradient-to-br from-primary/5 to-secondary/5">
      {/* AI Tutor Avatar Section */}
      <div className="flex-1 flex flex-col items-center justify-center p-8 relative">
        {/* Decorative Background */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute top-20 left-20 w-64 h-64 bg-accent/10 rounded-full blur-3xl" />
          <div className="absolute bottom-20 right-20 w-96 h-96 bg-secondary/10 rounded-full blur-3xl" />
        </div>

        {/* 3D Avatar Silhouette */}
        <div className="relative z-10 mb-8">
          <div className="relative">
            {/* Glow Effect */}
            <div className="absolute inset-0 bg-gradient-to-br from-secondary to-accent rounded-full blur-2xl opacity-30 scale-110" />
            
            {/* Avatar Container */}
            <div className="relative w-80 h-80 rounded-full bg-gradient-to-br from-primary via-secondary to-accent p-1 shadow-2xl">
              <div className="w-full h-full rounded-full bg-background flex items-center justify-center overflow-hidden">
                {/* 3D Tutor Silhouette */}
                <svg
                  viewBox="0 0 200 200"
                  className="w-64 h-64"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  {/* Head */}
                  <circle cx="100" cy="70" r="35" fill="url(#gradient1)" />
                  
                  {/* Body */}
                  <ellipse cx="100" cy="140" rx="45" ry="55" fill="url(#gradient2)" />
                  
                  {/* Left Arm */}
                  <path
                    d="M 65 110 Q 40 120 45 145"
                    stroke="url(#gradient2)"
                    strokeWidth="18"
                    strokeLinecap="round"
                    fill="none"
                  />
                  
                  {/* Right Arm */}
                  <path
                    d="M 135 110 Q 160 120 155 145"
                    stroke="url(#gradient2)"
                    strokeWidth="18"
                    strokeLinecap="round"
                    fill="none"
                  />
                  
                  {/* Gradient Definitions */}
                  <defs>
                    <linearGradient id="gradient1" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#1E2A78" />
                      <stop offset="50%" stopColor="#4C6FFF" />
                      <stop offset="100%" stopColor="#A78BFA" />
                    </linearGradient>
                    <linearGradient id="gradient2" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#4C6FFF" />
                      <stop offset="100%" stopColor="#A78BFA" />
                    </linearGradient>
                  </defs>
                </svg>
              </div>
            </div>

            {/* Status Indicator */}
            <div className="absolute bottom-8 right-8 flex items-center gap-2 bg-card px-4 py-2 rounded-full shadow-lg border border-border">
              <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse" />
              <span className="text-sm font-semibold text-foreground">Active</span>
            </div>
          </div>

          {/* Tutor Name */}
          <div className="text-center mt-6">
            <h2 className="mb-1">Dr. Nova</h2>
            <p className="text-muted-foreground">AI Teaching Assistant</p>
          </div>
        </div>

        {/* Control Bar */}
        <div className="relative z-10 flex items-center gap-3">
          <button
            onClick={() => setIsMuted(!isMuted)}
            className="w-12 h-12 rounded-full bg-card border-2 border-border hover:border-secondary transition-colors flex items-center justify-center shadow-md"
            title={isMuted ? 'Unmute' : 'Mute'}
          >
            {isMuted ? <VolumeX size={20} /> : <Volume2 size={20} />}
          </button>

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="w-12 h-12 rounded-full bg-card border-2 border-border hover:border-secondary transition-colors flex items-center justify-center shadow-md"
            title={isExpanded ? 'Minimize' : 'Expand'}
          >
            {isExpanded ? <Minimize2 size={20} /> : <Maximize2 size={20} />}
          </button>
        </div>
      </div>

      {/* Lesson Content */}
      <div className="bg-card border-t-2 border-border p-8">
        <div className="max-w-2xl mx-auto">
          <div className="mb-6">
            <div className="inline-block px-3 py-1 bg-secondary/10 text-secondary rounded-full text-xs font-semibold mb-3">
              MODULE 2 · LESSON 3
            </div>
            <h3 className="mb-3">Understanding Python Variables</h3>
            <div className="w-16 h-1 bg-gradient-to-r from-secondary to-accent rounded-full mb-4" />
          </div>

          <div className="space-y-6">
            {/* Key Concept */}
            <div className="bg-gradient-to-r from-primary/5 to-secondary/5 border-l-4 border-secondary rounded-r-xl p-5">
              <h4 className="mb-2 text-primary">What is a Variable?</h4>
              <p className="text-foreground/80 leading-relaxed">
                A variable is a container for storing data values. In Python, you create 
                variables by assigning a value to a name using the equals sign (=).
              </p>
            </div>

            {/* Code Example */}
            <div className="bg-[#1e1e1e] rounded-xl overflow-hidden shadow-md">
              <div className="px-4 py-2 bg-[#252526] border-b border-[#3e3e42]">
                <span className="text-xs font-mono text-[#cccccc]">Example</span>
              </div>
              <pre className="p-4 text-sm font-mono text-[#d4d4d4] overflow-x-auto">
                <code>{`x = 5                    # Integer
name = "Python"          # String
is_active = True         # Boolean`}</code>
              </pre>
            </div>

            {/* Data Types Grid */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-card border-2 border-border rounded-xl p-4 hover:border-accent transition-colors">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center mb-3">
                  <span className="text-2xl">🔢</span>
                </div>
                <h5 className="mb-1 text-sm">Numbers</h5>
                <code className="text-xs font-mono text-muted-foreground">int, float</code>
              </div>

              <div className="bg-card border-2 border-border rounded-xl p-4 hover:border-accent transition-colors">
                <div className="w-10 h-10 rounded-lg bg-secondary/10 flex items-center justify-center mb-3">
                  <span className="text-2xl">📝</span>
                </div>
                <h5 className="mb-1 text-sm">Text</h5>
                <code className="text-xs font-mono text-muted-foreground">str</code>
              </div>

              <div className="bg-card border-2 border-border rounded-xl p-4 hover:border-accent transition-colors">
                <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center mb-3">
                  <span className="text-2xl">✓</span>
                </div>
                <h5 className="mb-1 text-sm">Boolean</h5>
                <code className="text-xs font-mono text-muted-foreground">True/False</code>
              </div>
            </div>

            {/* Chat with Tutor */}
            <button className="w-full py-4 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2">
              <MessageCircle size={20} />
              <span>Ask Dr. Nova a Question</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
