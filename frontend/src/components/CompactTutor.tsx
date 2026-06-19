import { Mic, MicOff, Volume2, VolumeX, MessageCircle, Pause, Play, Send, Loader2, Code2, GripHorizontal, Maximize2, Minimize2, ThumbsUp, ThumbsDown, Info } from 'lucide-react';
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
  submitFeedback,
  type SERResult,
  type IntentPrediction,
  type FeedbackValue,
  type TutorStreamChunk,
} from '../services/tutor';

import { fuseEmotions } from '../services/emotionFusion';
import { Nova3DAvatar } from './Nova3DAvatar';
import type { BlendshapeData } from '../services/tutor';

const INTENT_OPTIONS: { value: string; label: string; description: string }[] = [
  {
    value: 'On-Topic Question',
    label: 'On-Topic Question',
    description: 'Asking about the current Python topic — explanation, example, clarification, or debugging help.',
  },
  {
    value: 'Off-Topic Question',
    label: 'Off-Topic',
    description: 'Completely unrelated to the lesson or programming.',
  },
  {
    value: 'Emotional-State',
    label: 'Emotional State',
    description: 'Expressing a feeling like frustration, confusion, excitement, boredom, or anxiety.',
  },
  {
    value: 'Pace-Related',
    label: 'Pace-Related',
    description: 'Wants to change speed — slow down, speed up, skip, or take a break.',
  },
  {
    value: 'Repeat/clarification',
    label: 'Repeat / Clarification',
    description: 'Wants something repeated or explained again (uses "again", "back", "repeat", "missed").',
  },
  {
    value: 'Debugging/Code-Sharing',
    label: 'Debugging / Code',
    description: 'Sharing code, error messages, tracebacks, or asking for debugging help.',
  },
];

interface TranscriptEntry {
  role: 'tutor' | 'student';
  text: string;
  topic?: string;
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
  const [sessionContext, setSessionContext] = useState('');
  const [correctionModal, setCorrectionModal] = useState<{ index: number; chatLogId: number } | null>(null);

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
    
    setTranscript((prev) => [
      ...prev,
      { role: 'student', text: isAutoTrigger ? `LearnPal, please explain this slide: ${currentSlideTitle}` : q }
    ]);

    try {
      const repeatKeywords = ['repeat', 'again', 'replay', 'rewind', "say that again", "once more", "didn't get that", "missed that"];
      const paceKeywords = ['slow down', 'too fast', 'speed up', 'faster', 'slower', 'skip'];
      const emotionKeywords = ['confused', 'lost', 'frustrated', "don't understand", 'hard', 'difficult', 'give up', 'struggling'];
      const lower = q.toLowerCase();
      let intent: string = 'On-Topic Question';
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
      if (lessonId) {
        const chatLog = await persistChatLog({
          lesson: lessonId,
          transcript_text: q,
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

  const handleFeedback = async (index: number, feedback: FeedbackValue) => {
    const entry = transcript[index];
    if (!entry?.chatLogId || entry.feedback) return;

    if (feedback === 'thumbs_down') {
      setCorrectionModal({ index, chatLogId: entry.chatLogId });
      return;
    }

    const result = await submitFeedback(entry.chatLogId, feedback);
    if (result) {
      setTranscript((prev) => {
        const updated = [...prev];
        updated[index] = { ...updated[index], feedback };
        return updated;
      });
      if (result.retraining_recommended) {
        console.log('[Intent Feedback] Retraining threshold reached.');
      }
    }
  };

  const handleCorrectIntent = async (correctedIntent: string) => {
    if (!correctionModal) return;
    const { index, chatLogId } = correctionModal;
    const result = await submitFeedback(chatLogId, 'thumbs_down', correctedIntent);
    if (result) {
      setTranscript((prev) => {
        const updated = [...prev];
        updated[index] = {
          ...updated[index],
          feedback: 'thumbs_down',
          correctedIntent,
        };
        return updated;
      });
      if (result.retraining_recommended) {
        console.log('[Intent Feedback] Retraining threshold reached.');
      }
    }
    setCorrectionModal(null);
  };

  const closeCorrectionModal = () => setCorrectionModal(null);

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

  return (
    <div
      ref={panelRef}
      style={isFloating ? { width: 320, maxWidth: '90vw', top: 16, left: 16, maxHeight: '80vh' } : { width: 320, minWidth: 320 }}
      className={`relative ${isFloating
        ? 'absolute rounded-2xl border border-border bg-card/95 backdrop-blur-md flex flex-col overflow-hidden shadow-2xl z-50'
        : 'shrink-0 border-l-2 border-border bg-card flex flex-col overflow-hidden'
        }`}>
      

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
              {entry.role === 'tutor' && entry.grounded === false && (
                <div className="mt-1.5 text-xs text-amber-600/90 flex items-center gap-1">
                  ⚠ Grounding unavailable — answered from general knowledge, not the course textbook.
                </div>
              )}
              {entry.role === 'tutor' && entry.chatLogId && (
                <div className="mt-2 flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground">Was this helpful?</span>
                    <button
                      onClick={() => handleFeedback(i, 'thumbs_up')}
                      disabled={!!entry.feedback}
                      className={`p-1 rounded transition-colors ${entry.feedback === 'thumbs_up' ? 'bg-green-100 text-green-600' : 'hover:bg-muted text-muted-foreground'}`}
                      title="Helpful"
                    >
                      <ThumbsUp size={12} />
                    </button>
                    <button
                      onClick={() => handleFeedback(i, 'thumbs_down')}
                      disabled={!!entry.feedback}
                      className={`p-1 rounded transition-colors ${entry.feedback === 'thumbs_down' ? 'bg-red-100 text-red-600' : 'hover:bg-muted text-muted-foreground'}`}
                      title="Not helpful"
                    >
                      <ThumbsDown size={12} />
                    </button>
                  </div>
                  {entry.feedback === 'thumbs_down' && entry.correctedIntent && (
                    <span className="text-[10px] text-red-600">
                      Marked as: {INTENT_OPTIONS.find(o => o.value === entry.correctedIntent)?.label ?? entry.correctedIntent}
                    </span>
                  )}
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

      {/* Correction modal for thumbs-down feedback */}
      {correctionModal && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-xl border border-border bg-card p-4 shadow-2xl">
            <h4 className="text-sm font-semibold mb-1">Which intent fits better?</h4>
            <p className="text-xs text-muted-foreground mb-3">
              Help us improve by selecting the correct category for your question.
            </p>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {INTENT_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  onClick={() => handleCorrectIntent(option.value)}
                  className="w-full flex items-center justify-between rounded-lg border border-border px-3 py-2 text-left text-xs hover:bg-muted transition-colors"
                >
                  <span className="font-medium">{option.label}</span>
                  <span
                    className="ml-2 text-muted-foreground"
                    title={option.description}
                  >
                    <Info size={14} />
                  </span>
                </button>
              ))}
            </div>
            <button
              onClick={closeCorrectionModal}
              className="mt-3 w-full py-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
