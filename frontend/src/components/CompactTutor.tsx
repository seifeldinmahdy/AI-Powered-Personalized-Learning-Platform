import {
  Mic, MicOff, Volume2, VolumeX, MessageCircle,
  Pause, Play, Loader2, CheckCircle2, Send, X,
  BookOpen
} from 'lucide-react';
import { useState, useRef, useEffect, useCallback } from 'react';
import {
  startSession,
  continueSession,
  askQuestion,
  stopSession,
  type TopicInput,
  type ContinueResponse,
} from '../services/tutor';

interface TranscriptEntry {
  role: 'tutor' | 'student';
  text: string;
  topic?: string;
  subtopic?: string;
  isAnswer?: boolean;
}

interface CompactTutorProps {
  /** Pre-configured topics for this lesson. If provided, shows "Start Session" immediately. */
  topics?: TopicInput[];
}

export function CompactTutor({ topics: propTopics }: CompactTutorProps) {
  // ─── State ───
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<'idle' | 'lecturing' | 'answering' | 'finished' | 'loading'>('idle');
  const [isMuted, setIsMuted] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [showQuestionInput, setShowQuestionInput] = useState(false);
  const [questionText, setQuestionText] = useState('');
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [currentTopic, setCurrentTopic] = useState<string | null>(null);
  const [currentSubtopic, setCurrentSubtopic] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const isPausedRef = useRef(false);

  // Keep ref in sync with state
  useEffect(() => {
    isPausedRef.current = isPaused;
  }, [isPaused]);

  // Default topics if none provided
  const defaultTopics: TopicInput[] = propTopics || [
    {
      name: 'Python Variables',
      subtopics: [
        'What is a variable and why do we need them',
        'Variable naming rules and conventions',
        'Assigning values to variables',
      ],
    },
    {
      name: 'Data Types',
      subtopics: [
        'Integers and floats',
        'Strings and string operations',
        'Booleans and type conversion',
      ],
    },
  ];

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  // ─── Audio playback ───
  const playAudio = useCallback((base64Audio: string): Promise<void> => {
    return new Promise((resolve, reject) => {
      try {
        // Stop previous audio if playing
        if (audioRef.current) {
          audioRef.current.pause();
          audioRef.current = null;
        }

        if (isMuted) {
          resolve();
          return;
        }

        const audio = new Audio(`data:audio/mpeg;base64,${base64Audio}`);
        audioRef.current = audio;
        setIsSpeaking(true);

        audio.onended = () => {
          setIsSpeaking(false);
          audioRef.current = null;
          resolve();
        };
        audio.onerror = () => {
          setIsSpeaking(false);
          audioRef.current = null;
          reject(new Error('Audio playback failed'));
        };
        audio.play().catch(reject);
      } catch (e) {
        reject(e);
      }
    });
  }, [isMuted]);

  // ─── Start session ───
  const handleStart = async () => {
    setError(null);
    setStatus('loading');
    setTranscript([]);

    try {
      const res = await startSession(defaultTopics);
      setSessionId(res.data.session_id);
      setStatus('lecturing');

      // Immediately get the first chunk
      await fetchNextChunk(res.data.session_id);
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to start session');
      setStatus('idle');
    }
  };

  // ─── Fetch next lecture chunk (the self-reprompting loop) ───
  const fetchNextChunk = async (sid: string) => {
    try {
      setStatus('lecturing');
      const res = await continueSession(sid);
      const data: ContinueResponse = res.data;

      if (data.text) {
        setTranscript(prev => [...prev, {
          role: 'tutor',
          text: data.text,
          topic: data.topic || undefined,
          subtopic: data.subtopic || undefined,
        }]);
      }

      setCurrentTopic(data.topic);
      setCurrentSubtopic(data.subtopic);
      setProgress(data.progress);

      if (data.is_finished) {
        setStatus('finished');
        return;
      }

      // Play audio, then auto-continue
      if (data.audio_base64) {
        try {
          await playAudio(data.audio_base64);
        } catch {
          // Audio failed, continue anyway
        }
      }

      // Wait a beat, then auto-continue (unless paused or asking question)
      if (!isPausedRef.current) {
        setTimeout(() => {
          if (!isPausedRef.current) {
            fetchNextChunk(sid);
          }
        }, 500);
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to continue');
      setStatus('idle');
    }
  };

  // ─── Ask question ───
  const handleAskQuestion = async () => {
    if (!sessionId || !questionText.trim()) return;

    const q = questionText.trim();
    setQuestionText('');
    setShowQuestionInput(false);
    setStatus('answering');

    // Pause the auto-continue
    setIsPaused(true);

    setTranscript(prev => [...prev, { role: 'student', text: q }]);

    try {
      const res = await askQuestion(sessionId, q);

      setTranscript(prev => [...prev, {
        role: 'tutor',
        text: res.data.answer,
        topic: res.data.topic || undefined,
        subtopic: res.data.subtopic || undefined,
        isAnswer: true,
      }]);

      setProgress(res.data.progress);

      // Play audio answer
      if (res.data.audio_base64) {
        try {
          await playAudio(res.data.audio_base64);
        } catch { /* continue */ }
      }

      // Resume lecture after answering
      setIsPaused(false);
      if (!res.data.is_finished) {
        setStatus('lecturing');
        setTimeout(() => fetchNextChunk(sessionId), 500);
      } else {
        setStatus('finished');
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to answer');
      setIsPaused(false);
      setStatus('lecturing');
    }
  };

  // ─── Pause / Resume ───
  const handlePauseResume = () => {
    if (isPaused) {
      // Resume
      setIsPaused(false);
      if (sessionId && status !== 'finished') {
        fetchNextChunk(sessionId);
      }
    } else {
      // Pause
      setIsPaused(true);
      if (audioRef.current) {
        audioRef.current.pause();
        setIsSpeaking(false);
      }
    }
  };

  // ─── Mute / Unmute ───
  const handleMuteToggle = () => {
    setIsMuted(!isMuted);
    if (!isMuted && audioRef.current) {
      audioRef.current.pause();
      setIsSpeaking(false);
    }
  };

  // ─── Stop session ───
  const handleStop = async () => {
    if (sessionId) {
      try { await stopSession(sessionId); } catch { /* ignore */ }
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setStatus('finished');
    setIsSpeaking(false);
    setIsPaused(false);
  };

  // ─── Render: Idle State ───
  if (status === 'idle') {
    return (
      <div className="w-[20%] border-l-2 border-border bg-card flex flex-col">
        <div className="px-4 py-3 border-b border-border bg-gradient-to-br from-primary/5 to-accent/5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 bg-muted-foreground rounded-full" />
            <h4 className="mb-0 text-sm">Dr. Nova</h4>
          </div>
          <p className="text-xs text-muted-foreground">AI Teaching Assistant</p>
        </div>

        {/* Avatar */}
        <div className="px-4 py-8 flex flex-col items-center border-b border-border bg-gradient-to-br from-primary/5 via-secondary/5 to-accent/5">
          <div className="relative mb-6">
            <div className="absolute inset-0 bg-gradient-to-br from-secondary to-accent rounded-full blur-xl opacity-20" />
            <div className="relative w-32 h-32 rounded-full bg-gradient-to-br from-primary via-secondary to-accent p-1 shadow-xl">
              <div className="w-full h-full rounded-full bg-background flex items-center justify-center overflow-hidden">
                <BookOpen size={48} className="text-secondary opacity-60" />
              </div>
            </div>
          </div>

          <button
            onClick={handleStart}
            className="w-full py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2 text-sm"
          >
            <Play size={16} />
            <span>Start Session</span>
          </button>

          {error && (
            <p className="text-xs text-red-400 mt-2 text-center">{error}</p>
          )}
        </div>

        {/* Topics Preview */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          <div className="text-xs text-muted-foreground mb-2 font-semibold uppercase tracking-wider">
            Topics to cover
          </div>
          <div className="space-y-2">
            {defaultTopics.map((t, i) => (
              <div key={i} className="bg-muted/20 rounded-lg p-3 border border-border">
                <div className="text-sm font-medium text-foreground">{t.name}</div>
                {t.subtopics.length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {t.subtopics.map((s, j) => (
                      <div key={j} className="text-xs text-muted-foreground pl-3">
                        • {s}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ─── Render: Loading State ───
  if (status === 'loading') {
    return (
      <div className="w-[20%] border-l-2 border-border bg-card flex flex-col items-center justify-center">
        <Loader2 size={40} className="animate-spin text-secondary mb-4" />
        <p className="text-sm text-muted-foreground">Starting session...</p>
      </div>
    );
  }

  // ─── Render: Active / Finished State ───
  return (
    <div className="w-[20%] border-l-2 border-border bg-card flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-gradient-to-br from-primary/5 to-accent/5">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${
              status === 'finished' ? 'bg-accent' :
              status === 'answering' ? 'bg-amber-400 animate-pulse' :
              isPaused ? 'bg-yellow-400' :
              'bg-green-500 animate-pulse'
            }`} />
            <h4 className="mb-0 text-sm">Dr. Nova</h4>
          </div>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
            status === 'finished' ? 'bg-accent/10 text-accent' :
            status === 'answering' ? 'bg-amber-400/10 text-amber-400' :
            isPaused ? 'bg-yellow-400/10 text-yellow-400' :
            'bg-green-500/10 text-green-500'
          }`}>
            {status === 'finished' ? 'Done' :
             status === 'answering' ? 'Answering' :
             isPaused ? 'Paused' : 'Lecturing'}
          </span>
        </div>

        {/* Progress Bar */}
        <div className="mt-2">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-muted-foreground">Progress</span>
            <span className="text-[10px] font-mono text-foreground">{Math.round(progress)}%</span>
          </div>
          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-secondary to-accent rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      </div>

      {/* Compact Avatar + Controls */}
      <div className="px-4 py-3 flex items-center gap-3 border-b border-border">
        {/* Mini avatar */}
        <div className="relative flex-shrink-0">
          <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary via-secondary to-accent p-0.5 shadow-md">
            <div className="w-full h-full rounded-full bg-background flex items-center justify-center">
              <BookOpen size={18} className="text-secondary" />
            </div>
          </div>
          {/* Speaking indicator */}
          {isSpeaking && (
            <div className="absolute -bottom-0.5 -right-0.5 flex gap-0.5 bg-card rounded-full px-1.5 py-0.5 border border-border shadow">
              <div className="w-0.5 h-2 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '0ms' }} />
              <div className="w-0.5 h-3 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '150ms' }} />
              <div className="w-0.5 h-2 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
            </div>
          )}
        </div>

        {/* Controls */}
        <div className="flex items-center gap-1.5">
          {status !== 'finished' && (
            <button
              onClick={handlePauseResume}
              className={`p-2 rounded-lg border-2 transition-all ${
                !isPaused
                  ? 'border-secondary bg-secondary text-white shadow-md'
                  : 'border-border bg-card hover:border-secondary'
              }`}
              title={isPaused ? 'Resume' : 'Pause'}
            >
              {isPaused ? <Play size={14} /> : <Pause size={14} />}
            </button>
          )}
          <button
            onClick={handleMuteToggle}
            className="p-2 rounded-lg border-2 border-border bg-card hover:border-secondary transition-colors"
            title={isMuted ? 'Unmute' : 'Mute'}
          >
            {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </button>
          {status !== 'finished' && (
            <button
              onClick={handleStop}
              className="p-2 rounded-lg border-2 border-border bg-card hover:border-red-400 transition-colors text-muted-foreground hover:text-red-400"
              title="End Session"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Current Topic */}
      {currentTopic && status !== 'finished' && (
        <div className="px-4 py-3 border-b border-border bg-muted/10">
          <div className="text-[10px] text-muted-foreground mb-0.5 uppercase tracking-wider">Currently Explaining</div>
          <p className="text-sm font-semibold text-foreground leading-snug">{currentTopic}</p>
          {currentSubtopic && (
            <p className="text-xs text-secondary mt-0.5">{currentSubtopic}</p>
          )}
        </div>
      )}

      {/* Transcript */}
      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="space-y-2.5">
          {transcript.map((entry, i) => (
            <div
              key={i}
              className={`rounded-lg p-3 ${
                entry.role === 'student'
                  ? 'bg-secondary/10 border-l-2 border-secondary ml-4'
                  : entry.isAnswer
                  ? 'bg-amber-500/5 border-l-2 border-amber-400'
                  : 'bg-primary/5 border-l-2 border-primary'
              }`}
            >
              {entry.role === 'student' && (
                <div className="text-[10px] text-secondary font-semibold mb-1">You asked:</div>
              )}
              {entry.isAnswer && (
                <div className="text-[10px] text-amber-400 font-semibold mb-1">Answer:</div>
              )}
              <p className="text-xs text-foreground/80 leading-relaxed">{entry.text}</p>
              {entry.subtopic && entry.role === 'tutor' && !entry.isAnswer && (
                <span className="text-[10px] text-muted-foreground mt-1 block">
                  📍 {entry.subtopic}
                </span>
              )}
            </div>
          ))}

          {/* Typing indicator when loading */}
          {(status === 'lecturing' && !isSpeaking && transcript.length > 0 && !isPaused) && (
            <div className="flex items-center gap-1.5 px-3 py-2">
              <div className="w-1.5 h-1.5 bg-secondary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-1.5 h-1.5 bg-secondary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div className="w-1.5 h-1.5 bg-secondary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          )}

          {/* Finished message */}
          {status === 'finished' && (
            <div className="bg-accent/10 rounded-lg p-4 text-center border border-accent/20">
              <CheckCircle2 size={24} className="text-accent mx-auto mb-2" />
              <p className="text-sm font-semibold text-foreground">Session Complete!</p>
              <p className="text-xs text-muted-foreground mt-1">All topics have been covered.</p>
              <button
                onClick={() => {
                  setStatus('idle');
                  setSessionId(null);
                  setTranscript([]);
                  setProgress(0);
                  setCurrentTopic(null);
                  setCurrentSubtopic(null);
                  setError(null);
                }}
                className="mt-3 px-4 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-lg text-xs font-semibold hover:shadow-md transition-all"
              >
                Start New Session
              </button>
            </div>
          )}

          <div ref={transcriptEndRef} />
        </div>
      </div>

      {/* Question Input or Ask Button */}
      {status !== 'finished' && (
        <div className="p-3 border-t border-border">
          {showQuestionInput ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={questionText}
                  onChange={(e) => setQuestionText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleAskQuestion();
                    if (e.key === 'Escape') setShowQuestionInput(false);
                  }}
                  placeholder="Type your question..."
                  className="flex-1 px-3 py-2 bg-muted/30 border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-secondary"
                  autoFocus
                />
                <button
                  onClick={handleAskQuestion}
                  disabled={!questionText.trim()}
                  className="p-2 rounded-lg bg-gradient-to-r from-secondary to-accent text-white disabled:opacity-40 hover:shadow-md transition-all"
                >
                  <Send size={14} />
                </button>
              </div>
              <button
                onClick={() => setShowQuestionInput(false)}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => {
                setShowQuestionInput(true);
                // Pause while asking
                if (!isPaused) handlePauseResume();
              }}
              className="w-full py-2.5 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2 text-sm"
            >
              <MessageCircle size={14} />
              <span>Ask Question</span>
            </button>
          )}

          {error && (
            <p className="text-xs text-red-400 mt-2 text-center">{error}</p>
          )}
        </div>
      )}
    </div>
  );
}
