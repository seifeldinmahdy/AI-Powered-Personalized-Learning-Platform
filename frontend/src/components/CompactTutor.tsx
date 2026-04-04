import { Mic, MicOff, Volume2, VolumeX, MessageCircle, Pause, Play, Send, Loader2, Code2 } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import {
  startTutorSession,
  continueTutorSession,
  askTutor,
  stopTutorSession,
  transcribeAudio,
  classifyIntent,
  askRag,
} from '../services/tutor';

interface TranscriptEntry {
  role: 'tutor' | 'student';
  text: string;
  topic?: string;
  sources?: { book: string; page_start: number; page_end: number }[];
}

interface CompactTutorProps {
  lessonTitle?: string;
  subtopics?: string[];
}

export function CompactTutor({ lessonTitle, subtopics = [] }: CompactTutorProps) {
  const navigate = useNavigate();
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [isFinished, setIsFinished] = useState(false);
  const [progress, setProgress] = useState(0);
  const [showChat, setShowChat] = useState(false);
  const [question, setQuestion] = useState('');
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState('');
  const [started, setStarted] = useState(false);

  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioBlobUrlRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const isMutedRef = useRef(false);
  const isPausedRef = useRef(false);
  const isFinishedRef = useRef(false);
  const isLoadingRef = useRef(false);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<{ stop: () => void } | null>(null);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      audioRef.current?.pause();
      if (audioBlobUrlRef.current) URL.revokeObjectURL(audioBlobUrlRef.current);
      if (sessionIdRef.current) stopTutorSession(sessionIdRef.current);
    };
  }, []);

  function setAudioSrc(base64: string) {
    const audio = audioRef.current;
    if (!audio) return;
    if (audioBlobUrlRef.current) {
      URL.revokeObjectURL(audioBlobUrlRef.current);
      audioBlobUrlRef.current = null;
    }
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    audioBlobUrlRef.current = URL.createObjectURL(blob);
    audio.muted = isMutedRef.current;
    audio.src = audioBlobUrlRef.current;
    // Don't autoplay if user has paused
    if (isPausedRef.current) {
      setIsSpeaking(false);
      return;
    }
    audio.play().catch(() => setIsSpeaking(false));
  }

  async function fetchAndPlay(sid: string) {
    if (isFinishedRef.current || isLoadingRef.current) return;
    isLoadingRef.current = true;
    setIsLoading(true);
    try {
      const chunk = await continueTutorSession(sid, true);
      setProgress(chunk.progress);

      if (chunk.text) {
        setTranscript((prev) => [
          ...prev,
          { role: 'tutor', text: chunk.text, topic: chunk.subtopic || chunk.topic },
        ]);
      }

      if (chunk.audio_base64) {
        setAudioSrc(chunk.audio_base64);
        setIsSpeaking(true);
      } else {
        setIsSpeaking(false);
      }

      if (chunk.is_finished) {
        isFinishedRef.current = true;
        setIsFinished(true);
      }
    } catch {
      setError('Failed to get lecture content.');
      setIsSpeaking(false);
    } finally {
      isLoadingRef.current = false;
      setIsLoading(false);
    }
  }

  const handleStart = async () => {
    if (!lessonTitle || !audioRef.current) return;
    setStarted(true);
    setIsLoading(true);
    isLoadingRef.current = true;

    // Step 1: unlock audio synchronously in the click handler
    const audio = audioRef.current;
    audio.src = '';
    try { await audio.play(); } catch { /* expected */ }
    audio.pause();

    // Step 2: fetch session + chunk (async, after unlock)
    try {
      const session = await startTutorSession(lessonTitle, subtopics);
      sessionIdRef.current = session.session_id;
      isLoadingRef.current = false;
      setIsLoading(false);
      await fetchAndPlay(session.session_id);
    } catch {
      setError('Dr. Nova is unavailable right now.');
      setIsLoading(false);
      isLoadingRef.current = false;
    }
  };

  const handlePlayPause = () => {
    const audio = audioRef.current;
    console.log('[Pause] audio:', !!audio, 'isPausedRef:', isPausedRef.current, 'paused:', audio?.paused, 'src:', audio?.src?.slice(0,40));
    if (!audio) return;
    if (isPausedRef.current) {
      isPausedRef.current = false;
      setIsPaused(false);
      audio.play().catch((e) => console.log('[Pause] play error:', e));
      setIsSpeaking(true);
    } else {
      isPausedRef.current = true;
      setIsPaused(true);
      audio.pause();
      setIsSpeaking(false);
    }
  };

  const handleNext = () => {
    if (!sessionIdRef.current || isLoadingRef.current || isFinishedRef.current) return;
    audioRef.current?.pause();
    setIsSpeaking(false);
    isPausedRef.current = false;
    setIsPaused(false);
    fetchAndPlay(sessionIdRef.current);
  };

  const handleMute = () => {
    if (!audioRef.current) return;
    const next = !isMutedRef.current;
    isMutedRef.current = next;
    setIsMuted(next);
    audioRef.current.muted = next;
  };

  const handleAskQuestion = async (overrideQuestion?: string) => {
    const q = (overrideQuestion ?? question).trim();
    if (!sessionIdRef.current || !q || isAsking) return;
    setQuestion('');

    // If lecture audio is currently playing, pause it
    if (isSpeaking && !isPausedRef.current) {
      audioRef.current?.pause();
      isPausedRef.current = true;
      setIsPaused(true);
      setIsSpeaking(false);
    }

    setIsAsking(true);
    setTranscript((prev) => [...prev, { role: 'student', text: q }]);

    try {
      // Keyword override before calling the model — catches short/ambiguous phrases
      const repeatKeywords = ['repeat', 'again', 'replay', 'rewind', 'say that again', 'once more', 'didn\'t get that', 'missed that'];
      const paceKeywords = ['slow down', 'too fast', 'speed up', 'faster', 'slower', 'skip'];
      const emotionKeywords = ['confused', 'lost', 'frustrated', 'don\'t understand', 'hard', 'difficult', 'give up', 'struggling'];
      const lower = q.toLowerCase();
      let intent: import('../services/tutor').IntentName;
      if (repeatKeywords.some(k => lower.includes(k))) {
        intent = 'Repeat/clarification';
      } else if (paceKeywords.some(k => lower.includes(k))) {
        intent = 'Pace-Related';
      } else if (emotionKeywords.some(k => lower.includes(k))) {
        intent = 'Emotional-State';
      } else {
        // Format context to match the model's training format so it can
        // correctly judge what is on-topic vs off-topic for this lesson.
        const sessionContext = lessonTitle
          ? `topic:${lessonTitle} | prev:${lessonTitle} | emotion:neutral | pace:normal`
          : '';
        intent = await classifyIntent(q, sessionContext);
      }

      // Handle each intent differently
      const resumeLecture = () => {
        if (audioRef.current && isPausedRef.current) {
          audioRef.current.play().catch(() => {});
          isPausedRef.current = false;
          setIsPaused(false);
          setIsSpeaking(true);
        }
      };

      if (intent === 'Off-Topic Question') {
        setTranscript((prev) => [...prev, {
          role: 'tutor',
          text: "That seems off-topic. Let's stay focused on the current lesson. Feel free to ask anything related to what we're covering!",
          topic: 'Off-Topic',
        }]);
        resumeLecture();
        setIsAsking(false);
        return;
      }

      if (intent === 'Emotional-State') {
        // Re-explain the current topic instead of just encouraging
        const res = await askTutor(
          sessionIdRef.current,
          `The student said: "${q}". Please offer brief encouragement and re-explain the current topic in a simpler way.`,
          !isMutedRef.current,
        );
        setTranscript((prev) => [...prev, { role: 'tutor', text: res.answer, topic: 'Encouragement' }]);
        if (res.audio_base64) {
          isPausedRef.current = false;
          setIsPaused(false);
          setAudioSrc(res.audio_base64);
          setIsSpeaking(true);
        }
        setIsAsking(false);
        return;
      }

      if (intent === 'Pace-Related') {
        setTranscript((prev) => [...prev, {
          role: 'tutor',
          text: "Got it! You can use the Pause button to take a break or Next to skip ahead. I'll keep going at your pace.",
          topic: 'Pace',
        }]);
        resumeLecture();
        setIsAsking(false);
        return;
      }

      if (intent === 'Repeat/clarification') {
        if (audioBlobUrlRef.current && audioRef.current) {
          // If audio already ended, replay from start; otherwise just unpause
          if (audioRef.current.ended || audioRef.current.currentTime === 0) {
            audioRef.current.currentTime = 0;
          }
          audioRef.current.play().catch(() => {});
          setIsSpeaking(true);
          isPausedRef.current = false;
          setIsPaused(false);
          setTranscript((prev) => [...prev, {
            role: 'tutor',
            text: "Sure! Let me repeat that for you.",
            topic: 'Repeat',
          }]);
          setIsAsking(false);
          return;
        }
        // Fallback: ask tutor to re-explain if no audio cached
      }

      // On-Topic Question (or Repeat/clarification fallback)
      // Try RAG first to ground the answer in textbook content
      let ragContext = '';
      let ragSources: { book: string; page_start: number; page_end: number }[] = [];
      try {
        const ragRes = await askRag(q, lessonTitle);
        // Only use RAG context if it found real sources (not the "could not find" fallback)
        if (ragRes.answer && ragRes.sources.length > 0 && !ragRes.answer.includes('could not find')) {
          ragContext = `\n\nRelevant textbook context:\n${ragRes.answer}`;
          ragSources = ragRes.sources.map(s => ({ book: s.book, page_start: s.page_start, page_end: s.page_end }));
        }
      } catch {
        // RAG unavailable — fall back to pure LLM
      }

      const augmentedQuestion = ragContext ? `${q}${ragContext}` : q;
      const res = await askTutor(sessionIdRef.current, augmentedQuestion, !isMutedRef.current);
      setTranscript((prev) => [...prev, {
        role: 'tutor',
        text: res.answer,
        topic: 'Answer',
        sources: ragSources.length > 0 ? ragSources : undefined,
      }]);
      if (res.audio_base64) {
        isPausedRef.current = false;
        setIsPaused(false);
        setAudioSrc(res.audio_base64);
        setIsSpeaking(true);
      }
    } catch {
      setTranscript((prev) => [...prev, {
        role: 'tutor',
        text: 'Sorry, I could not process your question.',
      }]);
    } finally {
      setIsAsking(false);
    }
  };

  const handleVoiceInput = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Use Web Audio API to capture raw PCM, then encode as WAV
      // (avoids webm format which requires ffmpeg on the server)
      const audioCtx = new AudioContext({ sampleRate: 16000 });
      const source = audioCtx.createMediaStreamSource(stream);
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      const pcmChunks: Float32Array[] = [];

      processor.onaudioprocess = (e) => {
        pcmChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(audioCtx.destination);

      // Store stop function in ref so button click can trigger it
      const stopRecording = async () => {
        stream.getTracks().forEach((t) => t.stop());
        processor.disconnect();
        source.disconnect();
        await audioCtx.close();
        setIsRecording(false);
        setIsTranscribing(true);
        setShowChat(true);

        try {
          // Combine all PCM chunks
          const totalLength = pcmChunks.reduce((s, c) => s + c.length, 0);
          const pcm = new Float32Array(totalLength);
          let offset = 0;
          for (const chunk of pcmChunks) { pcm.set(chunk, offset); offset += chunk.length; }

          // Encode as 16-bit PCM WAV
          const numSamples = pcm.length;
          const sampleRate = 16000;
          const buffer = new ArrayBuffer(44 + numSamples * 2);
          const view = new DataView(buffer);
          const write = (o: number, s: string) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
          write(0, 'RIFF'); view.setUint32(4, 36 + numSamples * 2, true);
          write(8, 'WAVE'); write(12, 'fmt '); view.setUint32(16, 16, true);
          view.setUint16(20, 1, true); view.setUint16(22, 1, true);
          view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
          view.setUint16(32, 2, true); view.setUint16(34, 16, true);
          write(36, 'data'); view.setUint32(40, numSamples * 2, true);
          for (let i = 0; i < numSamples; i++) {
            view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
          }

          const blob = new Blob([buffer], { type: 'audio/wav' });
          const text = await transcribeAudio(blob);
          setQuestion(text);
        } catch {
          setError('Failed to transcribe voice input.');
        } finally {
          setIsTranscribing(false);
        }
      };

      // Override mediaRecorderRef to store the stop function
      mediaRecorderRef.current = { stop: stopRecording } as unknown as MediaRecorder;
      setIsRecording(true);
    } catch {
      setError('Microphone access denied.');
    }
  };

  return (
    <div className="w-[35%] min-w-0 border-l-2 border-border bg-card flex flex-col overflow-hidden">
      <audio
        ref={audioRef}
        onEnded={() => {
          setIsSpeaking(false);
          isPausedRef.current = false;
          setIsPaused(false);
        }}
        style={{ display: 'none' }}
      />

      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-gradient-to-br from-primary/5 to-accent/5">
        <div className="flex items-center gap-2 mb-1">
          <div className={`w-2 h-2 rounded-full ${error ? 'bg-red-500' : isFinished ? 'bg-muted-foreground' : started ? 'bg-green-500 animate-pulse' : 'bg-yellow-400'}`} />
          <h4 className="mb-0 text-sm">Dr. Nova</h4>
          {progress > 0 && (
            <span className="ml-auto text-xs text-muted-foreground">{progress}%</span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">AI Teaching Assistant</p>
      </div>

      {/* Avatar */}
      <div className={`px-4 flex flex-col items-center border-b border-border bg-gradient-to-br from-primary/5 via-secondary/5 to-accent/5 ${started ? 'py-2' : 'py-4'}`}>
        <div className={`relative ${started ? 'mb-2' : 'mb-3'}`}>
          <div className="absolute inset-0 bg-gradient-to-br from-secondary to-accent rounded-full blur-xl opacity-20 pointer-events-none" />
          <div className={`relative rounded-full bg-gradient-to-br from-primary via-secondary to-accent p-1 shadow-xl ${started ? 'w-16 h-16' : 'w-24 h-24'}`}>
            <div className="w-full h-full rounded-full bg-background flex items-center justify-center overflow-hidden">
              <svg viewBox="0 0 200 200" className={started ? 'w-12 h-12' : 'w-20 h-20'} fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="100" cy="70" r="30" fill="url(#grad1)" />
                <ellipse cx="100" cy="135" rx="38" ry="48" fill="url(#grad2)" />
                <path d="M 68 108 Q 48 118 50 138" stroke="url(#grad2)" strokeWidth="14" strokeLinecap="round" fill="none" />
                <path d="M 132 108 Q 152 118 150 138" stroke="url(#grad2)" strokeWidth="14" strokeLinecap="round" fill="none" />
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
          {isSpeaking && !isPaused && (
            <div className="absolute -bottom-1 -right-1 flex gap-0.5 bg-card rounded-full px-2 py-1 border border-border shadow-md">
              <div className="w-1 h-3 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '0ms' }} />
              <div className="w-1 h-4 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '150ms' }} />
              <div className="w-1 h-3 bg-secondary rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
            </div>
          )}
          {isLoading && (
            <div className="absolute -bottom-1 -right-1 bg-card rounded-full p-1 border border-border shadow-md">
              <Loader2 size={14} className="animate-spin text-secondary" />
            </div>
          )}
        </div>

        {/* Controls */}
        {!started ? (
          <button
            onClick={handleStart}
            disabled={isLoading}
            className="px-6 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm disabled:opacity-60"
          >
            {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            <span>{isLoading ? 'Preparing...' : 'Start Lecture'}</span>
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <button
              onClick={handlePlayPause}
              disabled={isFinished}
              className={`p-2 rounded-lg border-2 transition-all disabled:opacity-40 ${
                !isPaused ? 'border-secondary bg-secondary text-white shadow-md' : 'border-border bg-card hover:border-secondary'
              }`}
              title={isPaused ? 'Resume' : 'Pause'}
            >
              {isPaused ? <Play size={16} /> : <Pause size={16} />}
            </button>

            <button
              onClick={handleNext}
              disabled={isLoading || isFinished}
              className="p-2 rounded-lg border-2 border-border bg-card hover:border-secondary transition-colors disabled:opacity-40 text-xs font-semibold px-3"
            >
              Next
            </button>

            <button
              onClick={handleMute}
              className="p-2 rounded-lg border-2 border-border bg-card hover:border-secondary transition-colors"
              title={isMuted ? 'Unmute' : 'Mute'}
            >
              {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
            </button>
          </div>
        )}

        {isFinished && (
          <div className="flex flex-col items-center gap-1 mt-1">
            <p className="text-xs text-muted-foreground">Lecture complete</p>
            <button
              onClick={() => navigate(`/practice/${encodeURIComponent(lessonTitle || 'Programming')}`, { state: { topic: lessonTitle } })}
              className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold text-sm hover:shadow-lg transition-all"
            >
              <Code2 size={15} />
              Practice Now
            </button>
          </div>
        )}
      </div>

      {/* Current Topic */}
      <div className="px-4 py-2 border-b border-border bg-muted/20">
        <div className="text-xs text-muted-foreground mb-0.5">Currently Explaining:</div>
        <p className="text-sm font-semibold text-foreground leading-snug">
          {lessonTitle || 'Lesson Content'}
        </p>
      </div>

      {/* Transcript */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {error && (
          <div className="bg-destructive/10 rounded-lg p-3 border-l-2 border-destructive">
            <p className="text-xs text-destructive">{error}</p>
          </div>
        )}
        {!started && !error && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <p className="text-sm text-muted-foreground">Click "Start Lecture" to hear Dr. Nova explain this lesson.</p>
          </div>
        )}
        {started && transcript.length === 0 && !error && (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={24} className="animate-spin text-secondary" />
          </div>
        )}
        {transcript.map((entry, i) => (
          <div
            key={i}
            className={`rounded-lg p-4 ${
              entry.role === 'tutor'
                ? 'bg-primary/5 border-l-2 border-primary'
                : 'bg-secondary/10 border-l-2 border-secondary ml-4'
            }`}
          >
            {entry.role === 'student' && (
              <span className="text-sm font-semibold text-secondary block mb-1">You</span>
            )}
            {entry.topic && entry.role === 'tutor' && (
              <span className="text-sm font-semibold text-muted-foreground block mb-1">{entry.topic}</span>
            )}
            <p className="text-sm text-foreground/80 leading-relaxed">{entry.text}</p>
            {entry.sources && entry.sources.length > 0 && (
              <div className="mt-2 space-y-0.5">
                {entry.sources.map((s, si) => (
                  <span key={si} className="inline-block text-xs bg-secondary/10 text-secondary rounded px-2 py-0.5 mr-1">
                    📖 {s.book} p.{s.page_start}–{s.page_end}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={transcriptEndRef} />
      </div>

      {/* Ask Question */}
      {started && (
        <div className="p-4 border-t border-border space-y-2">
          {showChat ? (
            <div className="flex gap-2">
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAskQuestion(question)}
                placeholder="Ask Dr. Nova..."
                className="flex-1 text-sm px-3 py-2 rounded-xl border border-border bg-background focus:outline-none focus:border-secondary"
                disabled={isAsking}
              />
              <button
                onClick={() => handleAskQuestion()}
                disabled={!question.trim() || isAsking}
                className="p-2 bg-gradient-to-r from-secondary to-accent text-white rounded-xl disabled:opacity-50"
              >
                {isAsking ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowChat(true)}
              className="w-full py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2 text-sm"
            >
              <MessageCircle size={16} />
              <span>Ask Question</span>
            </button>
          )}
          <button
            onClick={handleVoiceInput}
            disabled={isTranscribing}
            className={`w-full py-2 border-2 rounded-xl transition-colors flex items-center justify-center gap-2 text-sm font-medium disabled:opacity-50 ${
              isRecording
                ? 'border-red-500 bg-red-50 text-red-600 animate-pulse'
                : 'border-border hover:border-secondary'
            }`}
          >
            {isTranscribing ? (
              <><Loader2 size={16} className="animate-spin" /><span>Transcribing…</span></>
            ) : isRecording ? (
              <><MicOff size={16} /><span>Stop Recording</span></>
            ) : (
              <><Mic size={16} /><span>Voice Input</span></>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
