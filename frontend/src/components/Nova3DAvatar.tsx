import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';

const AI_URL = import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001';

export interface Nova3DAvatarProps {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  emotion?: string;
  blendshapeData?: { names: string[]; frames: number[][] } | null;
  size?: number;
  isFloating?: boolean;
}

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

/* ─── Eye look positions ─── */
const EYE_POSITIONS: Record<string, number>[] = [
  {},
  { EyeLookOutLeft: 0.3, EyeLookInRight: 0.3 },
  { EyeLookInLeft: 0.3, EyeLookOutRight: 0.3 },
  { EyeLookUpLeft: 0.25, EyeLookUpRight: 0.25 },
  { EyeLookDownLeft: 0.2, EyeLookDownRight: 0.2 },
  { EyeLookUpLeft: 0.2, EyeLookOutLeft: 0.2, EyeLookUpRight: 0.2, EyeLookInRight: 0.2 },
  { EyeLookUpLeft: 0.2, EyeLookInLeft: 0.2, EyeLookUpRight: 0.2, EyeLookOutRight: 0.2 },
  { EyeSquintLeft: 0.2, EyeSquintRight: 0.2 },
];

const EYE_LOOK_NAMES = [
  'EyeLookOutLeft', 'EyeLookInRight', 'EyeLookInLeft', 'EyeLookOutRight',
  'EyeLookUpLeft', 'EyeLookUpRight', 'EyeLookDownLeft', 'EyeLookDownRight',
  'EyeSquintLeft', 'EyeSquintRight',
];

const VISEME_NAMES = ['JawOpen', 'MouthFunnel', 'MouthPucker', 'MouthLowerDownLeft', 'MouthLowerDownRight'];
const BLINK_NAMES = ['EyeBlinkLeft', 'EyeBlinkRight'];

export function Nova3DAvatar({ audioRef, emotion, blendshapeData, size = 120, isFloating = false }: Nova3DAvatarProps) {
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
    // Idle state
    blinkValue: 0,
    blinkPhase: 'idle' as 'idle' | 'closing' | 'hold' | 'opening',
    blinkPhaseTime: 0,
    targetEyePos: {} as Record<string, number>,
    currentEyePos: {} as Record<string, number>,
    microSmileValue: 0,
    microSmileTarget: 0,
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

  // Keep refs in sync
  useEffect(() => { emotionRef.current = emotion; }, [emotion]);
  useEffect(() => { blendshapeRef.current = blendshapeData; }, [blendshapeData]);

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
        console.log('[Nova3D] Morph meshes found:', morphMeshes.length);
        if (morphMeshes.length > 0) {
          console.log('[Nova3D] Morph targets:', Object.keys(morphMeshes[0].morphTargetDictionary!));
        }

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
          console.warn(`[Nova3D] Failed to load ${url}, trying fallback ${fallbackUrl}...`);
          loadModel(fallbackUrl);
        } else {
          console.error('[Nova3D] Model load failed:', err);
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
        // 40% center bias
        const idx = Math.random() < 0.4 ? 0 : Math.floor(Math.random() * EYE_POSITIONS.length);
        s.targetEyePos = { ...EYE_POSITIONS[idx] };
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
      const audio = audioRef.current;
      const isPlaying = audio && !audio.paused && !audio.ended && audio.currentTime > 0;

      // ── LAYER 1: Speech ──
      const bsData = blendshapeRef.current;
      if (isPlaying && bsData && bsData.frames.length > 0) {
        // A2F mode
        s.speechFading = false;
        const frameIdx = Math.min(Math.floor(audio!.currentTime * 30), bsData.frames.length - 1);
        const frame = bsData.frames[frameIdx];
        bsData.names.forEach((name, i) => { lerpBS(name, frame[i], 0.25); });
        s.lastA2fNames = bsData.names;
      } else if (isPlaying && !bsData) {
        // Fallback viseme mode
        s.speechFading = false;
        const progress = (audio!.currentTime % CYCLE_DUR) / CYCLE_DUR;
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

      // Eye movement
      EYE_LOOK_NAMES.forEach(name => {
        const target = s.targetEyePos[name] ?? 0;
        const cur = s.currentEyePos[name] ?? 0;
        const next = cur + (target - cur) * 0.08;
        s.currentEyePos[name] = next;
        setBS(name, next);
      });

      // Micro smile
      s.microSmileValue += (s.microSmileTarget - s.microSmileValue) * 0.04;
      if (s.microSmileValue > 0.005) {
        const curL = getBS('MouthSmileLeft'), curR = getBS('MouthSmileRight');
        setBS('MouthSmileLeft', Math.min(1, curL + s.microSmileValue));
        setBS('MouthSmileRight', Math.min(1, curR + s.microSmileValue));
      }

      // Head sway
      if (s.rootGroup) {
        const t = now / 1000;
        s.rootGroup.rotation.z = Math.sin(t * 0.4) * 0.008;
        s.rootGroup.rotation.x = Math.sin(t * 0.3) * 0.005;
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

    // ── Cleanup ──
    return () => {
      s.mounted = false;
      cancelAnimationFrame(s.rafId);
      s.timeouts.forEach(t => clearTimeout(t));
      document.removeEventListener('visibilitychange', onVisChange);
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
