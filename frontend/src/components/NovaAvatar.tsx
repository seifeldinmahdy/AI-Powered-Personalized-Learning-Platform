import { useEffect, useRef, useCallback, useMemo } from 'react';

/* ═══════════════════════════════════════════════════════════════════
   NovaAvatar — Canvas2D animated AI face with spring physics,
   viseme cycling, eye look-around, and emotion-driven expression.
   ═══════════════════════════════════════════════════════════════════ */

export interface NovaAvatarProps {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  emotion?: string;
  isSpeaking: boolean;
  isLoading: boolean;
  size?: number;
}

/* ─── Spring physics helper ───────────────────────────────────── */

class Spring {
  value: number;
  target: number;
  velocity = 0;
  stiffness: number;
  damping: number;

  constructor(initial: number, stiffness = 120, damping = 14) {
    this.value = initial;
    this.target = initial;
    this.stiffness = stiffness;
    this.damping = damping;
  }

  step(dt: number) {
    const force = -this.stiffness * (this.value - this.target);
    const damp = -this.damping * this.velocity;
    this.velocity += (force + damp) * dt;
    this.value += this.velocity * dt;
  }

  set(v: number) { this.target = v; }
  snap(v: number) { this.target = v; this.value = v; this.velocity = 0; }
}

/* ─── Emotion definitions ─────────────────────────────────────── */

interface EmotionState {
  // Colors
  primary: string;
  accent: string;
  // Face
  leftBrowY: number;    // -1 raised, +1 lowered
  rightBrowY: number;
  eyeOpenness: number;  // 0=closed, 1=normal, 1.4=wide
  pupilSize: number;    // 0.5-1.5
  mouthSmile: number;   // -1 frown, 0 neutral, 1 smile
  // Label
  label: string;
}

const NEUTRAL: EmotionState = {
  primary: '#4C6FFF', accent: '#A78BFA',
  leftBrowY: 0, rightBrowY: 0,
  eyeOpenness: 1, pupilSize: 1, mouthSmile: 0,
  label: '',
};

const EMOTIONS: Record<string, Partial<EmotionState>> = {
  happy:      { primary: '#34D399', accent: '#6EE7B7', leftBrowY: -0.3, rightBrowY: -0.3, eyeOpenness: 0.85, mouthSmile: 1, label: '😊' },
  excited:    { primary: '#FBBF24', accent: '#FDE68A', leftBrowY: -0.6, rightBrowY: -0.6, eyeOpenness: 1.3, pupilSize: 1.2, mouthSmile: 1, label: '🤩' },
  sad:        { primary: '#60A5FA', accent: '#93C5FD', leftBrowY: 0.5, rightBrowY: 0.5, eyeOpenness: 0.7, pupilSize: 0.85, mouthSmile: -0.7, label: '😔' },
  angry:      { primary: '#EF4444', accent: '#FCA5A5', leftBrowY: 0.8, rightBrowY: 0.8, eyeOpenness: 0.7, pupilSize: 0.8, mouthSmile: -0.5, label: '😠' },
  frustrated: { primary: '#F97316', accent: '#FDBA74', leftBrowY: 0.7, rightBrowY: 0.7, eyeOpenness: 0.75, pupilSize: 0.85, mouthSmile: -0.4, label: '😤' },
  confused:   { primary: '#A78BFA', accent: '#C4B5FD', leftBrowY: -0.5, rightBrowY: 0.4, eyeOpenness: 1.15, pupilSize: 1.05, mouthSmile: -0.15, label: '🤔' },
  surprised:  { primary: '#F59E0B', accent: '#FDE68A', leftBrowY: -0.8, rightBrowY: -0.8, eyeOpenness: 1.4, pupilSize: 1.3, mouthSmile: 0, label: '😮' },
  surprise:   { primary: '#F59E0B', accent: '#FDE68A', leftBrowY: -0.8, rightBrowY: -0.8, eyeOpenness: 1.4, pupilSize: 1.3, mouthSmile: 0, label: '😮' },
  fear:       { primary: '#8B5CF6', accent: '#C4B5FD', leftBrowY: -0.6, rightBrowY: -0.6, eyeOpenness: 1.3, pupilSize: 0.7, mouthSmile: -0.2, label: '😰' },
  anxious:    { primary: '#8B5CF6', accent: '#DDD6FE', leftBrowY: -0.3, rightBrowY: -0.1, eyeOpenness: 1.1, mouthSmile: -0.1, label: '😟' },
  bored:      { primary: '#6B7280', accent: '#9CA3AF', leftBrowY: 0.2, rightBrowY: 0.2, eyeOpenness: 0.45, pupilSize: 0.9, mouthSmile: -0.1, label: '😑' },
  disgust:    { primary: '#059669', accent: '#6EE7B7', leftBrowY: 0.4, rightBrowY: 0.1, eyeOpenness: 0.65, mouthSmile: -0.6, label: '😒' },
  calm:       { primary: '#06B6D4', accent: '#67E8F9', eyeOpenness: 0.9, mouthSmile: 0.3, label: '😌' },
};

function getEmotion(name?: string): EmotionState {
  if (!name) return { ...NEUTRAL };
  return { ...NEUTRAL, ...(EMOTIONS[name.trim().toLowerCase()] || {}) };
}

/* ─── Viseme shapes (mouth control points) ───────────────────── */
// Each viseme is an array of [cp1y, cp2y, width, height]
// representing a bezier mouth shape
const VISEMES = [
  [0, 0, 1, 0],         // closed
  [2, 2, 1, 0.3],       // slightly parted
  [4, 5, 1.1, 0.55],    // medium open
  [3, 7, 0.9, 0.75],    // tall open
  [5, 5, 1.2, 0.6],     // wide
  [2, 6, 0.7, 0.8],     // O shape
];

/* ─── Particle ────────────────────────────────────────────────── */

interface Particle {
  x: number; y: number;
  vx: number; vy: number;
  r: number; phase: number;
  speed: number;
}

function createParticles(n: number): Particle[] {
  return Array.from({ length: n }, () => ({
    x: Math.random() * 200,
    y: Math.random() * 200,
    vx: (Math.random() - 0.5) * 0.3,
    vy: (Math.random() - 0.5) * 0.3,
    r: 0.8 + Math.random() * 1.5,
    phase: Math.random() * Math.PI * 2,
    speed: 0.5 + Math.random() * 1.5,
  }));
}

/* ─── Hex colour to RGB ────────────────────────────────────────── */

function hexToRgb(hex: string): [number, number, number] {
  const m = hex.replace('#', '').match(/.{2}/g);
  if (!m) return [76, 111, 255];
  return [parseInt(m[0], 16), parseInt(m[1], 16), parseInt(m[2], 16)];
}

function lerpColor(a: [number, number, number], b: [number, number, number], t: number): string {
  const r = Math.round(a[0] + (b[0] - a[0]) * t);
  const g = Math.round(a[1] + (b[1] - a[1]) * t);
  const bl = Math.round(a[2] + (b[2] - a[2]) * t);
  return `rgb(${r},${g},${bl})`;
}

/* ═══════════════════════════════════════════════════════════════ */

export function NovaAvatar({
  audioRef,
  emotion,
  isSpeaking,
  isLoading,
  size = 120,
}: NovaAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const connectedRef = useRef<HTMLAudioElement | null>(null);

  // Animation state stored in refs for 60fps loop
  const stateRef = useRef({
    // Springs
    leftBrowY: new Spring(0, 80, 10),
    rightBrowY: new Spring(0, 80, 10),
    eyeOpenness: new Spring(1, 150, 12),
    pupilSize: new Spring(1, 100, 11),
    mouthSmile: new Spring(0, 90, 10),
    amplitude: new Spring(0, 200, 18),
    lookX: new Spring(0, 60, 8),
    lookY: new Spring(0, 60, 8),
    headTilt: new Spring(0, 40, 7),
    // Color lerp
    colorT: 0,
    prevPrimary: hexToRgb('#4C6FFF') as [number, number, number],
    prevAccent: hexToRgb('#A78BFA') as [number, number, number],
    nextPrimary: hexToRgb('#4C6FFF') as [number, number, number],
    nextAccent: hexToRgb('#A78BFA') as [number, number, number],
    // Timers
    blinkTimer: 2 + Math.random() * 3,
    isBlinking: false,
    blinkDuration: 0,
    lookTimer: 1 + Math.random() * 2,
    visemeIndex: 0,
    visemeTimer: 0,
    time: 0,
    lastFrame: performance.now(),
    // Particles
    particles: createParticles(16),
  });

  const emotionRef = useRef(emotion);
  const speakingRef = useRef(isSpeaking);
  const loadingRef = useRef(isLoading);

  // Memoized emotion label for overlay
  const emotionStyle = useMemo(() => getEmotion(emotion), [emotion]);

  /* ── Sync props to refs ──────────────────────────────────────── */

  useEffect(() => {
    const s = stateRef.current;
    const emo = getEmotion(emotion);

    if (emotion !== emotionRef.current) {
      emotionRef.current = emotion;
      // Trigger color transition
      s.prevPrimary = hexToRgb(lerpColor(s.prevPrimary, s.nextPrimary, s.colorT));
      s.prevAccent = hexToRgb(lerpColor(s.prevAccent, s.nextAccent, s.colorT));
      s.nextPrimary = hexToRgb(emo.primary);
      s.nextAccent = hexToRgb(emo.accent);
      s.colorT = 0;
    }

    s.leftBrowY.set(emo.leftBrowY);
    s.rightBrowY.set(emo.rightBrowY);
    s.eyeOpenness.set(emo.eyeOpenness);
    s.pupilSize.set(emo.pupilSize);
    s.mouthSmile.set(emo.mouthSmile);
  }, [emotion]);

  useEffect(() => { speakingRef.current = isSpeaking; }, [isSpeaking]);
  useEffect(() => { loadingRef.current = isLoading; }, [isLoading]);

  /* ── Connect Web Audio analyser ──────────────────────────────── */

  const connectAnalyser = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || connectedRef.current === audio) return;
    try {
      if (!audioCtxRef.current) audioCtxRef.current = new AudioContext();
      const ctx = audioCtxRef.current;
      if (!sourceRef.current) sourceRef.current = ctx.createMediaElementSource(audio);
      if (!analyserRef.current) {
        analyserRef.current = ctx.createAnalyser();
        analyserRef.current.fftSize = 256;
        analyserRef.current.smoothingTimeConstant = 0.7;
      }
      sourceRef.current.connect(analyserRef.current);
      analyserRef.current.connect(ctx.destination);
      connectedRef.current = audio;
    } catch { /* already connected */ }
  }, [audioRef]);

  /* ── Main render loop ────────────────────────────────────────── */

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    const DPR = window.devicePixelRatio || 1;
    const W = 200, H = 200;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    ctx.scale(DPR, DPR);

    const freqBuf = new Uint8Array(128);

    function frame(now: number) {
      const s = stateRef.current;
      const dt = Math.min((now - s.lastFrame) / 1000, 0.05);
      s.lastFrame = now;
      s.time += dt;

      /* ── Read amplitude ────────────────────────────── */
      let rawAmp = 0;
      if (speakingRef.current) {
        connectAnalyser();
        const an = analyserRef.current;
        if (an) {
          an.getByteFrequencyData(freqBuf);
          let sum = 0;
          for (let i = 0; i < freqBuf.length; i++) sum += freqBuf[i];
          rawAmp = Math.min((sum / freqBuf.length) / 100, 1);
        }
      }
      s.amplitude.set(speakingRef.current ? rawAmp : 0);

      /* ── Blink timer ───────────────────────────────── */
      s.blinkTimer -= dt;
      if (s.blinkTimer <= 0 && !s.isBlinking) {
        s.isBlinking = true;
        s.blinkDuration = 0;
      }
      if (s.isBlinking) {
        s.blinkDuration += dt;
        if (s.blinkDuration > 0.15) {
          s.isBlinking = false;
          s.blinkTimer = 2 + Math.random() * 4;
        }
      }

      /* ── Eye look-around ───────────────────────────── */
      s.lookTimer -= dt;
      if (s.lookTimer <= 0) {
        s.lookX.set((Math.random() - 0.5) * 4);
        s.lookY.set((Math.random() - 0.5) * 2.5);
        s.headTilt.set((Math.random() - 0.5) * 3);
        s.lookTimer = 1.5 + Math.random() * 3;
      }

      /* ── Viseme cycling when speaking ──────────────── */
      if (speakingRef.current && s.amplitude.value > 0.05) {
        s.visemeTimer += dt * (3 + s.amplitude.value * 8); // faster with louder
        if (s.visemeTimer > 1) {
          s.visemeTimer = 0;
          // Pick random viseme weighted by amplitude
          const maxIdx = Math.min(Math.floor(1 + s.amplitude.value * 5), VISEMES.length - 1);
          s.visemeIndex = 1 + Math.floor(Math.random() * maxIdx);
        }
      } else {
        s.visemeIndex = 0;
        s.visemeTimer = 0;
      }

      /* ── Color lerp ────────────────────────────────── */
      s.colorT = Math.min(s.colorT + dt * 2, 1);
      const primaryRgb = lerpColor(s.prevPrimary, s.nextPrimary, s.colorT);
      const accentRgb = lerpColor(s.prevAccent, s.nextAccent, s.colorT);

      /* ── Step all springs ──────────────────────────── */
      s.leftBrowY.step(dt);
      s.rightBrowY.step(dt);
      s.eyeOpenness.step(dt);
      s.pupilSize.step(dt);
      s.mouthSmile.step(dt);
      s.amplitude.step(dt);
      s.lookX.step(dt);
      s.lookY.step(dt);
      s.headTilt.step(dt);

      const amp = s.amplitude.value;

      /* ═══════════════════════════════════════════════ */
      /* ──           DRAW                           ── */
      /* ═══════════════════════════════════════════════ */

      ctx.clearRect(0, 0, W, H);
      ctx.save();

      // Subtle head tilt
      ctx.translate(W / 2, H / 2);
      ctx.rotate((s.headTilt.value * Math.PI) / 180);
      ctx.translate(-W / 2, -H / 2);

      const cx = W / 2, cy = 100;

      /* ── Background glow ──────────────────────────── */
      const glowR = 65 + amp * 15;
      const grd = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      grd.addColorStop(0, primaryRgb.replace('rgb', 'rgba').replace(')', `,${0.12 + amp * 0.15})`));
      grd.addColorStop(0.6, accentRgb.replace('rgb', 'rgba').replace(')', ',0.04)'));
      grd.addColorStop(1, 'transparent');
      ctx.fillStyle = grd;
      ctx.fillRect(0, 0, W, H);

      /* ── Outer ring ──────────────────────────────── */
      ctx.save();
      ctx.translate(cx, cy);
      ctx.strokeStyle = primaryRgb;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = 0.3 + amp * 0.3;
      ctx.beginPath();
      ctx.arc(0, 0, 82 + amp * 4, 0, Math.PI * 2);
      ctx.stroke();
      // Spinning accent arc
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = accentRgb;
      const arcStart = s.time * (speakingRef.current ? 3 : 0.8);
      ctx.beginPath();
      ctx.arc(0, 0, 82 + amp * 4, arcStart, arcStart + 0.6);
      ctx.stroke();
      ctx.globalAlpha = 0.35;
      ctx.beginPath();
      ctx.arc(0, 0, 82 + amp * 4, arcStart + Math.PI, arcStart + Math.PI + 0.4);
      ctx.stroke();
      ctx.restore();

      /* ── Face plate ──────────────────────────────── */
      ctx.save();
      const faceR = 58;
      const faceGrd = ctx.createRadialGradient(cx - 10, cy - 15, 0, cx, cy, faceR);
      faceGrd.addColorStop(0, '#161B45');
      faceGrd.addColorStop(0.5, '#111640');
      faceGrd.addColorStop(1, '#0B0F2E');
      ctx.fillStyle = faceGrd;
      ctx.shadowColor = primaryRgb;
      ctx.shadowBlur = 15 + amp * 20;
      ctx.beginPath();
      ctx.arc(cx, cy, faceR, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // Inner edge highlight
      ctx.strokeStyle = `rgba(255,255,255,0.06)`;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();

      /* ── Wireframe contours ──────────────────────── */
      ctx.save();
      ctx.globalAlpha = 0.06;
      ctx.strokeStyle = primaryRgb;
      ctx.lineWidth = 0.5;
      ctx.setLineDash([3, 6]);
      ctx.beginPath(); ctx.ellipse(cx, cy + 5, 48, 54, 0, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.ellipse(cx, cy + 5, 40, 46, 0, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();

      /* ── Eyebrows ─────────────────────────────────── */
      const browBaseY = 72;
      const browW = 16;
      const lby = browBaseY + s.leftBrowY.value * 8;
      const rby = browBaseY + s.rightBrowY.value * 8;

      ctx.save();
      ctx.strokeStyle = primaryRgb;
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.globalAlpha = 0.7;
      ctx.shadowColor = primaryRgb;
      ctx.shadowBlur = 6;

      // Left brow (inner higher when raised)
      ctx.beginPath();
      ctx.moveTo(cx - 30 + browW, lby + s.leftBrowY.value * 2);
      ctx.quadraticCurveTo(cx - 30 + browW / 2, lby - 2, cx - 30, lby);
      ctx.stroke();

      // Right brow
      ctx.beginPath();
      ctx.moveTo(cx + 30 - browW, rby + s.rightBrowY.value * 2);
      ctx.quadraticCurveTo(cx + 30 - browW / 2, rby - 2, cx + 30, rby);
      ctx.stroke();
      ctx.restore();

      /* ── Eyes ──────────────────────────────────────── */
      const eyeY = 90;
      const eyeSpacing = 22;
      const blinkMult = s.isBlinking ? 0.05 : 1;
      const openness = s.eyeOpenness.value * blinkMult;
      const eyeRx = 10;
      const eyeRy = Math.max(openness * 9, 0.5);
      const pSize = s.pupilSize.value;
      const lx = s.lookX.value;
      const ly = s.lookY.value;

      for (const side of [-1, 1]) {
        const ex = cx + side * eyeSpacing;

        // Eye socket glow
        ctx.save();
        const socketGrd = ctx.createRadialGradient(ex, eyeY, 0, ex, eyeY, 16);
        socketGrd.addColorStop(0, primaryRgb.replace('rgb', 'rgba').replace(')', ',0.1)'));
        socketGrd.addColorStop(1, 'transparent');
        ctx.fillStyle = socketGrd;
        ctx.fillRect(ex - 16, eyeY - 16, 32, 32);
        ctx.restore();

        // Eye white/shape
        ctx.save();
        ctx.fillStyle = `rgba(220,225,255,${0.08 + openness * 0.04})`;
        ctx.strokeStyle = primaryRgb;
        ctx.lineWidth = 1.5;
        ctx.globalAlpha = 0.85;
        ctx.shadowColor = primaryRgb;
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.ellipse(ex, eyeY, eyeRx, eyeRy, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();

        if (openness > 0.2) {
          // Iris
          const irisR = 4 * pSize;
          const irisGrd = ctx.createRadialGradient(
            ex + lx, eyeY + ly, 0,
            ex + lx, eyeY + ly, irisR
          );
          irisGrd.addColorStop(0, accentRgb);
          irisGrd.addColorStop(0.6, primaryRgb);
          irisGrd.addColorStop(1, primaryRgb.replace('rgb', 'rgba').replace(')', ',0.4)'));
          ctx.save();
          ctx.fillStyle = irisGrd;
          ctx.shadowColor = primaryRgb;
          ctx.shadowBlur = 6;
          ctx.beginPath();
          ctx.arc(ex + lx, eyeY + ly, irisR, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();

          // Pupil
          ctx.save();
          ctx.fillStyle = '#0a0b14';
          ctx.beginPath();
          ctx.arc(ex + lx, eyeY + ly, irisR * 0.45, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();

          // Glint
          ctx.save();
          ctx.fillStyle = 'rgba(255,255,255,0.85)';
          ctx.beginPath();
          ctx.arc(ex + lx + 2, eyeY + ly - 2, 1.4, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = 'rgba(255,255,255,0.4)';
          ctx.beginPath();
          ctx.arc(ex + lx - 1.5, eyeY + ly + 1.5, 0.8, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
      }

      /* ── Nose hint ─────────────────────────────────── */
      ctx.save();
      ctx.strokeStyle = primaryRgb;
      ctx.globalAlpha = 0.1;
      ctx.lineWidth = 1;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(cx, 102);
      ctx.lineTo(cx, 110);
      ctx.stroke();
      ctx.restore();

      /* ── Mouth (viseme-based) ──────────────────────── */
      const mouthCx = cx;
      const mouthCy = 122;
      const smile = s.mouthSmile.value;

      // Interpolate viseme
      const vis = VISEMES[s.visemeIndex];
      const mw = 14 * vis[2]; // width
      const mh = vis[3] * 12; // height
      const cp1 = vis[0];
      const cp2 = vis[1];

      ctx.save();
      ctx.strokeStyle = primaryRgb;
      ctx.fillStyle = primaryRgb.replace('rgb', 'rgba').replace(')', ',0.15)');
      ctx.lineWidth = 2;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.shadowColor = primaryRgb;
      ctx.shadowBlur = 5;
      ctx.globalAlpha = 0.8;

      ctx.beginPath();
      if (mh < 2) {
        // Closed mouth — curved line
        ctx.moveTo(mouthCx - mw, mouthCy);
        ctx.quadraticCurveTo(mouthCx, mouthCy + smile * 6, mouthCx + mw, mouthCy);
        ctx.stroke();
      } else {
        // Open mouth
        ctx.moveTo(mouthCx - mw, mouthCy);
        // Top lip
        ctx.quadraticCurveTo(mouthCx, mouthCy - cp1 + smile * 3, mouthCx + mw, mouthCy);
        // Bottom lip
        ctx.quadraticCurveTo(mouthCx, mouthCy + cp2 + mh + smile * 2, mouthCx - mw, mouthCy);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
      ctx.restore();

      /* ── Circuit accents ───────────────────────────── */
      ctx.save();
      ctx.strokeStyle = primaryRgb;
      ctx.globalAlpha = 0.1;
      ctx.lineWidth = 0.8;
      ctx.lineCap = 'round';
      // Left cheek
      ctx.beginPath();
      ctx.moveTo(cx - 42, 105);
      ctx.lineTo(cx - 48, 112);
      ctx.lineTo(cx - 45, 122);
      ctx.stroke();
      // Right cheek
      ctx.beginPath();
      ctx.moveTo(cx + 42, 105);
      ctx.lineTo(cx + 48, 112);
      ctx.lineTo(cx + 45, 122);
      ctx.stroke();
      // Dots
      ctx.fillStyle = primaryRgb;
      ctx.globalAlpha = 0.2;
      ctx.beginPath(); ctx.arc(cx - 48, 112, 1.2, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(cx + 48, 112, 1.2, 0, Math.PI * 2); ctx.fill();
      ctx.restore();

      /* ── Particles ─────────────────────────────────── */
      ctx.save();
      for (const p of s.particles) {
        p.x += p.vx + Math.sin(s.time * p.speed + p.phase) * 0.15;
        p.y += p.vy + Math.cos(s.time * p.speed + p.phase) * 0.12;

        // Wrap around
        if (p.x < 0) p.x = W;
        if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H;
        if (p.y > H) p.y = 0;

        const dist = Math.sqrt((p.x - cx) ** 2 + (p.y - cy) ** 2);
        const fade = Math.max(0, 1 - dist / 100);
        const pAlpha = fade * (0.2 + (speakingRef.current ? amp * 0.5 : 0));

        ctx.fillStyle = p.phase > Math.PI ? accentRgb : primaryRgb;
        ctx.globalAlpha = pAlpha;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * (0.8 + amp * 0.4), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      /* ── Loading overlay ───────────────────────────── */
      if (loadingRef.current) {
        ctx.save();
        ctx.fillStyle = 'rgba(11,15,46,0.5)';
        ctx.beginPath();
        ctx.arc(cx, cy, 58, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = primaryRgb;
        ctx.lineWidth = 2.5;
        ctx.lineCap = 'round';
        const la = s.time * 4;
        ctx.beginPath();
        ctx.arc(cx, cy, 20, la, la + 1.8);
        ctx.stroke();
        ctx.restore();
      }

      ctx.restore(); // head tilt

      rafRef.current = requestAnimationFrame(frame);
    }

    rafRef.current = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(rafRef.current);
  }, [connectAnalyser]);

  return (
    <div className="relative" style={{ width: size, height: size, overflow: 'hidden' }}>
      <canvas
        ref={canvasRef}
        style={{ width: size, height: size }}
        className="rounded-full"
      />

      {/* Speaking equalizer */}
      {isSpeaking && (
        <div
          className="absolute -bottom-1 -right-1 flex items-end gap-[2px] rounded-full px-2 py-1.5 border border-white/10 shadow-lg"
          style={{ background: '#0B0F2E', boxShadow: `0 0 8px ${emotionStyle.primary}40` }}
        >
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="rounded-full transition-all duration-75"
              style={{
                width: 2.5,
                height: `${8 + Math.random() * 6}px`,
                backgroundColor: emotionStyle.primary,
                opacity: 0.8,
              }}
            />
          ))}
        </div>
      )}

    </div>
  );
}
