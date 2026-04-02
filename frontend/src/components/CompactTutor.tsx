import { Mic, MicOff, Volume2, VolumeX, MessageCircle, Pause, Play } from 'lucide-react';
import { useState } from 'react';

interface CompactTutorProps {
  lessonTitle?: string;
}

export function CompactTutor({ lessonTitle }: CompactTutorProps) {
  const [isMuted, setIsMuted] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(true);
  const [showChat, setShowChat] = useState(false);

  return (
    <div className="w-[35%] border-l-2 border-border bg-card flex flex-col">
      {/* Tutor Header */}
      <div className="px-4 py-3 border-b border-border bg-gradient-to-br from-primary/5 to-accent/5">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <h4 className="mb-0 text-sm">Dr. Nova</h4>
        </div>
        <p className="text-xs text-muted-foreground">AI Teaching Assistant</p>
      </div>

      {/* Avatar - Compact Version */}
      <div className="px-4 py-6 flex flex-col items-center border-b border-border bg-gradient-to-br from-primary/5 via-secondary/5 to-accent/5">
        <div className="relative mb-4">
          {/* Glow Effect */}
          <div className="absolute inset-0 bg-gradient-to-br from-secondary to-accent rounded-full blur-xl opacity-20" />
          
          {/* Avatar */}
          <div className="relative w-32 h-32 rounded-full bg-gradient-to-br from-primary via-secondary to-accent p-1 shadow-xl">
            <div className="w-full h-full rounded-full bg-background flex items-center justify-center overflow-hidden">
              <svg
                viewBox="0 0 200 200"
                className="w-24 h-24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                {/* Head */}
                <circle cx="100" cy="70" r="30" fill="url(#grad1)" />
                
                {/* Body */}
                <ellipse cx="100" cy="135" rx="38" ry="48" fill="url(#grad2)" />
                
                {/* Left Arm */}
                <path
                  d="M 68 108 Q 48 118 50 138"
                  stroke="url(#grad2)"
                  strokeWidth="14"
                  strokeLinecap="round"
                  fill="none"
                />
                
                {/* Right Arm */}
                <path
                  d="M 132 108 Q 152 118 150 138"
                  stroke="url(#grad2)"
                  strokeWidth="14"
                  strokeLinecap="round"
                  fill="none"
                />
                
                <defs>
                  <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#1E2A78" />
                    <stop offset="50%" stopColor="#4C6FFF" />
                    <stop offset="100%" stopColor="#A78BFA" />
                  </linearGradient>
                  <linearGradient id="grad2" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#4C6FFF" />
                    <stop offset="100%" stopColor="#A78BFA" />
                  </linearGradient>
                </defs>
              </svg>
            </div>
          </div>

          {/* Speaking Indicator */}
          {isSpeaking && (
            <div className="absolute -bottom-1 -right-1 flex gap-0.5 bg-card rounded-full px-2 py-1 border border-border shadow-md">
              <div className="w-1 h-3 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '0ms' }} />
              <div className="w-1 h-4 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '150ms' }} />
              <div className="w-1 h-3 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
            </div>
          )}
        </div>

        {/* Control Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsSpeaking(!isSpeaking)}
            className={`p-2 rounded-lg border-2 transition-all ${
              isSpeaking
                ? 'border-secondary bg-secondary text-white shadow-md'
                : 'border-border bg-card hover:border-secondary'
            }`}
            title={isSpeaking ? 'Pause' : 'Resume'}
          >
            {isSpeaking ? <Pause size={16} /> : <Play size={16} />}
          </button>

          <button
            onClick={() => setIsMuted(!isMuted)}
            className="p-2 rounded-lg border-2 border-border bg-card hover:border-secondary transition-colors"
            title={isMuted ? 'Unmute' : 'Mute'}
          >
            {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
          </button>
        </div>
      </div>

      {/* Current Topic */}
      <div className="px-4 py-4 border-b border-border bg-muted/20">
        <div className="text-xs text-muted-foreground mb-1">Currently Explaining:</div>
        <p className="text-sm font-semibold text-foreground leading-snug">
          {lessonTitle || 'Lesson Content'}
        </p>
      </div>

      {/* Transcript/Status */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="space-y-3">
          <div className="bg-primary/5 rounded-lg p-3 border-l-2 border-primary">
            <p className="text-xs text-foreground/80 leading-relaxed">
              "A variable is like a labeled container that holds information..."
            </p>
            <span className="text-xs text-muted-foreground mt-1 block">0:45</span>
          </div>

          <div className="bg-secondary/5 rounded-lg p-3 border-l-2 border-secondary">
            <p className="text-xs text-foreground/80 leading-relaxed">
              "You can store numbers, text, or True/False values in variables."
            </p>
            <span className="text-xs text-muted-foreground mt-1 block">1:12</span>
          </div>

          <div className="bg-accent/5 rounded-lg p-3 border-l-2 border-accent">
            <p className="text-xs text-foreground/80 leading-relaxed">
              "Let's look at some examples to understand this better..."
            </p>
            <span className="text-xs text-muted-foreground mt-1 block">1:38</span>
          </div>
        </div>
      </div>

      {/* Ask Question Button */}
      <div className="p-4 border-t border-border">
        <button
          onClick={() => setShowChat(!showChat)}
          className="w-full py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2 text-sm"
        >
          <MessageCircle size={16} />
          <span>Ask Question</span>
        </button>

        {/* Voice Input Button */}
        <button className="w-full mt-2 py-3 border-2 border-border rounded-xl hover:border-secondary transition-colors flex items-center justify-center gap-2 text-sm font-medium">
          <Mic size={16} />
          <span>Voice Input</span>
        </button>
      </div>
    </div>
  );
}
