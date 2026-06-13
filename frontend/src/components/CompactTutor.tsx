import { Mic, MicOff, Volume2, VolumeX, MessageCircle, Pause, Play, Send, Loader2, Code2, GripHorizontal, Maximize2, Minimize2 } from 'lucide-react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router';
import {
  startTutorSession,
  continueTutorSession,
  askTutor,
  stopTutorSession,
  transcribeAudio,
  classifyIntent,
  askRag,
  analyzeSpeechEmotion,
  synthesizeAudio,
  setTutorPace,
  persistChatLog,
  type SERResult,
} from '../services/tutor';

import { fuseEmotions } from '../services/emotionFusion';
import { Nova3DAvatar } from './Nova3DAvatar';
import type { BlendshapeData } from '../services/tutor';

interface TranscriptEntry {
  role: 'tutor' | 'student';
  text: string;
  topic?: string;
  sources?: { book: string; page_start: number; page_end: number }[];
  // Set on on-topic answers: true = grounded in textbook passages, false =
  // answered without grounding (surface a "grounding unavailable" note).
  grounded?: boolean;
}

interface CompactTutorProps {
  lessonTitle?: string;
  lessonId?: number;
  courseId?: string;
  sessionId?: string;
  subtopics?: string[];
  fusedEmotion?: string;
  currentSlideIndex?: number;
  currentSlideTitle?: string;
  currentSlideContent?: string;
  onSessionStart?: () => void;
  onLatestSER?: (ser: SERResult) => void;
  onUpdateFusedEmotion?: (emotion: string) => void;
  onNextSlide?: () => void;
  studentProfileSummary?: string;
  isFloating?: boolean;
}

export function CompactTutor({
  lessonTitle,
  lessonId,
  courseId,
  sessionId,
  subtopics = [],
  fusedEmotion,
  currentSlideIndex = 0,
  currentSlideTitle,
  currentSlideContent,
  onSessionStart,
  onLatestSER,
  onUpdateFusedEmotion,
  onNextSlide,
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
  const [showChat, setShowChat] = useState(false);
  const [question, setQuestion] = useState('');
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState('');
  const [started, setStarted] = useState(false);
  const [tutorEmotion, setTutorEmotion] = useState('calm');
  const [currentBlendshapes, setCurrentBlendshapes] = useState<BlendshapeData | null>(null);

  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);

  // Draggable avatar state
  const [isDetached, setIsDetached] = useState(false);
  const [avatarPos, setAvatarPos] = useState({ x: 0, y: 0 });
  const [bubbleScale, setBubbleScale] = useState(1);
  const isDraggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const panelRef = useRef<HTMLDivElement>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioBlobUrlRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const isMutedRef = useRef(false);
  const isPausedRef = useRef(false);
  const isFinishedRef = useRef(false);
  const isLoadingRef = useRef(false);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<{ stop: () => void } | null>(null);
  const visitedSlidesRef = useRef<Set<number>>(new Set([0]));
  const currentSlideRef = useRef(0);  // tracks latest slide for staleness checks

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  // ── Drag: starts inline, becomes floating when dragged away, snaps back when dropped on panel ──
  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;

    // When first detaching, position the bubble at the cursor
    const startX = isDetached ? avatarPos.x : e.clientX;
    const startY = isDetached ? avatarPos.y : e.clientY;
    const offsetX = e.clientX - startX;
    const offsetY = e.clientY - startY;

    if (!isDetached) {
      setAvatarPos({ x: startX, y: startY });
      setIsDetached(true);
    }

    const onMove = (ev: MouseEvent) => {
      if (!isDraggingRef.current) return;
      // Clamp to viewport boundaries (40px margin for the bubble radius)
      const margin = 40;
      const clampedX = Math.max(margin, Math.min(window.innerWidth - margin, ev.clientX - offsetX));
      const clampedY = Math.max(margin, Math.min(window.innerHeight - margin, ev.clientY - offsetY));
      setAvatarPos({ x: clampedX, y: clampedY });
    };
    const onUp = (ev: MouseEvent) => {
      isDraggingRef.current = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      // If dropped over the panel, snap back to docked
      const panel = panelRef.current;
      if (panel) {
        const rect = panel.getBoundingClientRect();
        if (ev.clientX >= rect.left && ev.clientX <= rect.right && ev.clientY >= rect.top && ev.clientY <= rect.bottom) {
          setIsDetached(false);
        }
      }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [avatarPos, isDetached]);

  // Reset to docked when switching modes
  useEffect(() => { setIsDetached(false); }, [isFloating]);

  // Handle auto-explain on new slide visit
  useEffect(() => {
    currentSlideRef.current = currentSlideIndex;  // always track latest slide
    if (!sessionIdRef.current || !currentSlideContent) return;

    if (!visitedSlidesRef.current.has(currentSlideIndex)) {
      visitedSlidesRef.current.add(currentSlideIndex);

      // Pause any ongoing lecture
      if (audioRef.current && !audioRef.current.paused) {
        audioRef.current.pause();
      }
      setIsSpeaking(false);

      // Trigger auto-explanation for the new slide
      handleAskQuestion(`Please explain this slide. Title: ${currentSlideTitle}\nContent: ${currentSlideContent}`, fusedEmotion, true, currentSlideIndex);
    }
  }, [currentSlideIndex, currentSlideContent, currentSlideTitle]);



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
      setTutorEmotion('calm');
      // Pass the latest fused emotion for tone adaptation
      const currentEmotion = fusedEmotion || 'neutral';
      const chunk = await continueTutorSession(sid, true, currentEmotion !== 'neutral' ? currentEmotion : undefined);
      setProgress(chunk.progress);

      if (chunk.text) {
        setTranscript((prev) => [
          ...prev,
          { role: 'tutor', text: chunk.text, topic: chunk.subtopic || chunk.topic },
        ]);
      }

      setCurrentBlendshapes(chunk.blendshapes || null);

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
      const session = await startTutorSession(lessonTitle, subtopics, undefined, studentProfileSummary, sessionId);
      sessionIdRef.current = session.session_id;
      isLoadingRef.current = false;
      setIsLoading(false);
      onSessionStart?.();
      await fetchAndPlay(session.session_id);
    } catch {
      setError('LearnPal is unavailable right now.');
      setIsLoading(false);
      isLoadingRef.current = false;
    }
  };

  const handlePlayPause = () => {
    const audio = audioRef.current;
    console.log('[Pause] audio:', !!audio, 'isPausedRef:', isPausedRef.current, 'paused:', audio?.paused, 'src:', audio?.src?.slice(0, 40));
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
    onNextSlide?.();
    fetchAndPlay(sessionIdRef.current);
  };

  const handleMute = () => {
    if (!audioRef.current) return;
    const next = !isMutedRef.current;
    isMutedRef.current = next;
    setIsMuted(next);
    audioRef.current.muted = next;
  };

  const handleAskQuestion = async (overrideQuestion?: string, overrideEmotion?: string, isAutoTrigger = false, triggeredForSlide?: number) => {
    const q = (overrideQuestion ?? question).trim();
    if (!sessionIdRef.current || !q || isAsking) return;

    // If this is a stale auto-trigger (student already moved past this slide), discard silently
    if (isAutoTrigger && triggeredForSlide !== undefined && triggeredForSlide !== currentSlideRef.current) {
      return;
    }

    setQuestion('');

    // If lecture audio is currently playing, pause it
    if (isSpeaking && !isPausedRef.current) {
      audioRef.current?.pause();
      isPausedRef.current = true;
      setIsPaused(true);
      setIsSpeaking(false);
    }

    setIsAsking(true);
    setTranscript((prev) => [
      ...prev,
      { role: 'student', text: isAutoTrigger ? `LearnPal, please explain this slide: ${currentSlideTitle}` : q }
    ]);

    try {
      // Keyword override before calling the model — catches short/ambiguous phrases
      const repeatKeywords = ['repeat', 'again', 'replay', 'rewind', 'say that again', 'once more', 'didn\'t get that', 'missed that'];
      const paceKeywords = ['slow down', 'too fast', 'speed up', 'faster', 'slower', 'skip'];
      const emotionKeywords = ['confused', 'lost', 'frustrated', 'don\'t understand', 'hard', 'difficult', 'give up', 'struggling'];
      const lower = q.toLowerCase();
      let intent: import('../services/tutor').IntentName = 'On-Topic Question';

      if (!isAutoTrigger) {
        if (repeatKeywords.some(k => lower.includes(k))) {
          intent = 'Repeat/clarification';
        } else if (paceKeywords.some(k => lower.includes(k))) {
          intent = 'Pace-Related';
        } else if (emotionKeywords.some(k => lower.includes(k))) {
          intent = 'Emotional-State';
        } else {
          // Pass the real backend session_id. The AI service fills the
          // classifier context from SharedSessionStore (live emotion / pace /
          // topic / ability), so it reflects real state instead of constants.
          // Falls back gracefully to empty context if the session isn't in the
          // store yet.
          intent = await classifyIntent(q, sessionIdRef.current ?? undefined);
        }
      }

      // Handle each intent differently
      const resumeLecture = () => {
        if (audioRef.current && isPausedRef.current) {
          audioRef.current.play().catch(() => { });
          isPausedRef.current = false;
          setIsPaused(false);
          setIsSpeaking(true);
        }
      };

      const currentEmotion = overrideEmotion || fusedEmotion || 'neutral';

      const logInteraction = (responseSummary?: string) => {
        // Backend handles interaction logging via SharedSessionStore
      };

      if (intent === 'Off-Topic Question') {
        const msg = "That seems off-topic. Let's stay focused on the current lesson. Feel free to ask anything related to what we're covering!";
        setTranscript((prev) => [...prev, {
          role: 'tutor',
          text: msg,
          topic: 'Off-Topic',
        }]);
        logInteraction(msg);
        setTutorEmotion('confused');
        setTutorEmotion('confused');

        try {
          const b64 = await synthesizeAudio(msg, 'calm', sessionIdRef.current);
          isPausedRef.current = false;
          setIsPaused(false);
          setAudioSrc(b64);
          setIsSpeaking(true);
        } catch {
          resumeLecture();
        }

        setIsAsking(false);
        return;
      }

      if (intent === 'Emotional-State') {
        // Re-explain the current topic instead of just encouraging
        const res = await askTutor(
          sessionIdRef.current,
          `The student said: "${q}". Please offer brief encouragement and re-explain the current topic in a simpler way.`,
          !isMutedRef.current,
          currentEmotion !== 'neutral' ? currentEmotion : undefined,
        );
        setTranscript((prev) => [...prev, { role: 'tutor', text: res.answer, topic: 'Encouragement' }]);
        logInteraction(res.answer);
        setTutorEmotion('happy');
        setTutorEmotion('happy');
        setCurrentBlendshapes(res.blendshapes || null);
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
        const textToAnalyze = q.toLowerCase();
        let targetPace: 'slow' | 'normal' | 'fast' = 'normal';
        if (textToAnalyze.includes('slow') || (textToAnalyze.includes('fast') && textToAnalyze.includes('too'))) {
          targetPace = 'slow';
        } else if (textToAnalyze.includes('fast') || (textToAnalyze.includes('slow') && textToAnalyze.includes('too'))) {
          targetPace = 'fast';
        }

        try {
          if (sessionIdRef.current) {
            await setTutorPace(sessionIdRef.current, targetPace);
          }
        } catch { /* ignore */ }

        const msg = targetPace === 'slow'
          ? "Got it! I will slow down my speaking pace for the rest of the session."
          : targetPace === 'fast'
            ? "Got it! I will speak faster for the rest of the session."
            : "Got it! You can use the Pause button to take a break or Next to skip ahead. I'll keep going at your pace.";

        setTranscript((prev) => [...prev, {
          role: 'tutor',
          text: msg,
          topic: 'Pace',
        }]);
        logInteraction(msg);
        setTutorEmotion('calm');

        try {
          const b64 = await synthesizeAudio(msg, 'calm', sessionIdRef.current);
          isPausedRef.current = false;
          setIsPaused(false);
          setAudioSrc(b64);
          setIsSpeaking(true);
        } catch {
          resumeLecture();
        }

        setIsAsking(false);
        return;
      }

      if (intent === 'Repeat/clarification') {
        if (audioBlobUrlRef.current && audioRef.current) {
          // If audio already ended, replay from start; otherwise just unpause
          if (audioRef.current.ended || audioRef.current.currentTime === 0) {
            audioRef.current.currentTime = 0;
          }
          audioRef.current.play().catch(() => { });
          setIsSpeaking(true);
          isPausedRef.current = false;
          setIsPaused(false);
          const msg = "Sure! Let me repeat that for you.";
          setTranscript((prev) => [...prev, {
            role: 'tutor',
            text: msg,
            topic: 'Repeat',
          }]);
          logInteraction(msg);
          setTutorEmotion('excited');
          setIsAsking(false);
          return;
        }
        // Fallback: ask tutor to re-explain if no audio cached
      }

      // On-Topic Question (or Repeat/clarification fallback)
      // Retrieve RAW textbook passages scoped to THIS course's corpus, and let
      // the tutor LLM ground on them directly (no pre-generated RAG answer, no
      // telephone game). courseId is required to resolve the corpus scope.
      let grounding: import('../services/tutor').RAGPassage[] = [];
      let ragSources: { book: string; page_start: number; page_end: number }[] = [];
      if (courseId) {
        try {
          const ragRes = await askRag(q, courseId);
          if (ragRes.grounded && ragRes.passages.length > 0) {
            grounding = ragRes.passages;
            ragSources = ragRes.passages.map(s => ({ book: s.book, page_start: s.page_start, page_end: s.page_end }));
          }
        } catch {
          // Retrieval unavailable — fall through to an ungrounded tutor answer.
        }
      }

      const res = await askTutor(
        sessionIdRef.current,
        q,
        !isMutedRef.current,
        currentEmotion !== 'neutral' ? currentEmotion : undefined,
        grounding.length > 0 ? grounding : undefined,
      );

      // Staleness guard: if this was an auto-explain and the student moved
      // to a different slide while we were waiting, discard the response.
      if (isAutoTrigger && triggeredForSlide !== undefined && triggeredForSlide !== currentSlideRef.current) {
        setIsAsking(false);
        return;
      }

      setTranscript((prev) => [...prev, {
        role: 'tutor',
        text: res.answer,
        topic: 'Answer',
        sources: ragSources.length > 0 ? ragSources : undefined,
        grounded: res.grounded,
      }]);

      if (lessonId) persistChatLog(lessonId, q, res.answer);
      logInteraction(res.answer);
      setTutorEmotion('happy');

      setCurrentBlendshapes(res.blendshapes || null);
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

    // If lecture audio is currently playing, pause it to prevent overlap
    if (isSpeaking && !isPausedRef.current) {
      audioRef.current?.pause();
      isPausedRef.current = true;
      setIsPaused(true);
      setIsSpeaking(false);
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

          // Run ASR + SER in parallel for efficiency
          const [text, serResult] = await Promise.allSettled([
            transcribeAudio(blob),
            analyzeSpeechEmotion(blob),
          ]);

          // Handle transcription result
          if (text.status === 'fulfilled') {
            setQuestion(text.value);
          } else {
            setError('Failed to transcribe voice input.');
          }

          let finalEmotion = fusedEmotion || 'neutral';

          // Handle SER result — report to LiveSession for fusion
          if (serResult.status === 'fulfilled' && onLatestSER) {
            onLatestSER(serResult.value);

            // Fuse SER with latest FER data
            try {
              const fusion = await fuseEmotions(
                {
                  fer_emotion: finalEmotion !== 'neutral' ? finalEmotion : undefined,
                  ser_emotion: serResult.value.emotion,
                  ser_confidence: serResult.value.confidence,
                },
                {
                  slide_index: currentSlideIndex,
                  slide_title: currentSlideTitle,
                  subtopic: lessonTitle,
                  session_id: sessionId,
                },
              );
              finalEmotion = fusion.fused_emotion;
              onUpdateFusedEmotion?.(fusion.fused_emotion);
            } catch {
              // Fusion/logging errors are non-critical
            }
          }

          if (text.status === 'fulfilled') {
            handleAskQuestion(text.value, finalEmotion);
          }
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
    <div
      ref={panelRef}
      style={isFloating ? { width: 320, maxWidth: '90vw', top: 16, left: 16, maxHeight: '80vh' } : { width: 320, minWidth: 320 }}
      className={`relative ${isFloating
        ? 'absolute rounded-2xl border border-border bg-card/95 backdrop-blur-md flex flex-col overflow-hidden shadow-2xl z-50'
        : 'shrink-0 border-l-2 border-border bg-card flex flex-col overflow-hidden'
        }`}>
      <audio
        ref={audioRef}
        onEnded={() => {
          setIsSpeaking(false);
          isPausedRef.current = false;
          setIsPaused(false);
        }}
        style={{ display: 'none' }}
      />

      {/* Header — always visible when docked */}
      {(!started || !isDetached) && (
        <div className="px-4 py-3 border-b border-border bg-gradient-to-br from-primary/5 to-accent/5">
          <div className="flex items-center gap-3 mb-1">
            <div className={`w-2 h-2 rounded-full shrink-0 ${error ? 'bg-red-500' : isFinished ? 'bg-muted-foreground' : started ? 'bg-green-500 animate-pulse' : 'bg-yellow-400'}`} />
            <h4 className="mb-0 text-sm font-bold bg-gradient-to-r from-primary via-secondary to-accent bg-clip-text text-transparent">LearnPal</h4>
            {progress > 0 && (
              <span className="ml-auto text-xs text-muted-foreground font-medium">{progress}%</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">AI Teaching Assistant</p>
        </div>
      )}

      {/* Avatar section — inline (docked) or floating (detached) */}
      {started && isDetached ? (
        /* ── DETACHED: floating bubble, position:fixed ── */
        <div
          onMouseDown={onDragStart}
          style={{
            position: 'fixed',
            top: avatarPos.y,
            left: avatarPos.x,
            transform: `translate(-50%, -50%)`,
            zIndex: 9999,
            cursor: 'grab',
            userSelect: 'none',
          }}
          className="flex flex-col items-center gap-2"
        >
          {/* Floating name pill */}
          <div className="flex items-center gap-2 bg-card/95 backdrop-blur-md px-3 py-1.5 border border-border shadow-lg mb-0.5 transition-all duration-300"
               style={{ borderRadius: 16 * bubbleScale, transform: `scale(${bubbleScale})`, transformOrigin: 'bottom center' }}>
            <div className={`w-2 h-2 rounded-full shrink-0 ${error ? 'bg-red-500' : isFinished ? 'bg-muted-foreground' : 'bg-green-500 animate-pulse'}`} />
            <span className="text-xs font-bold bg-gradient-to-r from-primary via-secondary to-accent bg-clip-text text-transparent">LearnPal</span>
            {progress > 0 && <span className="text-[10px] text-muted-foreground ml-1">{progress}%</span>}
            <GripHorizontal size={12} className="text-muted-foreground/40 ml-1" />
          </div>
          <div className="relative transition-all duration-300">
            <div className="absolute inset-0 bg-gradient-to-br from-secondary to-accent rounded-full blur-xl opacity-30 pointer-events-none transition-all duration-300" />
            <div className="relative rounded-full bg-gradient-to-br from-primary via-secondary to-accent p-1.5 shadow-2xl transition-all duration-300 flex items-center justify-center"
                 style={{ width: 144 * bubbleScale, height: 144 * bubbleScale }}>
              <Nova3DAvatar
                audioRef={audioRef}
                emotion={fusedEmotion || tutorEmotion}
                blendshapeData={currentBlendshapes}
                size={144 * bubbleScale - 12}
                isFloating={false}
              />
            </div>
          </div>
          {/* Controls */}
          <div onMouseDown={(e) => e.stopPropagation()} 
               style={{ transform: `scale(${bubbleScale})`, transformOrigin: 'top center' }}
               className="flex items-center gap-2.5 bg-card/95 backdrop-blur-md rounded-full px-4 py-2 border border-border shadow-lg mt-1 transition-all duration-300">
            <button onClick={handlePlayPause} disabled={isFinished}
              className={`p-2 rounded-full border transition-all disabled:opacity-40 flex items-center justify-center ${!isPaused ? 'border-secondary bg-secondary text-white shadow-md' : 'border-border bg-card hover:border-secondary'}`}
              title={isPaused ? 'Resume' : 'Pause'}>
              {isPaused ? <Play size={14} /> : <Pause size={14} />}
            </button>
            <button onClick={handleNext} disabled={isLoading || isFinished}
              className="p-2 rounded-full border border-border bg-card hover:border-secondary transition-colors disabled:opacity-40 text-xs font-semibold w-[64px] flex justify-center items-center">
              {isLoading ? <Loader2 size={14} className="animate-spin" /> : 'Next'}
            </button>
            <button onClick={handleMute}
              className="p-2 rounded-full border border-border bg-card hover:border-secondary transition-colors flex items-center justify-center"
              title={isMuted ? 'Unmute' : 'Mute'}>
              {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </button>
            <button onClick={() => setBubbleScale(s => s === 1 ? 1.5 : 1)}
              className="p-2 rounded-full border border-border bg-card hover:border-secondary transition-colors flex items-center justify-center"
              title={bubbleScale === 1 ? 'Enlarge' : 'Shrink'}>
              {bubbleScale === 1 ? <Maximize2 size={14} /> : <Minimize2 size={14} />}
            </button>
          </div>
          {isFinished && (
            <div className="flex flex-col items-center gap-1 mt-1">
              <p className="text-xs text-muted-foreground">Lecture complete</p>
            </div>
          )}
        </div>
      ) : (
        /* ── DOCKED: inline avatar with controls ── */
        <div className={`px-4 flex flex-col items-center border-b border-border bg-gradient-to-br from-primary/5 via-secondary/5 to-accent/5 ${started ? 'py-3' : 'py-4'}`}>
          <div
            className={`relative ${started ? 'mb-2 cursor-grab' : 'mb-3'}`}
            onMouseDown={started ? onDragStart : undefined}
            style={started ? { userSelect: 'none' } : undefined}
          >
            <div className="absolute inset-0 bg-gradient-to-br from-secondary to-accent rounded-full blur-xl opacity-20 pointer-events-none" />
            <div className="relative rounded-full bg-gradient-to-br from-primary via-secondary to-accent p-1.5 shadow-xl w-40 h-40">
              <Nova3DAvatar
                audioRef={audioRef}
                emotion={fusedEmotion || tutorEmotion}
                blendshapeData={currentBlendshapes}
                size={154}
                isFloating={isFloating}
              />
            </div>
          </div>
          {!started ? (
            <button
              onClick={handleStart}
              disabled={isLoading}
              className="px-6 py-2 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-2 text-sm disabled:opacity-60">
              {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              <span>{isLoading ? 'Preparing...' : 'Start Lecture'}</span>
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <button onClick={handlePlayPause} disabled={isFinished}
                className={`p-2 rounded-lg border-2 transition-all disabled:opacity-40 ${!isPaused ? 'border-secondary bg-secondary text-white shadow-md' : 'border-border bg-card hover:border-secondary'}`}
                title={isPaused ? 'Resume' : 'Pause'}>
                {isPaused ? <Play size={16} /> : <Pause size={16} />}
              </button>
              <button onClick={handleNext} disabled={isLoading || isFinished}
                className="p-2 rounded-lg border-2 border-border bg-card hover:border-secondary transition-colors disabled:opacity-40 text-xs font-semibold px-3 w-16 flex justify-center items-center">
                {isLoading ? <Loader2 size={16} className="animate-spin" /> : 'Next'}
              </button>
              <button onClick={handleMute}
                className="p-2 rounded-lg border-2 border-border bg-card hover:border-secondary transition-colors"
                title={isMuted ? 'Unmute' : 'Mute'}>
                {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
              </button>
            </div>
          )}
          {isFinished && (
            <div className="flex flex-col items-center gap-1 mt-1">
              <p className="text-xs text-muted-foreground">Lecture complete</p>
            </div>
          )}
        </div>
      )}

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
            <p className="text-sm text-muted-foreground">Click "Start Lecture" to hear LearnPal explain this lesson.</p>
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
                <span className="text-xs font-semibold text-secondary block mb-0.5">You</span>
              )}
              {entry.topic && entry.role === 'tutor' && (
                <span className="text-xs font-semibold text-muted-foreground block mb-0.5">{entry.topic}</span>
              )}
              <p className="text-sm text-foreground/80 leading-relaxed break-words whitespace-pre-wrap">{entry.text}</p>
              {entry.sources && entry.sources.length > 0 && (
                <div className="mt-1.5 space-y-0.5">
                  {entry.sources.map((s, si) => (
                    <span key={si} className="inline-block text-xs bg-secondary/10 text-secondary rounded px-2 py-0.5 mr-1">
                      📖 {s.book} p.{s.page_start}–{s.page_end}
                    </span>
                  ))}
                </div>
              )}
              {entry.role === 'tutor' && entry.grounded === false && (
                <div className="mt-1.5 text-xs text-amber-600/90 flex items-center gap-1">
                  ⚠ Grounding unavailable — answered from general knowledge, not the course textbook.
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
                placeholder="Ask LearnPal..."
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
            className={`w-full py-2 border-2 rounded-xl transition-colors flex items-center justify-center gap-2 text-sm font-medium disabled:opacity-50 ${isRecording
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
