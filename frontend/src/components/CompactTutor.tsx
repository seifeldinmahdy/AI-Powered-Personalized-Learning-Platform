import { Mic, Volume2, VolumeX, Pause, Play, Loader2, Code2 } from 'lucide-react';
import { NovaAvatar } from './NovaAvatar';
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import {
  startTutorSession,
  continueTutorSession,
  askTutor,
  stopTutorSession,
  transcribeAudio,
  analyzeSpeechEmotion,
} from '../services/tutor';
import { logEmotionEvent } from '../services/emotionLogger';
import type { EmotionEvent } from '../services/emotionLogger';
import type { SERResult } from '../services/tutor';

interface TranscriptEntry {
  role: 'tutor' | 'student';
  text: string;
  topic?: string;
}

export interface CompactTutorProps {
  lessonTitle?: string;
  subtopics?: string[];
  fusedEmotion?: string;
  currentSlideIndex?: number;
  currentSlideTitle?: string;
  onSessionStart?: () => void;
  onLatestSER?: (ser: SERResult) => void;
  studentProfileSummary?: string;
  isFloating?: boolean;
}

type MicState = 'idle' | 'recording' | 'processing';

export function CompactTutor({
  lessonTitle,
  subtopics = [],
  fusedEmotion,
  currentSlideIndex = 0,
  currentSlideTitle,
  onSessionStart,
  onLatestSER,
  studentProfileSummary,
  isFloating = false,
}: CompactTutorProps) {
  const navigate = useNavigate();
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [isFinished, setIsFinished] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [started, setStarted] = useState(false);
  const [micState, setMicState] = useState<MicState>('idle');

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioBlobUrlRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const isMutedRef = useRef(false);
  const isPausedRef = useRef(false);
  const isFinishedRef = useRef(false);
  const isLoadingRef = useRef(false);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const stopRecordingRef = useRef<(() => void) | null>(null);
  const currentSubtopicRef = useRef<string | undefined>(undefined);

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
    audio.play().catch(() => setIsSpeaking(false));
  }

  async function fetchAndPlay(sid: string) {
    if (isFinishedRef.current || isLoadingRef.current) return;
    isLoadingRef.current = true;
    setIsLoading(true);
    try {
      const chunk = await continueTutorSession(sid, true, fusedEmotion);
      setProgress(chunk.progress);
      currentSubtopicRef.current = chunk.subtopic || chunk.topic;

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

    // Notify parent (LiveSession) that the session started
    onSessionStart?.();

    // Step 2: fetch session + chunk (async, after unlock)
    try {
      const session = await startTutorSession(lessonTitle, subtopics, undefined, studentProfileSummary);
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
    if (!audioRef.current) return;
    if (isPausedRef.current) {
      isPausedRef.current = false;
      setIsPaused(false);
      audioRef.current.play().catch(() => { });
      setIsSpeaking(true);
    } else {
      isPausedRef.current = true;
      setIsPaused(true);
      audioRef.current.pause();
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

  // ─── Mic button: record → ASR + SER in parallel → ask tutor ───
  const handleMicClick = async () => {
    // If currently recording, stop
    if (micState === 'recording') {
      stopRecordingRef.current?.();
      return;
    }

    // Start recording
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Use Web Audio API to capture raw PCM → WAV (avoids webm/ffmpeg issues)
      const audioCtx = new AudioContext({ sampleRate: 16000 });
      const source = audioCtx.createMediaStreamSource(stream);
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      const pcmChunks: Float32Array[] = [];

      processor.onaudioprocess = (e) => {
        pcmChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(audioCtx.destination);

      const stopRecording = async () => {
        stream.getTracks().forEach((t) => t.stop());
        processor.disconnect();
        source.disconnect();
        await audioCtx.close();
        setMicState('processing');

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

          const audioBlob = new Blob([buffer], { type: 'audio/wav' });

          // Send to ASR + SER in parallel
          const [transcriptText, serResult] = await Promise.allSettled([
            transcribeAudio(audioBlob),
            analyzeSpeechEmotion(audioBlob),
          ]);

          const question = transcriptText.status === 'fulfilled' ? transcriptText.value : '';
          const ser: SERResult | null = serResult.status === 'fulfilled' ? serResult.value : null;

          // Notify parent of latest SER result
          if (ser) {
            onLatestSER?.(ser);
          }

          if (!question.trim()) {
            setError('Could not transcribe your voice. Please try again.');
            setMicState('idle');
            return;
          }

          if (!sessionIdRef.current) {
            setMicState('idle');
            return;
          }

          // Pause lecture audio if playing
          if (isSpeaking && !isPausedRef.current) {
            audioRef.current?.pause();
            isPausedRef.current = true;
            setIsPaused(true);
            setIsSpeaking(false);
          }

          // Show student question in transcript
          setTranscript((prev) => [...prev, { role: 'student', text: question }]);

          // Ask the tutor — include the student's emotional state
          const questionEmotion = ser?.emotion || fusedEmotion || undefined;
          const res = await askTutor(sessionIdRef.current, question, !isMutedRef.current, questionEmotion);
          setTranscript((prev) => [
            ...prev,
            { role: 'tutor', text: res.answer, topic: 'Answer' },
          ]);

          // Log emotion event for this question
          const emotionEvent: EmotionEvent = {
            timestamp: new Date().toISOString(),
            slide_index: currentSlideIndex,
            slide_title: currentSlideTitle,
            subtopic: currentSubtopicRef.current,
            ser_emotion: ser?.emotion,
            ser_confidence: ser?.confidence,
            fused_emotion: ser?.emotion || fusedEmotion || 'neutral',
            event_type: 'question',
            question_transcript: question,
            dr_nova_response_summary: res.answer.slice(0, 200),
          };
          logEmotionEvent(emotionEvent);

          // Play answer audio
          if (res.audio_base64) {
            setAudioSrc(res.audio_base64);
            setIsSpeaking(true);
            isPausedRef.current = false;
            setIsPaused(false);
          }
        } catch {
          setError('Failed to process your question.');
        } finally {
          setMicState('idle');
        }
      };

      stopRecordingRef.current = stopRecording;
      setMicState('recording');
    } catch {
      setError('Microphone access denied.');
    }
  };

  return (
    <div
      className={
        isFloating
          ? 'z-40 rounded-2xl border border-border/50 shadow-2xl overflow-hidden backdrop-blur-sm bg-card flex flex-col'
          : 'w-[30%] border-l-2 border-border bg-card flex flex-col'
      }
      style={isFloating ? {
        position: 'absolute',
        left: 12,
        top: 12,
        width: 300,
        maxHeight: '50vh',
        opacity: 0.97,
      } : undefined}
    >
      <audio
        ref={audioRef}
        onEnded={() => setIsSpeaking(false)}
        style={{ display: 'none' }}
      />

      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-gradient-to-br from-primary/5 to-accent/5">
        <div className="flex items-center gap-2 mb-1">
          <div className={`w-2 h-2 rounded-full ${error ? 'bg-red-500' : isFinished ? 'bg-muted-foreground' : started ? 'bg-green-500 animate-pulse' : 'bg-yellow-400'}`} />
          <h4 className="mb-0 text-sm">Dr. Nova</h4>

        </div>
        <p className="text-xs text-muted-foreground">AI Teaching Assistant</p>
      </div>

      {/* Avatar */}
      <div className={`flex flex-col items-center border-b border-border bg-gradient-to-br from-primary/5 via-secondary/5 to-accent/5 ${isFloating ? 'px-3 py-2' : 'px-4 py-4'}`}>
        <div className={isFloating ? 'mb-2' : 'mb-3'}>
          <NovaAvatar
            audioRef={audioRef}
            emotion={fusedEmotion}
            isSpeaking={isSpeaking && !isPaused}
            isLoading={isLoading}
            size={isFloating ? 56 : 80}
          />
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
              className={`p-2 rounded-lg border-2 transition-all disabled:opacity-40 ${!isPaused ? 'border-secondary bg-secondary text-white shadow-md' : 'border-border bg-card hover:border-secondary'
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
          <div className="flex flex-col items-center gap-2 mt-2">
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
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-3 space-y-3 min-h-0" style={{ overflowWrap: 'break-word', wordBreak: 'break-word' }}>
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
            className={`rounded-lg p-3 ${entry.role === 'tutor'
              ? 'bg-primary/5 border-l-2 border-primary'
              : 'bg-secondary/10 border-l-2 border-secondary ml-4'
              }`}
          >
            {entry.role === 'student' && (
              <span className="text-xs font-semibold text-secondary block mb-1">You</span>
            )}
            {entry.topic && entry.role === 'tutor' && (
              <span className="text-xs font-semibold text-muted-foreground block mb-1">{entry.topic}</span>
            )}
            <p className="text-xs text-foreground/80 leading-relaxed">{entry.text}</p>
          </div>
        ))}
        <div ref={transcriptEndRef} />
      </div>

      {/* Mic Button — replaces text input */}
      {started && (
        <div className="p-4 border-t border-border">
          <button
            onClick={handleMicClick}
            disabled={micState === 'processing'}
            className={`w-full py-3 rounded-xl font-semibold transition-all flex items-center justify-center gap-2 text-sm disabled:opacity-50 ${micState === 'recording'
              ? 'bg-red-400 text-white animate-pulse shadow-lg'
              : micState === 'processing'
                ? 'bg-secondary/10 text-secondary border-2 border-secondary'
                : 'bg-gradient-to-r from-secondary to-accent text-white hover:shadow-lg'
              }`}
          >
            {micState === 'processing' ? (
              <><Loader2 size={16} className="animate-spin" /><span>Processing…</span></>
            ) : micState === 'recording' ? (
              <><Mic size={16} /><span>Stop Recording</span></>
            ) : (
              <><Mic size={16} /><span>Ask with Voice</span></>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
