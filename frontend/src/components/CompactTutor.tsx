import { Mic, MicOff, Volume2, VolumeX, MessageCircle, Pause, Play, Send, Loader2, Code2, GripHorizontal, Maximize2, Minimize2, ThumbsUp, ThumbsDown, Flag } from 'lucide-react';
import type { CSSProperties } from 'react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router';
import {
  startTutorSession,
  continueTutorSession,
  askTutor,
  stopTutorSession,
  abandonSocraticExchange,
  transcribeAudio,
  classifyIntent,
  askRag,
  analyzeSpeechEmotion,
  synthesizeAudio,
  setTutorPace,
  persistChatLog,
  getChatHistory,
  submitFeedback,
  fetchIntentChoices,
  type SERResult,
  type IntentPrediction,
  type FeedbackValue,
  type TutorStreamChunk,
  type IntentChoice,
} from '../services/tutor';

import { fuseEmotions } from '../services/emotionFusion';
import { Nova3DAvatar } from './Nova3DAvatar';
import type { BlendshapeData } from '../services/tutor';
import { INTENT_OPTIONS as FALLBACK_INTENT_OPTIONS } from '../lib/intents';
import type { IntentName } from '../services/tutor';

// Auto-explain chat logs are persisted with a compact, parseable marker so they
// can be rebuilt as labelled slide checkpoints when the session is reopened.
const SLIDE_EXPLAIN_RE = /^Please explain slide (\d+): ([\s\S]*)$/;
const slideExplainMarker = (slideNumber: number, title: string) =>
  `Please explain slide ${slideNumber}: ${title}`;

// Shared control-button styling (codex). Round pills for the floating bubble,
// rounded squares for the docked panel — both neutral with a blue active state.
const ctrlDotStyle: CSSProperties = {
  padding: 8, borderRadius: 999, border: '1px solid var(--hairline)', background: 'var(--bg-surface)',
  color: 'var(--text-primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
};
const ctrlDotActive: CSSProperties = { border: '1px solid var(--accent-primary)', background: 'var(--accent-primary)', color: '#fff' };
const ctrlBtnStyle: CSSProperties = {
  padding: 8, borderRadius: 8, border: '1px solid var(--steel)', background: 'var(--bg-surface)',
  color: 'var(--text-primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
};
const ctrlBtnActive: CSSProperties = { border: '1px solid var(--accent-primary)', background: 'var(--accent-primary)', color: '#fff' };

interface TranscriptEntry {
  role: 'tutor' | 'student' | 'checkpoint';
  text: string;
  topic?: string;
  // Checkpoint markers (auto-explain): which slide this explanation belongs to,
  // so the saved chat log reads as a sequence of clearly-labelled slide stops.
  slideNumber?: number;
  slideTitle?: string;
  is_streaming?: boolean;
  // Set on on-topic answers: true = grounded in textbook passages, false =
  // answered without grounding (surface a "grounding unavailable" note).
  grounded?: boolean;
  chatLogId?: number;
  feedback?: FeedbackValue | null;
  correctedIntent?: string | null;
  intent?: IntentPrediction | null;
}

interface CompactTutorProps {
  lessonTitle?: string;
  lessonId?: number;
  courseId?: string;
  sessionId?: string;
  subtopics?: string[];
  // Titles of lessons already completed before this one, so the tutor can call
  // back to them ("as we saw last lesson…").
  priorTopics?: string[];
  fusedEmotion?: string;
  currentSlideIndex?: number;
  currentSlideTitle?: string;
  currentSlideContent?: string;
  onSessionStart?: () => void;
  onLatestSER?: (ser: SERResult) => void;
  onUpdateFusedEmotion?: (emotion: string) => void;
  onNextSlide?: () => void;
  // Fired whenever the tutor starts/stops speaking, so the parent can lock slide
  // navigation while a chunk is being narrated.
  onSpeakingChange?: (speaking: boolean) => void;
  studentProfileSummary?: string;
  isFloating?: boolean;
}

export function CompactTutor({
  lessonTitle,
  lessonId,
  courseId,
  sessionId,
  subtopics = [],
  priorTopics = [],
  fusedEmotion,
  currentSlideIndex = 0,
  currentSlideTitle,
  currentSlideContent,
  onSessionStart,
  onLatestSER,
  onUpdateFusedEmotion,
  onNextSlide,
  onSpeakingChange,
  studentProfileSummary,
  isFloating = false,
}: CompactTutorProps) {
  const navigate = useNavigate();
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  // Surface speaking state to the parent (slide-nav lock) on every change.
  useEffect(() => {
    onSpeakingChange?.(isSpeaking);
  }, [isSpeaking, onSpeakingChange]);
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
  const [sessionContext, setSessionContext] = useState('');
  const [intentOptions, setIntentOptions] = useState<IntentChoice[]>(FALLBACK_INTENT_OPTIONS);
  const [correctingIndex, setCorrectingIndex] = useState<number | null>(null);
  const [correctingFeedback, setCorrectingFeedback] = useState<FeedbackValue | null>(null);
  const [selectedCorrectedIntent, setSelectedCorrectedIntent] = useState<string>('');
  const [showingDescriptionFor, setShowingDescriptionFor] = useState<string | null>(null);

  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);

  // Draggable avatar state
  const [isDetached, setIsDetached] = useState(false);
  const [avatarPos, setAvatarPos] = useState({ x: 0, y: 0 });
  const [bubbleScale, setBubbleScale] = useState(1);
  const isDraggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const panelRef = useRef<HTMLDivElement>(null);
  
  // Streaming Audio Context
  const audioContextRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef<number>(0);


  const sessionIdRef = useRef<string | null>(null);
  const isMutedRef = useRef(false);
  const isPausedRef = useRef(false);
  const isFinishedRef = useRef(false);
  const isLoadingRef = useRef(false);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<{ stop: () => void } | null>(null);
  const visitedSlidesRef = useRef<Set<number>>(new Set([0]));
  const currentSlideRef = useRef(0);  // tracks latest slide for staleness checks
  // True when the tutor's last turn asked the student something (background
  // probe / teach-back / Socratic guiding question). The student's next message
  // is then a REPLY, so we skip retrieval (no RAG for Socratic/probe answers).
  const awaitingResponseRef = useRef(false);

  const blendshapeTimeoutsRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());

  const stopCurrentAudio = useCallback(() => {
    blendshapeTimeoutsRef.current.forEach(id => clearTimeout(id));
    blendshapeTimeoutsRef.current.clear();
    
    activeSourcesRef.current.forEach(source => {
      try { source.stop(); } catch(e) {}
    });
    activeSourcesRef.current.clear();
    
    if (audioContextRef.current) {
      if (audioContextRef.current.state === 'suspended') {
        audioContextRef.current.resume();
      }
      nextStartTimeRef.current = audioContextRef.current.currentTime;
    } else {
      nextStartTimeRef.current = 0;
    }
    
    setIsSpeaking(false);
    isPausedRef.current = false;
    setIsPaused(false);
    setCurrentBlendshapes(null);
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  useEffect(() => {
    let mounted = true;
    fetchIntentChoices().then((choices) => {
      if (mounted && choices.length > 0) {
        setIntentOptions(choices);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  // ── Restore the durable chat log for this (course, session) ──────────────
  // The conversation survives session end, so revisiting an old session shows
  // the previous tutor chatlog. Auto-explain rows are rebuilt as labelled slide
  // checkpoints; everything else as plain student/tutor turns.
  useEffect(() => {
    if (!courseId || !lessonId) return;
    let cancelled = false;
    getChatHistory(courseId, lessonId).then((history) => {
      if (cancelled || history.length === 0) return;
      const restored: TranscriptEntry[] = [];
      for (const log of history) {
        const m = log.transcript_text.match(SLIDE_EXPLAIN_RE);
        if (m) {
          restored.push({ role: 'checkpoint', text: m[2], slideNumber: Number(m[1]), slideTitle: m[2] });
        } else {
          restored.push({ role: 'student', text: log.transcript_text });
        }
        restored.push({
          role: 'tutor',
          text: log.ai_response_text,
          chatLogId: log.id,
          feedback: log.feedback ?? null,
          correctedIntent: log.corrected_intent ?? null,
          intent: log.predicted_intent ? ({ intent_name: log.predicted_intent } as IntentPrediction) : null,
        });
      }
      // Seed the transcript with the restored history (before any new turns).
      setTranscript((prev) => (prev.length === 0 ? restored : prev));
    });
    return () => { cancelled = true; };
  }, [courseId, lessonId]);

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

      // Stop any ongoing lecture
      stopCurrentAudio();

      // If the student navigated away before resolving a Socratic follow-up,
      // abandon it explicitly so the tutor doesn't assess stale replies later.
      if (awaitingResponseRef.current) {
        abandonSocraticExchange(sessionIdRef.current);
        awaitingResponseRef.current = false;
      }

      // Trigger auto-explanation for the new slide
      handleAskQuestion(`Please explain this slide. Title: ${currentSlideTitle}\nContent: ${currentSlideContent}`, fusedEmotion, true, currentSlideIndex);
    }
  }, [currentSlideIndex, currentSlideContent, currentSlideTitle]);



  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (audioContextRef.current) audioContextRef.current.close();
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
      if (sessionIdRef.current) stopTutorSession(sessionIdRef.current);
    };
  }, []);


  const createOnChunk = (isQuestion: boolean = false) => {
    let isFirstChunk = true;
    return async (chunk: TutorStreamChunk) => {
      if (chunk.text_chunk) {
        setTranscript((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === 'tutor' && last.is_streaming) {
            const newPrev = [...prev.slice(0, -1)];
            newPrev.push({ ...last, text: last.text + ' ' + (chunk.text_chunk || '') });
            return newPrev;
          } else {
            return [...prev, { role: 'tutor', text: chunk.text_chunk || '', topic: chunk.subtopic || chunk.topic, is_streaming: true }];
          }
        });
      }

      if (chunk.audio_base64 && audioContextRef.current) {
        try {
          const binary = atob(chunk.audio_base64);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          
          const audioBuffer = await audioContextRef.current.decodeAudioData(bytes.buffer);
          const source = audioContextRef.current.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(audioContextRef.current.destination);
          activeSourcesRef.current.add(source);
          
          const currentTime = audioContextRef.current.currentTime;
          // Add a tiny buffer if we're falling behind
          const startTime = Math.max(currentTime + 0.05, nextStartTimeRef.current);
          
          const delayMs = Math.max(0, (startTime - currentTime) * 1000);
          
          if (chunk.blendshapes) {
            const tId = setTimeout(() => {
              setCurrentBlendshapes(chunk.blendshapes!);
              blendshapeTimeoutsRef.current.delete(tId);
            }, delayMs);
            blendshapeTimeoutsRef.current.add(tId);
          }
          
          source.start(startTime);
          nextStartTimeRef.current = startTime + audioBuffer.duration;
          setIsSpeaking(true);
          
          source.onended = () => {
            activeSourcesRef.current.delete(source);
            if (audioContextRef.current && audioContextRef.current.currentTime >= nextStartTimeRef.current - 0.1) {
              setIsSpeaking(false);
              setCurrentBlendshapes(null);
            }
          };
        } catch (e) {
          console.error('Failed to decode audio chunk', e);
        }
      }
    };
  };

  function finalizeTranscript() {
    setTranscript((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === 'tutor' && last.is_streaming) {
        return [...prev.slice(0, -1), { ...last, is_streaming: false }];
      }
      return prev;
    });
  }



  async function fetchAndPlay(sid: string) {
    if (isFinishedRef.current || isLoadingRef.current) return;
    isLoadingRef.current = true;
    setIsLoading(true);
    try {
      setTutorEmotion('calm');
      const currentEmotion = fusedEmotion || 'neutral';
      
      const onChunk = createOnChunk(false);
      const chunk = await continueTutorSession(sid, true, currentEmotion !== 'neutral' ? currentEmotion : undefined, onChunk);
      
      finalizeTranscript();
      setProgress(chunk.progress);
      awaitingResponseRef.current = !!chunk.awaiting_response;

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
    if (!lessonTitle) return;
    setStarted(true);
    setIsLoading(true);
    isLoadingRef.current = true;

    // Step 1: unlock audio synchronously in the click handler
    if (!audioContextRef.current) {
      audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
    }
    if (audioContextRef.current.state === 'suspended') {
      audioContextRef.current.resume();
    }
    nextStartTimeRef.current = audioContextRef.current.currentTime;
    
    // Step 2: fetch session + chunk (async, after unlock)
    try {
      const session = await startTutorSession(lessonTitle, subtopics, undefined, studentProfileSummary, sessionId, priorTopics);
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
    if (!audioContextRef.current) return;
    if (isPausedRef.current) {
      isPausedRef.current = false;
      setIsPaused(false);
      audioContextRef.current.resume();
      setIsSpeaking(true);
    } else {
      isPausedRef.current = true;
      setIsPaused(true);
      audioContextRef.current.suspend();
      setIsSpeaking(false);
    }
  };

  const handleNext = () => {
    if (!sessionIdRef.current || isLoadingRef.current || isFinishedRef.current) return;
    stopCurrentAudio();
    onNextSlide?.();
    fetchAndPlay(sessionIdRef.current);
  };

  const handleMute = () => {
    // We cannot easily mute an AudioContext without a GainNode.
    // We can just track it and not connect source to destination in onChunk.
    // For now we just update state.
    const next = !isMutedRef.current;
    isMutedRef.current = next;
    setIsMuted(next);
  };

  const handleAskQuestion = async (overrideQuestion?: string, overrideEmotion?: string, isAutoTrigger = false, triggeredForSlide?: number) => {
    const q = (overrideQuestion ?? question).trim();
    if (!sessionIdRef.current || !q || isAsking) return;

    if (isAutoTrigger && triggeredForSlide !== undefined && triggeredForSlide !== currentSlideRef.current) {
      return;
    }

    setQuestion('');

    if (isSpeaking && !isPausedRef.current) {
      stopCurrentAudio();
    }

    setIsAsking(true);
    const wasAwaitingReply = awaitingResponseRef.current;
    awaitingResponseRef.current = false;
    
    // Slide number this turn is anchored to (auto-explain → labelled checkpoint).
    const slideNo = (triggeredForSlide ?? currentSlideRef.current) + 1;
    setTranscript((prev) => [
      ...prev,
      isAutoTrigger
        ? { role: 'checkpoint', text: currentSlideTitle ?? '', slideNumber: slideNo, slideTitle: currentSlideTitle ?? '' }
        : { role: 'student', text: q },
    ]);

    try {
      const repeatKeywords = ['repeat', 'again', 'replay', 'rewind', "say that again", "once more", "didn't get that", "missed that"];
      const paceKeywords = ['slow down', 'too fast', 'speed up', 'faster', 'slower', 'skip'];
      const emotionKeywords = ['confused', 'lost', 'frustrated', "don't understand", 'hard', 'difficult', 'give up', 'struggling'];
      const lower = q.toLowerCase();
      let intent: IntentName = 'On-Topic Question';
      let intentPrediction: IntentPrediction | null = null;

      if (!isAutoTrigger) {
        if (repeatKeywords.some(k => lower.includes(k))) {
          intent = 'Repeat/clarification';
        } else if (paceKeywords.some(k => lower.includes(k))) {
          intent = 'Pace-Related';
        } else if (emotionKeywords.some(k => lower.includes(k))) {
          intent = 'Emotional-State';
        } else {
          const ctx = lessonTitle ? `topic:${lessonTitle} | prev:${lessonTitle} | emotion:neutral | pace:normal` : '';
          setSessionContext(ctx);
          intentPrediction = await classifyIntent(q, ctx);
          intent = intentPrediction?.intent_name ?? 'On-Topic Question';
        }
      }

      const resumeLecture = () => {
        if (isPausedRef.current && audioContextRef.current && audioContextRef.current.state === 'suspended') {
          audioContextRef.current.resume();
          isPausedRef.current = false;
          setIsPaused(false);
          setIsSpeaking(true);
        }
      };

      const currentEmotion = overrideEmotion || fusedEmotion || 'neutral';
      const logInteraction = (responseSummary?: string) => {};

      if (intent === 'Off-Topic Question') {
        const msg = "That seems off-topic. Let's stay focused on the current lesson. Feel free to ask anything related to what we're covering!";
        setTranscript((prev) => [...prev, { role: 'tutor', text: msg, topic: 'Off-Topic' }]);
        logInteraction(msg);
        setTutorEmotion('confused');
        try {
          const b64 = await synthesizeAudio(msg, 'calm', sessionIdRef.current);
          const binary = atob(b64!);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          const audioBuffer = await audioContextRef.current!.decodeAudioData(bytes.buffer);
          const source = audioContextRef.current!.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(audioContextRef.current!.destination);
          source.start();
          isPausedRef.current = false;
          setIsPaused(false);
          setIsSpeaking(true);
        } catch {
          resumeLecture();
        }
        setIsAsking(false);
        return;
      }

      const onChunk = createOnChunk(true);

      if (intent === 'Emotional-State') {
        const res = await askTutor(
          sessionIdRef.current,
          `The student said: "${q}". Please offer brief encouragement and re-explain the current topic in a simpler way.`,
          !isMutedRef.current,
          currentEmotion !== 'neutral' ? currentEmotion : undefined,
          undefined,
          onChunk
        );
        finalizeTranscript();
        logInteraction(res.answer);
        setTutorEmotion('happy');
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
        try { if (sessionIdRef.current) await setTutorPace(sessionIdRef.current, targetPace); } catch {}

        const msg = targetPace === 'slow'
          ? "Got it! I will slow down my speaking pace for the rest of the session."
          : targetPace === 'fast'
            ? "Got it! I will speak faster for the rest of the session."
            : "Got it! You can use the Pause button to take a break or Next to skip ahead. I'll keep going at your pace.";

        setTranscript((prev) => [...prev, { role: 'tutor', text: msg, topic: 'Pace' }]);
        logInteraction(msg);
        setTutorEmotion('calm');
        try {
          const b64 = await synthesizeAudio(msg, 'calm', sessionIdRef.current);
          const binary = atob(b64!);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          const audioBuffer = await audioContextRef.current!.decodeAudioData(bytes.buffer);
          const source = audioContextRef.current!.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(audioContextRef.current!.destination);
          source.start();
          isPausedRef.current = false;
          setIsPaused(false);
          setIsSpeaking(true);
        } catch { resumeLecture(); }
        setIsAsking(false);
        return;
      }

      if (intent === 'Repeat/clarification') {
        resumeLecture();
        const msg = "Sure! Let me repeat that for you.";
        setTranscript((prev) => [...prev, { role: 'tutor', text: msg, topic: 'Repeat' }]);
        logInteraction(msg);
        setTutorEmotion('excited');
        setIsAsking(false);
        return;
      }

      let grounding: import('../services/tutor').RAGPassage[] = [];
      const ACK_RE = /^(yes|yeah|yep|no|nope|ok|okay|sure|maybe|right|correct|true|false|done|got it|i think so|i guess|idk|i don'?t know|not sure|thanks|thank you|cool|nice|hmm+)\b[\s.!?]*$/i;
      const isTrivialReply = q.split(/\s+/).filter(Boolean).length <= 2 || ACK_RE.test(q.trim());
      const shouldRetrieve = !!courseId && !wasAwaitingReply && !isTrivialReply;

      if (shouldRetrieve) {
        try {
          const ragRes = await askRag(q, courseId!);
          if (ragRes.grounded && ragRes.passages.length > 0) {
            grounding = ragRes.passages;
          }
        } catch {}
      }

      const res = await askTutor(
        sessionIdRef.current,
        q,
        !isMutedRef.current,
        currentEmotion !== 'neutral' ? currentEmotion : undefined,
        grounding.length > 0 ? grounding : undefined,
        onChunk
      );

      finalizeTranscript();
      awaitingResponseRef.current = !!res.awaiting_response;

      if (isAutoTrigger && triggeredForSlide !== undefined && triggeredForSlide !== currentSlideRef.current) {
        setIsAsking(false);
        return;
      }

      let chatLogId: number | undefined;
      if (lessonId && courseId) {
        // Auto-explain turns are stored under a parseable marker (rebuilt as a
        // slide checkpoint on reload); real questions store the raw text.
        const loggedText = isAutoTrigger ? slideExplainMarker(slideNo, currentSlideTitle ?? '') : q;
        const chatLog = await persistChatLog({
          course: Number(courseId),
          session_number: lessonId,
          transcript_text: loggedText,
          ai_response_text: res.answer ?? '',
          session_id: sessionIdRef.current ?? undefined,
          session_context: sessionContext,
          predicted_intent: intentPrediction?.intent_name,
          confidence: intentPrediction?.confidence,
          intent_probabilities: intentPrediction?.probabilities,
        });
        chatLogId = chatLog?.id;
      }

      setTranscript((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'tutor' && !last.is_streaming) {
            return [...prev.slice(0, -1), { ...last, grounded: res.grounded, chatLogId, intent: intentPrediction }];
        }
        return prev;
      });

      logInteraction(res.answer);
      setTutorEmotion('happy');

    } catch {
      setTranscript((prev) => [...prev, {
        role: 'tutor',
        text: 'Sorry, I could not process your question.',
      }]);
    } finally {
      setIsAsking(false);
    }
  };

  const handleFeedback = (index: number, feedback: FeedbackValue) => {
    const entry = transcript[index];
    if (!entry?.chatLogId || entry.feedback || correctingIndex === index) return;

    const defaultValue = entry.intent?.intent_name || intentOptions[0]?.value || '';
    setCorrectingIndex(index);
    setCorrectingFeedback(feedback);
    setSelectedCorrectedIntent(defaultValue);
    setShowingDescriptionFor(null);
  };

  const handleCorrectIntent = async () => {
    if (correctingIndex === null || !correctingFeedback) return;
    const entry = transcript[correctingIndex];
    if (!entry?.chatLogId) return;

    const correctedIntent = selectedCorrectedIntent;
    const result = await submitFeedback(entry.chatLogId, correctingFeedback, correctedIntent);
    if (result) {
      setTranscript((prev) => {
        const updated = [...prev];
        updated[correctingIndex] = {
          ...updated[correctingIndex],
          feedback: correctingFeedback,
          correctedIntent,
        };
        return updated;
      });
      if (result.retraining_recommended) {
        console.log('[Intent Feedback] Retraining threshold reached.');
      }
    }
    setCorrectingIndex(null);
    setCorrectingFeedback(null);
    setShowingDescriptionFor(null);
  };

  const closeCorrection = () => {
    setCorrectingIndex(null);
    setCorrectingFeedback(null);
    setShowingDescriptionFor(null);
  };

  const handleVoiceInput = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      return;
    }

    // If lecture audio is currently playing, stop it to prevent overlap
    if (isSpeaking && !isPausedRef.current) {
      stopCurrentAudio();
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

  // Status-dot colour in codex tokens.
  const statusDotColor = error
    ? 'var(--error-red)'
    : isFinished
      ? 'var(--steel)'
      : started
        ? 'var(--accent-success)'
        : 'var(--accent-warm)';

  return (
    <div
      ref={panelRef}
      className="codex"
      style={isFloating
        ? { position: 'absolute', width: 320, maxWidth: '90vw', top: 16, left: 16, maxHeight: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: 16, border: '1px solid var(--hairline)', background: 'var(--bg-surface)', boxShadow: '0 12px 40px rgba(0,0,0,0.18)', zIndex: 50 }
        : { width: 320, minWidth: 320, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderLeft: '1px solid var(--hairline)', background: 'var(--bg-surface)' }}>


      {/* Header — always visible when docked */}
      {(!started || !isDetached) && (
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--hairline)', background: 'var(--bg-primary)', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: statusDotColor }} className={started && !error && !isFinished ? 'animate-pulse' : undefined} />
            <span className="t-label" style={{ color: 'var(--accent-primary)' }}>LEARNPAL</span>
            {progress > 0 && (
              <span className="t-mono steel" style={{ marginLeft: 'auto' }}>{progress}%</span>
            )}
          </div>
          <p className="t-mono steel" style={{ margin: 0 }}>AI TEACHING ASSISTANT</p>
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
          <div className="codex"
               style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg-surface)', padding: '6px 12px', border: '1px solid var(--hairline)', borderRadius: 16 * bubbleScale, boxShadow: '0 6px 18px rgba(0,0,0,0.14)', marginBottom: 2, transform: `scale(${bubbleScale})`, transformOrigin: 'bottom center', transition: 'all 300ms' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: statusDotColor }} className={!error && !isFinished ? 'animate-pulse' : undefined} />
            <span className="t-label" style={{ color: 'var(--accent-primary)' }}>LEARNPAL</span>
            {progress > 0 && <span className="t-mono steel" style={{ marginLeft: 4 }}>{progress}%</span>}
            <GripHorizontal size={12} style={{ color: 'var(--steel)', marginLeft: 4 }} />
          </div>
          <div className="relative transition-all duration-300">
            <div className="absolute inset-0 rounded-full blur-xl opacity-40 pointer-events-none transition-all duration-300" style={{ background: 'var(--accent-primary)' }} />
            <div className="relative rounded-full shadow-2xl transition-all duration-300 flex items-center justify-center"
                 style={{ width: 144 * bubbleScale, height: 144 * bubbleScale, background: 'var(--accent-primary)', padding: 6 }}>
              <Nova3DAvatar
                isSpeaking={isSpeaking}
                emotion={fusedEmotion || tutorEmotion}
                blendshapeData={currentBlendshapes}
                size={144 * bubbleScale - 12}
                isFloating={false}
              />
            </div>
          </div>
          {/* Controls */}
          <div onMouseDown={(e) => e.stopPropagation()}
               style={{ transform: `scale(${bubbleScale})`, transformOrigin: 'top center', display: 'flex', alignItems: 'center', gap: 10, background: 'var(--bg-surface)', borderRadius: 999, padding: '8px 16px', border: '1px solid var(--hairline)', boxShadow: '0 6px 18px rgba(0,0,0,0.14)', marginTop: 4, transition: 'all 300ms' }}>
            <button onClick={handlePlayPause} disabled={isFinished} title={isPaused ? 'Resume' : 'Pause'}
              style={{ ...ctrlDotStyle, ...(!isPaused ? ctrlDotActive : {}), opacity: isFinished ? 0.4 : 1 }}>
              {isPaused ? <Play size={14} /> : <Pause size={14} />}
            </button>
            <button onClick={handleNext} disabled={isLoading || isFinished} title="Next slide"
              style={{ ...ctrlDotStyle, width: 64, borderRadius: 999, fontSize: 11, fontWeight: 600, opacity: (isLoading || isFinished) ? 0.4 : 1 }}>
              {isLoading ? <Loader2 size={14} className="animate-spin" /> : 'NEXT'}
            </button>
            <button onClick={handleMute} title={isMuted ? 'Unmute' : 'Mute'} style={ctrlDotStyle}>
              {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </button>
            <button onClick={() => setBubbleScale(s => s === 1 ? 1.5 : 1)} title={bubbleScale === 1 ? 'Enlarge' : 'Shrink'} style={ctrlDotStyle}>
              {bubbleScale === 1 ? <Maximize2 size={14} /> : <Minimize2 size={14} />}
            </button>
          </div>
          {isFinished && (
            <p className="t-mono steel" style={{ marginTop: 6 }}>LECTURE COMPLETE</p>
          )}
        </div>
      ) : (
        /* ── DOCKED: inline avatar with controls ── */
        <div style={{ padding: started ? '12px 16px' : '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', borderBottom: '1px solid var(--hairline)', background: 'var(--bg-primary)' }}>
          <div
            className="relative"
            onMouseDown={started ? onDragStart : undefined}
            style={{ marginBottom: started ? 8 : 12, cursor: started ? 'grab' : 'default', userSelect: started ? 'none' : undefined }}
          >
            <div className="absolute inset-0 rounded-full blur-xl opacity-30 pointer-events-none" style={{ background: 'var(--accent-primary)' }} />
            <div className="relative rounded-full shadow-xl" style={{ width: 160, height: 160, background: 'var(--accent-primary)', padding: 6 }}>
              <Nova3DAvatar
                isSpeaking={isSpeaking}
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
              className="btn btn-red"
              style={{ padding: '12px 22px', fontSize: 12 }}>
              {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              <span>{isLoading ? 'PREPARING…' : 'START LECTURE'}</span>
            </button>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button onClick={handlePlayPause} disabled={isFinished} title={isPaused ? 'Resume' : 'Pause'}
                style={{ ...ctrlBtnStyle, ...(!isPaused ? ctrlBtnActive : {}), opacity: isFinished ? 0.4 : 1 }}>
                {isPaused ? <Play size={16} /> : <Pause size={16} />}
              </button>
              <button onClick={handleNext} disabled={isLoading || isFinished} title="Next slide"
                style={{ ...ctrlBtnStyle, width: 64, fontSize: 11, fontWeight: 600, opacity: (isLoading || isFinished) ? 0.4 : 1 }}>
                {isLoading ? <Loader2 size={16} className="animate-spin" /> : 'NEXT'}
              </button>
              <button onClick={handleMute} title={isMuted ? 'Unmute' : 'Mute'} style={ctrlBtnStyle}>
                {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
              </button>
            </div>
          )}
          {isFinished && (
            <p className="t-mono steel" style={{ marginTop: 6 }}>LECTURE COMPLETE</p>
          )}
        </div>
      )}

      {/* Current Topic */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--hairline)', background: 'var(--bg-surface)', flexShrink: 0 }}>
        <div className="t-mono steel" style={{ marginBottom: 2 }}>CURRENTLY EXPLAINING</div>
        <p className="t-body" style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.35 }}>
          {lessonTitle || 'Lesson Content'}
        </p>
      </div>

      {/* Transcript */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {error && (
          <div style={{ background: 'rgba(220,38,38,0.06)', borderRadius: 8, padding: 12, borderLeft: '2px solid var(--error-red)' }}>
            <p className="t-body" style={{ margin: 0, fontSize: 12, color: 'var(--error-red)' }}>{error}</p>
          </div>
        )}
        {!started && transcript.length === 0 && !error && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12, textAlign: 'center' }}>
            <p className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Press <strong style={{ color: 'var(--text-primary)' }}>Start Lecture</strong> to hear LearnPal explain this lesson.</p>
          </div>
        )}
        {started && transcript.length === 0 && !error && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
            <Loader2 size={24} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
          </div>
        )}
        {transcript.map((entry, i) => {
          // ── Slide checkpoint marker (auto-explain) — a gradient "stop" on the
          //    path so the saved chatlog reads slide-by-slide. While the tutor is
          //    still generating (this is the last entry), show a loader beneath it.
          if (entry.role === 'checkpoint') {
            const generating = i === transcript.length - 1 && (isAsking || isLoading);
            return (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div
                  style={{
                    position: 'relative', borderRadius: 12, padding: '12px 16px', overflow: 'hidden',
                    background: 'linear-gradient(120deg, var(--accent-primary) 0%, var(--accent-soft) 100%)',
                    boxShadow: '0 6px 16px rgba(37,99,235,0.28)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Flag size={13} style={{ color: '#fff', flexShrink: 0 }} />
                    <span className="t-label" style={{ color: 'rgba(255,255,255,0.85)' }}>
                      SLIDE {String(entry.slideNumber ?? 0).padStart(2, '0')}
                    </span>
                  </div>
                  <p className="t-heading" style={{ margin: '6px 0 0', fontSize: 15, color: '#fff', lineHeight: 1.25 }}>
                    {entry.slideTitle || entry.text || 'This slide'}
                  </p>
                </div>
                {generating && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 4 }}>
                    <Loader2 size={13} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
                    <span className="t-mono steel">LEARNPAL IS EXPLAINING…</span>
                  </div>
                )}
              </div>
            );
          }
          return (
            <div
              key={i}
              style={entry.role === 'tutor'
                ? { borderRadius: 8, padding: 12, background: 'rgba(37,99,235,0.05)', borderLeft: '2px solid var(--accent-primary)' }
                : { borderRadius: 8, padding: 12, background: 'var(--bg-surface)', borderLeft: '2px solid var(--steel)', marginLeft: 16 }}
            >
              {entry.role === 'student' && (
                <span className="t-mono" style={{ display: 'block', marginBottom: 2, color: 'var(--steel-light)' }}>YOU</span>
              )}
              {entry.topic && entry.role === 'tutor' && (
                <span className="t-mono" style={{ display: 'block', marginBottom: 2, color: 'var(--steel-light)' }}>{entry.topic}</span>
              )}
              <p className="t-body" style={{ margin: 0, fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.55, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>{entry.text}</p>
              {entry.role === 'tutor' && entry.grounded === false && (
                <div style={{ marginTop: 6, fontSize: 11, color: 'var(--accent-warm)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  ⚠ Grounding unavailable — answered from general knowledge, not the course textbook.
                </div>
              )}
              {entry.role === 'tutor' && entry.chatLogId && (
                <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="t-mono steel">WAS THIS HELPFUL?</span>
                    <button
                      onClick={() => handleFeedback(i, 'thumbs_up')}
                      disabled={!!entry.feedback}
                      style={{ padding: 4, borderRadius: 6, border: 'none', cursor: entry.feedback ? 'default' : 'pointer', background: entry.feedback === 'thumbs_up' ? 'rgba(22,163,74,0.12)' : 'transparent', color: entry.feedback === 'thumbs_up' ? 'var(--accent-success)' : 'var(--steel-light)', display: 'flex' }}
                      title="Helpful"
                    >
                      <ThumbsUp size={12} />
                    </button>
                    <button
                      onClick={() => handleFeedback(i, 'thumbs_down')}
                      disabled={!!entry.feedback}
                      style={{ padding: 4, borderRadius: 6, border: 'none', cursor: entry.feedback ? 'default' : 'pointer', background: entry.feedback === 'thumbs_down' ? 'rgba(220,38,38,0.12)' : 'transparent', color: entry.feedback === 'thumbs_down' ? 'var(--error-red)' : 'var(--steel-light)', display: 'flex' }}
                      title="Not helpful"
                    >
                      <ThumbsDown size={12} />
                    </button>
                  </div>

                  {correctingIndex === i && !entry.feedback && (
                    <div style={{ borderRadius: 8, border: '1px solid var(--hairline)', background: 'var(--bg-primary)', padding: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <p className="t-mono steel" style={{ margin: 0 }}>
                        WHICH INTENT BEST MATCHES THIS?
                      </p>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {intentOptions.map((option) => {
                          const isSelected = selectedCorrectedIntent === option.value;
                          const showingDescription = showingDescriptionFor === option.value;
                          return (
                            <div key={option.value} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                              <button
                                type="button"
                                onClick={() => setSelectedCorrectedIntent(option.value)}
                                style={{
                                  width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                  borderRadius: 6, padding: '6px 8px', textAlign: 'left', fontSize: 12, cursor: 'pointer',
                                  border: `1px solid ${isSelected ? 'var(--accent-primary)' : 'var(--hairline)'}`,
                                  background: isSelected ? 'rgba(37,99,235,0.08)' : 'transparent',
                                  color: isSelected ? 'var(--accent-primary)' : 'var(--text-primary)',
                                }}
                              >
                                <span style={{ fontWeight: 500 }}>{option.label}</span>
                                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                  <span
                                    style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, borderRadius: '50%', border: '1px solid currentColor', fontSize: 9 }}
                                    title={option.description}
                                    tabIndex={0}
                                    onMouseEnter={() => setShowingDescriptionFor(option.value)}
                                    onMouseLeave={() => setShowingDescriptionFor(null)}
                                    onFocus={() => setShowingDescriptionFor(option.value)}
                                    onBlur={() => setShowingDescriptionFor(null)}
                                    onTouchStart={() =>
                                      setShowingDescriptionFor((prev) =>
                                        prev === option.value ? null : option.value
                                      )
                                    }
                                    role="button"
                                    aria-label={`Definition for ${option.label}`}
                                  >
                                    i
                                  </span>
                                  <span
                                    style={{ width: 12, height: 12, borderRadius: '50%', border: `1px solid ${isSelected ? 'var(--accent-primary)' : 'var(--steel)'}`, background: isSelected ? 'var(--accent-primary)' : 'transparent' }}
                                  />
                                </span>
                              </button>
                              {showingDescription && (
                                <p className="t-body" style={{ margin: 0, fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.4, padding: '0 4px' }}>
                                  {option.description}
                                </p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          onClick={handleCorrectIntent}
                          className="btn btn-red"
                          style={{ flex: 1, padding: '6px 8px', fontSize: 10 }}
                        >
                          SUBMIT
                        </button>
                        <button
                          onClick={closeCorrection}
                          className="btn btn-ghost-dark"
                          style={{ padding: '6px 8px', fontSize: 10 }}
                        >
                          CANCEL
                        </button>
                      </div>
                    </div>
                  )}

                  {entry.feedback && entry.correctedIntent && (
                    <span className="t-mono steel">
                      MARKED AS: {(intentOptions.find(o => o.value === entry.correctedIntent)?.label ?? entry.correctedIntent).toUpperCase()}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
        <div ref={transcriptEndRef} />
      </div>

      {/* Ask Question */}
      {started && (
        <div style={{ padding: 16, borderTop: '1px solid var(--hairline)', background: 'var(--bg-surface)', display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
          {showChat ? (
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAskQuestion(question)}
                placeholder="Ask LearnPal…"
                className="input"
                style={{ flex: 1, padding: '8px 12px', fontSize: 13, borderRadius: 8 }}
                disabled={isAsking}
              />
              <button
                onClick={() => handleAskQuestion()}
                disabled={!question.trim() || isAsking}
                className="btn btn-red"
                style={{ padding: '8px 12px', opacity: (!question.trim() || isAsking) ? 0.5 : 1 }}
              >
                {isAsking ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowChat(true)}
              className="btn btn-red"
              style={{ width: '100%', justifyContent: 'center', padding: '12px' }}
            >
              <MessageCircle size={16} />
              <span>ASK QUESTION</span>
            </button>
          )}
          <button
            onClick={handleVoiceInput}
            disabled={isTranscribing}
            className={isRecording ? 'animate-pulse' : undefined}
            style={{
              width: '100%', padding: '10px', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              fontSize: 12, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', cursor: isTranscribing ? 'default' : 'pointer',
              border: `1px solid ${isRecording ? 'var(--error-red)' : 'var(--steel)'}`,
              background: isRecording ? 'rgba(220,38,38,0.06)' : 'transparent',
              color: isRecording ? 'var(--error-red)' : 'var(--text-primary)',
              opacity: isTranscribing ? 0.5 : 1,
            }}
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
