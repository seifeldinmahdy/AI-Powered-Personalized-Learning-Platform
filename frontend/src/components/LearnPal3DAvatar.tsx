import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';

const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';

export interface LearnPal3DAvatarProps {
  isSpeaking: boolean;
  emotion?: string;
  blendshapeData?: { names: string[]; frames: number[][] } | null;
  // performance.now() ms that frame 0 of blendshapeData should align to. Lets the
  // caller resume a track at the correct frame after a pause (e.g. after a fun
  // reaction interrupts the lecture). When omitted, playback starts "now".
  blendshapeEpochMs?: number | null;
  // A one-shot facial reaction (easter egg). Bump `token` to (re)play it.
  reaction?: { kind: 'laugh' | 'frown' | 'dizzy'; token: number } | null;
  size?: number;
  isFloating?: boolean;
}

// Audio2Face tends to over-open the jaw; scale the openness shapes down so the
// mouth movement reads natural. Tune MOUTH_SCALE (1 = raw A2F, lower = calmer).
const MOUTH_SCALE = 0.6;
const MOUTH_OPEN_SHAPES = new Set(['jawopen', 'mouthopen', 'mouthlowerdownleft', 'mouthlowerdownright']);

// How long each one-shot facial reaction plays (seconds).
const REACTION_DURATIONS: Record<string, number> = { laugh: 1.6, frown: 1.3, dizzy: 1.9 };

/* ─── Emotion response mapping (student → avatar) ─── */
const STUDENT_TO_AVATAR: Record<string, string> = {
  happy: 'warm', excited: 'excited', sad: 'empathetic', frustrated: 'encouraging',
  angry: 'calm', confused: 'encouraging', anxious: 'reassuring', bored: 'engaging',
  fear: 'reassuring', disgust: 'calm', surprised: 'warm', calm: 'neutral', neutral: 'neutral',
};

const AVATAR_EMOTIONS: Record<string, Record<string, number>> = {
  warm: { MouthSmileLeft: 0.35, MouthSmileRight: 0.35, CheekSquintLeft: 0.2, CheekSquintRight: 0.2 },
  excited: { MouthSmileLeft: 0.6, MouthSmileRight: 0.6, EyeWideLeft: 0.2, EyeWideRight: 0.2, BrowInnerUp: 0.3 },
  empathetic: { BrowInnerUp: 0.4, MouthFrownLeft: 0.15, MouthFrownRight: 0.15, EyeSquintLeft: 0.15, EyeSquintRight: 0.15 },
  encouraging: { MouthSmileLeft: 0.4, MouthSmileRight: 0.4, BrowInnerUp: 0.2, CheekSquintLeft: 0.15, CheekSquintRight: 0.15 },
  calm: { MouthSmileLeft: 0.15, MouthSmileRight: 0.15 },
  reassuring: { MouthSmileLeft: 0.3, MouthSmileRight: 0.3, BrowInnerUp: 0.25, EyeSquintLeft: 0.1, EyeSquintRight: 0.1 },
  engaging: { MouthSmileLeft: 0.5, MouthSmileRight: 0.5, EyeWideLeft: 0.25, EyeWideRight: 0.25, BrowOuterUpLeft: 0.2, BrowOuterUpRight: 0.2 },
  neutral: {},
};

/* ─── Fallback viseme sequence ─── */
const VISEME_SEQ = [
  { t: 0.00, JawOpen: 0, MouthFunnel: 0, MouthPucker: 0 },
  { t: 0.08, JawOpen: 0.4, MouthFunnel: 0.1, MouthPucker: 0 },
  { t: 0.15, JawOpen: 0.2, MouthFunnel: 0, MouthPucker: 0.2 },
  { t: 0.22, JawOpen: 0.5, MouthFunnel: 0, MouthPucker: 0 },
  { t: 0.30, JawOpen: 0.1, MouthFunnel: 0.3, MouthPucker: 0 },
  { t: 0.38, JawOpen: 0, MouthFunnel: 0, MouthPucker: 0 },
  { t: 0.45, JawOpen: 0.3, MouthFunnel: 0, MouthPucker: 0.3 },
  { t: 0.55, JawOpen: 0.4, MouthFunnel: 0.2, MouthPucker: 0 },
  { t: 0.65, JawOpen: 0, MouthFunnel: 0, MouthPucker: 0 },
  { t: 0.72, JawOpen: 0.5, MouthFunnel: 0, MouthPucker: 0 },
  { t: 0.80, JawOpen: 0.2, MouthFunnel: 0.4, MouthPucker: 0 },
  { t: 0.88, JawOpen: 0.3, MouthFunnel: 0, MouthPucker: 0 },
  { t: 1.00, JawOpen: 0, MouthFunnel: 0, MouthPucker: 0 },
];

const VISEME_NAMES = ['JawOpen', 'MouthFunnel', 'MouthPucker', 'MouthLowerDownLeft', 'MouthLowerDownRight'];
const BLINK_NAMES = ['EyeBlinkLeft', 'EyeBlinkRight'];

export function LearnPal3DAvatar({ isSpeaking, emotion, blendshapeData, blendshapeEpochMs, reaction, size = 120, isFloating = false }: LearnPal3DAvatarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef({
    renderer: null as THREE.WebGLRenderer | null,
    scene: null as THREE.Scene | null,
    camera: null as THREE.PerspectiveCamera | null,
    morphMeshes: [] as THREE.Mesh[],
    rootGroup: null as THREE.Group | null,
    rafId: 0,
    timeouts: [] as ReturnType<typeof setTimeout>[],
    mounted: true,
    loaded: false,
    bsStartTime: 0,
    lastBsData: null as any,
    lastBsEpoch: undefined as number | null | undefined,
    // Idle state
    blinkValue: 0,
    blinkPhase: 'idle' as 'idle' | 'closing' | 'hold' | 'opening',
    blinkPhaseTime: 0,
    microSmileValue: 0,
    microSmileTarget: 0,
    // Gaze (eyeballs): this avatar steers the eyes via the LeftEye/RightEye
    // BONES, not the eyeLook* morphs — so cursor-follow & idle saccades rotate
    // these bones. gazeX/Y are smoothed toward targetGazeX/Y (-1..1).
    targetGazeX: 0,
    targetGazeY: 0,
    gazeX: 0,
    gazeY: 0,
    eyeBones: [] as { obj: THREE.Object3D; base: { x: number; y: number } }[],
    // Cursor eye-tracking: when the pointer is near the avatar, the gaze (and a
    // subtle head turn) follow it, overriding the random idle eye movement.
    cursorTracking: false,
    targetHeadYaw: 0,
    targetHeadPitch: 0,
    headYaw: 0,
    headPitch: 0,
    // One-shot facial reaction (laugh / frown / dizzy eyes).
    reactionKind: '' as string,
    reactionStart: 0,
    reactionActive: false,
    reactionToken: -1,
    // Emotion state
    targetEmotionBS: {} as Record<string, number>,
    currentEmotionBS: {} as Record<string, number>,
    // Speech fade-out
    speechFadeStart: 0,
    speechFading: false,
    lastA2fNames: [] as string[],
  });

  const emotionRef = useRef(emotion);
  const blendshapeRef = useRef(blendshapeData);
  const blendshapeEpochRef = useRef(blendshapeEpochMs);
  const isSpeakingRef = useRef(isSpeaking);

  // Keep refs in sync
  useEffect(() => { emotionRef.current = emotion; }, [emotion]);
  useEffect(() => { blendshapeRef.current = blendshapeData; }, [blendshapeData]);
  useEffect(() => { blendshapeEpochRef.current = blendshapeEpochMs; }, [blendshapeEpochMs]);
  useEffect(() => { isSpeakingRef.current = isSpeaking; }, [isSpeaking]);

  // Kick off a facial reaction when its token changes.
  useEffect(() => {
    if (reaction && reaction.token !== stateRef.current.reactionToken) {
      const s = stateRef.current;
      s.reactionToken = reaction.token;
      s.reactionKind = reaction.kind;
      s.reactionStart = performance.now() / 1000;
      s.reactionActive = true;
    }
  }, [reaction]);

  // Update emotion targets
  useEffect(() => {
    const s = stateRef.current;
    const avatarEmo = STUDENT_TO_AVATAR[(emotion || 'neutral').toLowerCase()] ?? 'neutral';
    s.targetEmotionBS = { ...(AVATAR_EMOTIONS[avatarEmo] || {}) };
  }, [emotion]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const s = stateRef.current;
    s.mounted = true;

    // ── Scene setup ──
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "high-performance" });
    renderer.setSize(size, size);
    renderer.setPixelRatio(Math.max(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(renderer.domElement);
    s.renderer = renderer; s.scene = scene; s.camera = camera;

    // Lighting
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const keyLight = new THREE.DirectionalLight(0xfff5e6, 0.8);
    keyLight.position.set(1.5, 2, 2);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0xe6f0ff, 0.3);
    fillLight.position.set(-1, 1, -1);
    scene.add(fillLight);

    // ── Load model ──
    const loader = new GLTFLoader();

    // Add DRACOLoader to support compressed .glb models
    const dracoLoader = new DRACOLoader();
    dracoLoader.setDecoderPath('https://www.gstatic.com/draco/v1/decoders/');
    loader.setDRACOLoader(dracoLoader);

    const loadModel = (url: string, fallbackUrl?: string) => {
      loader.load(url, (gltf) => {
        if (!s.mounted) return;
        const model = gltf.scene;
        const group = new THREE.Group();
        group.add(model);
        scene.add(group);
        s.rootGroup = group;

        // Collect morph meshes
        const morphMeshes: THREE.Mesh[] = [];
        model.traverse((child) => {
          if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            if (mesh.morphTargetDictionary && mesh.morphTargetInfluences) {
              morphMeshes.push(mesh);
            }
          }
        });
        s.morphMeshes = morphMeshes;
        console.log('[LearnPal3D] Morph meshes found:', morphMeshes.length);
        if (morphMeshes.length > 0) {
          console.log('[LearnPal3D] Morph targets:', Object.keys(morphMeshes[0].morphTargetDictionary!));
        }

        // Collect the eye bones for gaze. This avatar poses the eyeballs via
        // the LeftEye/RightEye bones — the eyeLook* morphs exist but don't
        // visibly rotate the eyeball, which is why morph-only cursor tracking
        // moved the head but not the eyes.
        const eyeBones: { obj: THREE.Object3D; base: { x: number; y: number } }[] = [];
        model.traverse((child) => {
          const isBone = (child as unknown as { isBone?: boolean }).isBone;
          const named = /^(LeftEye|RightEye)$/i.test(child.name);
          const looksLikeEyeBone = !!isBone && /eye/i.test(child.name) && !/lash|mesh|ao/i.test(child.name);
          if (named || looksLikeEyeBone) {
            eyeBones.push({ obj: child, base: { x: child.rotation.x, y: child.rotation.y } });
          }
        });
        s.eyeBones = eyeBones;
        console.log('[LearnPal3D] Eye bones found:', eyeBones.map((b) => b.obj.name));

        // Center the model in the scene
        const box = new THREE.Box3().setFromObject(model);
        const center = box.getCenter(new THREE.Vector3());
        const bSize = box.getSize(new THREE.Vector3());
        // Offset model so the head is centered in the circle
        // We move the target point higher up the bounding box
        const headY = center.y + bSize.y * 0.42;
        model.position.set(-center.x, -headY, -center.z);

        // Camera looks straight at origin, moved closer to zoom in
        camera.position.set(0, 0, bSize.y * 0.35);
        camera.lookAt(0, 0, 0);
        camera.updateProjectionMatrix();

        s.loaded = true;

        // Start idle timers
        scheduleBlink();
        scheduleEyeMove();
        scheduleMicroSmile();
      }, undefined, (err) => {
        if (fallbackUrl) {
          console.warn(`[LearnPal3D] Failed to load ${url}, trying fallback ${fallbackUrl}...`);
          loadModel(fallbackUrl);
        } else {
          console.error('[LearnPal3D] Model load failed:', err);
        }
      });
    };

    // Try loading avatar.glb first, then fallback to avatar.gltf
    loadModel(`${AI_URL}/static/avatar.glb`, `${AI_URL}/static/avatar.gltf`);

    // ── Blendshape helpers ──
    function findMorphIdx(mesh: THREE.Mesh, name: string): number | undefined {
      const dict = mesh.morphTargetDictionary;
      if (!dict) return undefined;
      let idx = dict[name];
      if (idx !== undefined) return idx;
      const lower = name.toLowerCase();
      const key = Object.keys(dict).find(k => k.toLowerCase() === lower);
      return key !== undefined ? dict[key] : undefined;
    }

    function setBS(name: string, value: number) {
      const v = Math.max(0, Math.min(1, value));
      s.morphMeshes.forEach(mesh => {
        const idx = findMorphIdx(mesh, name);
        if (idx !== undefined) mesh.morphTargetInfluences![idx] = v;
      });
    }

    function lerpBS(name: string, target: number, factor: number) {
      s.morphMeshes.forEach(mesh => {
        const idx = findMorphIdx(mesh, name);
        if (idx !== undefined) {
          const cur = mesh.morphTargetInfluences![idx];
          mesh.morphTargetInfluences![idx] = cur + (target - cur) * factor;
        }
      });
    }

    function getBS(name: string): number {
      if (s.morphMeshes.length === 0) return 0;
      const mesh = s.morphMeshes[0];
      const idx = findMorphIdx(mesh, name);
      return idx !== undefined ? (mesh.morphTargetInfluences![idx] || 0) : 0;
    }

    // ── Idle: Blinks ──
    function scheduleBlink() {
      if (!s.mounted) return;
      const delay = 2000 + Math.random() * 4000;
      const t = setTimeout(() => {
        if (!s.mounted) return;
        s.blinkPhase = 'closing'; s.blinkPhaseTime = 0;
        // 15% double blink
        if (Math.random() < 0.15) {
          const t2 = setTimeout(() => {
            if (s.mounted) { s.blinkPhase = 'closing'; s.blinkPhaseTime = 0; }
          }, 280);
          s.timeouts.push(t2);
        }
      }, delay);
      s.timeouts.push(t);
    }

    // ── Idle: Eye movement ──
    function scheduleEyeMove() {
      if (!s.mounted) return;
      const delay = 2000 + Math.random() * 3000;
      const t = setTimeout(() => {
        if (!s.mounted) return;
        // While the gaze is locked to the cursor, skip the random idle saccade.
        if (!s.cursorTracking) {
          // 40% center bias, else a small random glance.
          if (Math.random() < 0.4) {
            s.targetGazeX = 0; s.targetGazeY = 0;
          } else {
            s.targetGazeX = (Math.random() * 2 - 1) * 0.6;
            s.targetGazeY = (Math.random() * 2 - 1) * 0.4;
          }
        }
        scheduleEyeMove();
      }, delay);
      s.timeouts.push(t);
    }

    // ── Idle: Micro smile ──
    function scheduleMicroSmile() {
      if (!s.mounted) return;
      const delay = 8000 + Math.random() * 7000;
      const t = setTimeout(() => {
        if (!s.mounted) return;
        const currentSmile = Math.max(getBS('MouthSmileLeft'), getBS('MouthSmileRight'));
        if (currentSmile < 0.3) {
          s.microSmileTarget = 0.15 + Math.random() * 0.1;
          const t2 = setTimeout(() => { s.microSmileTarget = 0; }, 1400);
          s.timeouts.push(t2);
        }
        scheduleMicroSmile();
      }, delay);
      s.timeouts.push(t);
    }

    // ── Main render loop ──
    let prevTime = performance.now();
    const CYCLE_DUR = 0.9;

    function animate(now: number) {
      if (!s.mounted) return;
      s.rafId = requestAnimationFrame(animate);

      if (document.hidden || !s.loaded) return;

      const dt = Math.min((now - prevTime) / 1000, 0.05);
      prevTime = now;
      const isPlaying = isSpeakingRef.current;

      // ── LAYER 1: Speech ──
      const bsData = blendshapeRef.current;
      const bsEpoch = blendshapeEpochRef.current;

      // (Re)anchor frame 0 when the track changes OR its epoch changes (the
      // latter lets a caller resume a paused track at the right frame). An
      // explicit epoch aligns to that wall-clock ms; otherwise start "now".
      if (bsData && (bsData !== s.lastBsData || bsEpoch !== s.lastBsEpoch)) {
        s.lastBsData = bsData;
        s.lastBsEpoch = bsEpoch;
        s.bsStartTime = bsEpoch != null ? bsEpoch / 1000 : now / 1000;
      }
      if (!isPlaying) {
        s.lastBsData = null;
      }

      if (isPlaying && bsData && bsData.frames.length > 0) {
        // A2F mode
        s.speechFading = false;
        const elapsed = (now / 1000) - s.bsStartTime;
        // Audio2Face NIM outputs blendshapes at 30 FPS
        const frameIdx = Math.min(Math.floor(elapsed * 30), bsData.frames.length - 1);
        const frame = bsData.frames[frameIdx];
        bsData.names.forEach((name, i) => {
          // Damp the over-eager jaw/mouth openness A2F produces.
          const v = MOUTH_OPEN_SHAPES.has(name.toLowerCase()) ? frame[i] * MOUTH_SCALE : frame[i];
          lerpBS(name, v, 0.25);
        });
        s.lastA2fNames = bsData.names;
      } else if (isPlaying && !bsData) {
        // Fallback viseme mode
        s.speechFading = false;
        // Use global time for fallback
        const progress = ((now / 1000) % CYCLE_DUR) / CYCLE_DUR;
        // Find surrounding keyframes
        let lo = VISEME_SEQ[0], hi = VISEME_SEQ[1];
        for (let i = 0; i < VISEME_SEQ.length - 1; i++) {
          if (progress >= VISEME_SEQ[i].t && progress < VISEME_SEQ[i + 1].t) {
            lo = VISEME_SEQ[i]; hi = VISEME_SEQ[i + 1]; break;
          }
        }
        const segT = (hi.t - lo.t) > 0 ? (progress - lo.t) / (hi.t - lo.t) : 0;
        const jaw = lo.JawOpen + (hi.JawOpen - lo.JawOpen) * segT;
        const funnel = lo.MouthFunnel + (hi.MouthFunnel - lo.MouthFunnel) * segT;
        const pucker = lo.MouthPucker + (hi.MouthPucker - lo.MouthPucker) * segT;

        lerpBS('JawOpen', jaw, 0.3);
        lerpBS('MouthFunnel', funnel, 0.3);
        lerpBS('MouthPucker', pucker, 0.3);
        lerpBS('MouthLowerDownLeft', jaw * 0.6, 0.3);
        lerpBS('MouthLowerDownRight', jaw * 0.6, 0.3);
      } else if (!isPlaying) {
        // Speech ended — fade out
        if (!s.speechFading && (s.lastA2fNames.length > 0 || getBS('JawOpen') > 0.01)) {
          s.speechFading = true; s.speechFadeStart = now;
        }
        if (s.speechFading) {
          const elapsed = (now - s.speechFadeStart) / 1000;
          if (elapsed < 0.5) {
            const factor = 0.08;
            VISEME_NAMES.forEach(n => lerpBS(n, 0, factor));
            s.lastA2fNames.forEach(n => lerpBS(n, 0, factor));
          } else {
            VISEME_NAMES.forEach(n => setBS(n, 0));
            s.lastA2fNames.forEach(n => setBS(n, 0));
            s.speechFading = false; s.lastA2fNames = [];
          }
        }
      }

      // ── LAYER 2: Emotion (slow lerp, additive) ──
      const allEmotionNames = new Set<string>();
      Object.values(AVATAR_EMOTIONS).forEach(m => Object.keys(m).forEach(k => allEmotionNames.add(k)));
      allEmotionNames.forEach(name => {
        const target = s.targetEmotionBS[name] ?? 0;
        const cur = s.currentEmotionBS[name] ?? 0;
        const next = cur + (target - cur) * 0.03;
        s.currentEmotionBS[name] = next;
        // Additive: add on top of current value, clamped
        if (Math.abs(next) > 0.001) {
          const base = getBS(name);
          setBS(name, Math.min(1, base + next));
        }
      });

      // ── LAYER 3: Idle ──
      // Blinks
      if (s.blinkPhase !== 'idle') {
        s.blinkPhaseTime += dt;
        if (s.blinkPhase === 'closing') {
          s.blinkValue = Math.min(1, s.blinkValue + dt / 0.08);
          if (s.blinkPhaseTime > 0.08) { s.blinkPhase = 'hold'; s.blinkPhaseTime = 0; }
        } else if (s.blinkPhase === 'hold') {
          s.blinkValue = 1;
          if (s.blinkPhaseTime > 0.04) { s.blinkPhase = 'opening'; s.blinkPhaseTime = 0; }
        } else if (s.blinkPhase === 'opening') {
          s.blinkValue = Math.max(0, s.blinkValue - dt / 0.08);
          if (s.blinkPhaseTime > 0.08) { s.blinkPhase = 'idle'; s.blinkValue = 0; scheduleBlink(); }
        }
      }
      BLINK_NAMES.forEach(n => setBS(n, s.blinkValue));

      // ── Facial reaction (one-shot easter egg): laugh / frown / dizzy eyes ──
      let reactionKind = '';
      let reactionEnv = 0;   // ease 0→1→0 over the reaction
      let reactionRt = 0;    // seconds since the reaction started
      let dizzy = false;
      if (s.reactionActive) {
        reactionRt = (now / 1000) - s.reactionStart;
        const dur = REACTION_DURATIONS[s.reactionKind] ?? 1.5;
        if (reactionRt >= dur) {
          s.reactionActive = false;
        } else {
          reactionKind = s.reactionKind;
          reactionEnv = Math.sin((reactionRt / dur) * Math.PI);
          if (reactionKind === 'dizzy') dizzy = true;
        }
      }

      // Eye movement (gaze). Smooth toward the target, then steer the eye
      // bones — the real driver on this rig. The eyeLook* morphs are written
      // too so non-bone rigs still track, but they no-op harmlessly here.
      s.gazeX += (s.targetGazeX - s.gazeX) * 0.12;
      s.gazeY += (s.targetGazeY - s.gazeY) * 0.12;
      let gx = s.gazeX, gy = s.gazeY;
      if (dizzy) {
        // Eyes roll around in a circle — woozy after being thrown.
        const spin = reactionRt * 7.5; // ~1.2 revolutions per second
        gx = Math.cos(spin) * 0.9;
        gy = Math.sin(spin) * 0.9;
      }
      if (s.eyeBones.length > 0) {
        // Sign convention for this rig: +y looks toward the viewer's right,
        // +x looks down. Flip a sign here if a future avatar tracks
        // mirrored/inverted.
        const EYE_YAW = 0.6;   // radians at full horizontal deflection
        const EYE_PITCH = 0.5; // radians at full vertical deflection
        for (const { obj, base } of s.eyeBones) {
          obj.rotation.y = base.y + gx * EYE_YAW;
          obj.rotation.x = base.x + gy * EYE_PITCH;
        }
      }
      // Morph fallback (mirror-correct ARKit eyeLook mapping).
      setBS('EyeLookOutLeft', gx > 0 ? gx * 0.6 : 0);
      setBS('EyeLookInRight', gx > 0 ? gx * 0.6 : 0);
      setBS('EyeLookInLeft', gx < 0 ? -gx * 0.6 : 0);
      setBS('EyeLookOutRight', gx < 0 ? -gx * 0.6 : 0);
      setBS('EyeLookDownLeft', gy > 0 ? gy * 0.5 : 0);
      setBS('EyeLookDownRight', gy > 0 ? gy * 0.5 : 0);
      setBS('EyeLookUpLeft', gy < 0 ? -gy * 0.5 : 0);
      setBS('EyeLookUpRight', gy < 0 ? -gy * 0.5 : 0);

      // Micro smile
      s.microSmileValue += (s.microSmileTarget - s.microSmileValue) * 0.04;
      if (s.microSmileValue > 0.005) {
        const curL = getBS('MouthSmileLeft'), curR = getBS('MouthSmileRight');
        setBS('MouthSmileLeft', Math.min(1, curL + s.microSmileValue));
        setBS('MouthSmileRight', Math.min(1, curR + s.microSmileValue));
      }

      // Facial reaction expression overlay (additive, layered over any talking).
      if (reactionKind === 'laugh' || reactionKind === 'frown') {
        const addBS = (n: string, v: number) => setBS(n, Math.min(1, getBS(n) + v));
        if (reactionKind === 'laugh') {
          addBS('MouthSmileLeft', 0.7 * reactionEnv); addBS('MouthSmileRight', 0.7 * reactionEnv);
          addBS('CheekSquintLeft', 0.45 * reactionEnv); addBS('CheekSquintRight', 0.45 * reactionEnv);
          addBS('EyeSquintLeft', 0.3 * reactionEnv); addBS('EyeSquintRight', 0.3 * reactionEnv);
          addBS('BrowInnerUp', 0.2 * reactionEnv);
          // "ha-ha" jaw bob — only when not lip-syncing speech (else it fights it).
          if (!isPlaying) addBS('JawOpen', Math.max(0, Math.sin(reactionRt * 16)) * 0.22 * reactionEnv);
        } else {
          addBS('MouthFrownLeft', 0.55 * reactionEnv); addBS('MouthFrownRight', 0.55 * reactionEnv);
          addBS('BrowDownLeft', 0.35 * reactionEnv); addBS('BrowDownRight', 0.35 * reactionEnv);
          addBS('MouthPucker', 0.12 * reactionEnv);
        }
      }

      // Head sway (+ a gentle turn toward the cursor when tracking)
      if (s.rootGroup) {
        const t = now / 1000;
        s.headYaw += (s.targetHeadYaw - s.headYaw) * 0.08;
        s.headPitch += (s.targetHeadPitch - s.headPitch) * 0.08;
        // Dizzy adds a woozy head roll on top of the idle sway.
        const dizzyRoll = dizzy ? Math.sin(reactionRt * 9) * 0.06 : 0;
        s.rootGroup.rotation.z = Math.sin(t * 0.4) * 0.008 + dizzyRoll;
        s.rootGroup.rotation.x = Math.sin(t * 0.3) * 0.005 + s.headPitch;
        s.rootGroup.rotation.y = Math.sin(t * 0.25) * 0.006 + s.headYaw;
      }

      renderer.render(scene, camera);
    }

    s.rafId = requestAnimationFrame(animate);

    // ── Visibility pause ──
    const onVisChange = () => {
      if (!document.hidden && s.mounted) {
        prevTime = performance.now();
      }
    };
    document.addEventListener('visibilitychange', onVisChange);

    // ── Cursor eye-tracking ──
    // When the pointer comes near the avatar, map its offset from the avatar's
    // centre to the eye-look blendshapes (mirror-correct: cursor to the viewer's
    // right → the avatar looks to its left, which reads as "toward the cursor"),
    // plus a subtle head turn. Beyond `reach`, idle gaze resumes.
    const stopTracking = () => {
      if (!s.cursorTracking) return;
      s.cursorTracking = false;
      s.targetGazeX = 0;
      s.targetGazeY = 0;
      s.targetHeadYaw = 0;
      s.targetHeadPitch = 0;
    };
    const onPointerMove = (e: MouseEvent) => {
      if (!s.mounted || !s.loaded) return;
      const rect = container.getBoundingClientRect();
      if (rect.width === 0) return;
      const dx = e.clientX - (rect.left + rect.width / 2);
      const dy = e.clientY - (rect.top + rect.height / 2);
      const reach = Math.max(rect.width, rect.height) * 0.5 + 200; // "close to" the avatar
      if (Math.hypot(dx, dy) > reach) { stopTracking(); return; }

      s.cursorTracking = true;
      const nx = Math.max(-1, Math.min(1, dx / reach));
      const ny = Math.max(-1, Math.min(1, dy / reach));
      // Eyes lead the cursor; the head follows with a subtler turn.
      s.targetGazeX = nx;
      s.targetGazeY = ny;
      s.targetHeadYaw = nx * 0.16;
      s.targetHeadPitch = ny * 0.10;
    };
    window.addEventListener('mousemove', onPointerMove);
    document.addEventListener('mouseleave', stopTracking);

    // ── Cleanup ──
    return () => {
      s.mounted = false;
      cancelAnimationFrame(s.rafId);
      s.timeouts.forEach(t => clearTimeout(t));
      document.removeEventListener('visibilitychange', onVisChange);
      window.removeEventListener('mousemove', onPointerMove);
      document.removeEventListener('mouseleave', stopTracking);
      scene.traverse((obj) => {
        const m = obj as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
        if (m.material) {
          const mats = Array.isArray(m.material) ? m.material : [m.material];
          mats.forEach(mat => mat.dispose());
        }
      });
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [isFloating]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const s = stateRef.current;
    if (s.renderer) {
      s.renderer.setSize(size, size);
    }
  }, [size]);

  return (
    <div
      ref={containerRef}
      style={{
        width: size,
        height: size,
        overflow: 'hidden',
        borderRadius: '50%',
      }}
    />
  );
}
