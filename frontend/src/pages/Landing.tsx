import { useEffect, useRef, useState, type ReactNode, type CSSProperties, type RefObject } from "react";
import { useNavigate } from "react-router";

/* PersonifAI — Landing Page (immersive scrollytelling rebuild)

   This intentionally departs from the static design canvas. The goal is an
   Apple-product-page feel: pinned scenes that play on scroll, parallax depth,
   a horizontally-scrubbing gallery, directional reveals and count-ups.

   Engine: a single shared requestAnimationFrame scroll store drives DOM refs
   imperatively (no per-frame React re-renders). Everything degrades:
   - prefers-reduced-motion  → pins unpin, transforms off, content static.
   - small screens           → pins relax / horizontal gallery falls back to
                                native scroll.
   Brand copy + every CTA→/login + in-page nav scrolling are preserved. */

const HAIRLINE = "var(--hairline)";
const PAD_X = "clamp(20px, 6vw, 80px)";
const clamp = (n: number, a = 0, b = 1) => Math.min(b, Math.max(a, n));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/* ── shared rAF scroll store ─────────────────────────────────── */
type Sub = () => void;
const subs = new Set<Sub>();
let rafPending = false;
function flush() {
  rafPending = false;
  subs.forEach((f) => f());
}
function onScrollResize() {
  if (!rafPending) {
    rafPending = true;
    requestAnimationFrame(flush);
  }
}
function subscribe(fn: Sub) {
  if (subs.size === 0) {
    window.addEventListener("scroll", onScrollResize, { passive: true });
    window.addEventListener("resize", onScrollResize);
  }
  subs.add(fn);
  return () => {
    subs.delete(fn);
    if (subs.size === 0) {
      window.removeEventListener("scroll", onScrollResize);
      window.removeEventListener("resize", onScrollResize);
    }
  };
}

function useReducedMotion() {
  const [r, setR] = useState(false);
  useEffect(() => {
    const m = window.matchMedia("(prefers-reduced-motion: reduce)");
    const h = () => setR(m.matches);
    h();
    m.addEventListener?.("change", h);
    return () => m.removeEventListener?.("change", h);
  }, []);
  return r;
}

function useMedia(query: string) {
  const [v, setV] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(query);
    const h = () => setV(m.matches);
    h();
    m.addEventListener?.("change", h);
    return () => m.removeEventListener?.("change", h);
  }, [query]);
  return v;
}

/* Drive a callback with an element's scroll progress.
   mode "through": 0 when it enters from below, 0.5 centered, 1 when it leaves top.
   mode "sticky":  0..1 across a tall pin wrapper (height - viewport). */
function useScrollDrive<T extends HTMLElement>(
  ref: RefObject<T | null>,
  cb: (p: number) => void,
  mode: "through" | "sticky" = "through",
  enabled = true,
) {
  const cbRef = useRef(cb);
  cbRef.current = cb;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!enabled) {
      cbRef.current(mode === "through" ? 0.5 : 0);
      return;
    }
    const compute = () => {
      const rect = el.getBoundingClientRect();
      const vh = window.innerHeight || 1;
      const p =
        mode === "sticky"
          ? clamp(-rect.top / (rect.height - vh || 1))
          : clamp((vh - rect.top) / (vh + rect.height || 1));
      cbRef.current(p);
    };
    const unsub = subscribe(compute);
    compute();
    return unsub;
  }, [ref, mode, enabled]);
}

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ── Entrance reveal (IntersectionObserver, flash-free) ──────── */
type RevealVariant = "up" | "left" | "right" | "fade" | "scale";
const HIDDEN: Record<RevealVariant, string> = {
  up: "translateY(34px)",
  left: "translateX(-28px)",
  right: "translateX(28px)",
  fade: "none",
  scale: "scale(0.94)",
};
function Reveal({
  children, variant = "up", delay = 0, style, className,
}: { children: ReactNode; variant?: RevealVariant; delay?: number; style?: CSSProperties; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setShown(true); return; }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { setShown(true); io.disconnect(); } }),
      { threshold: 0.18, rootMargin: "0px 0px -8% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={className} style={{
      ...style,
      opacity: shown ? 1 : 0,
      transform: shown ? "none" : HIDDEN[variant],
      transition: `opacity 700ms cubic-bezier(0.16,1,0.3,1) ${delay}ms, transform 820ms cubic-bezier(0.16,1,0.3,1) ${delay}ms`,
      willChange: "opacity, transform",
    }}>{children}</div>
  );
}

/* ── Count-up number ─────────────────────────────────────────── */
function CountUp({ to, suffix = "", duration = 1200, style }: { to: number; suffix?: string; duration?: number; style?: CSSProperties }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { el.textContent = `${to}${suffix}`; return; }
    let raf = 0; let start = 0;
    const run = (t: number) => {
      if (!start) start = t;
      const p = clamp((t - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = `${Math.round(eased * to)}${suffix}`;
      if (p < 1) raf = requestAnimationFrame(run);
    };
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { raf = requestAnimationFrame(run); io.disconnect(); } });
    }, { threshold: 0.5 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to, suffix, duration]);
  return <span ref={ref} style={style}>0{suffix}</span>;
}

/* ── Top scroll-progress rail ────────────────────────────────── */
function ProgressRail() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const compute = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      el.style.transform = `scaleX(${max > 0 ? clamp(window.scrollY / max) : 0})`;
    };
    const unsub = subscribe(compute);
    compute();
    return unsub;
  }, []);
  return (
    <div style={{ position: "fixed", top: 0, left: 0, right: 0, height: 3, zIndex: 60, background: "transparent", pointerEvents: "none" }}>
      <div ref={ref} style={{ height: "100%", background: "linear-gradient(90deg,#2563EB,#16A34A)", transformOrigin: "left", transform: "scaleX(0)" }} />
    </div>
  );
}

/* ════════════════════════════════════════════════════════════ */
export default function Landing() {
  const navigate = useNavigate();
  const goLogin = () => navigate("/login");
  const reduce = useReducedMotion();
  const isMobile = useMedia("(max-width: 760px)");

  return (
    <div className="codex pai-landing" style={{ background: "var(--bg-primary)", position: "relative", overflowX: "clip", width: "100%" }}>
      <style>{`
        .pai-landing { --land-pad-x: ${PAD_X}; }
        @keyframes paiDrift { 0%{transform:translate3d(0,0,0)} 50%{transform:translate3d(-2.5%,1.5%,0)} 100%{transform:translate3d(0,0,0)} }
        @keyframes paiBob { 0%,100%{transform:translateY(0);opacity:.5} 50%{transform:translateY(9px);opacity:1} }
        @keyframes paiPulse { 0%,100%{opacity:.35} 50%{opacity:1} }
        .pai-cta-mag { transition: transform 220ms cubic-bezier(.16,1,.3,1), box-shadow 220ms ease; }
        .pai-cta-mag:hover { transform: translateY(-3px) scale(1.012); box-shadow: 0 24px 50px -22px rgba(37,99,235,.55); }
        .pai-navlink { position: relative; cursor: pointer; }
        .pai-navlink::after { content:""; position:absolute; left:0; bottom:-5px; height:1px; width:0; background:#2563EB; transition:width 240ms cubic-bezier(.16,1,.3,1); }
        .pai-navlink:hover::after { width:100%; }
        .pai-hide-mobile { }

        @media (max-width: 900px) {
          .pai-hero-grid { grid-template-columns: 1fr !important; }
          .pai-hero-desc { border-left: none !important; padding-left: 0 !important; margin-top: 26px; }
          .pai-p1-data { position: static !important; width: auto !important; height: auto !important; padding: 0 var(--land-pad-x) 56px !important; flex-direction: row !important; flex-wrap: wrap; gap: 24px !important; }
          .pai-p1-heading { padding-right: var(--land-pad-x) !important; }
          .pai-slides-stageGrid { grid-template-columns: 1fr !important; }
          .pai-foot-grid { grid-template-columns: 1fr !important; gap: 40px !important; }
        }
        @media (max-width: 760px) {
          .pai-hide-mobile { display: none !important; }
        }
        @media (max-width: 560px) {
          .pai-foot-row { flex-direction: column; align-items: flex-start !important; gap: 14px; }
        }
      `}</style>

      <ProgressRail />

      {/* tricolor edge bar */}
      <div style={{ position: "absolute", top: 0, left: 0, width: 4, height: "100%", zIndex: 40, display: "flex", flexDirection: "column", pointerEvents: "none" }}>
        <div style={{ flex: 1, background: "#2563EB" }} />
        <div style={{ flex: 1, background: "#16A34A" }} />
      </div>

      <Hero onLogin={goLogin} onNav={scrollToId} reduce={reduce} isMobile={isMobile} />
      <Manifesto reduce={reduce} />
      <Placement reduce={reduce} />
      <Curriculum />
      <AdaptiveSlides reduce={reduce} isMobile={isMobile} />
      <ExperienceGallery reduce={reduce} isMobile={isMobile} />
      <Assessments reduce={reduce} />
      <Principle reduce={reduce} />
      <Promise onLogin={goLogin} reduce={reduce} />
      <SiteFooter onLogin={goLogin} onNav={scrollToId} />
    </div>
  );
}

/* ── HERO — pinned "One ___." word rotator ───────────────────── */
const HERO_WORDS = [
  { t: "platform.", blue: false },
  { t: "student.", blue: false },
  { t: "course.", blue: true },
];

function HeroNav({ onLogin, onNav }: { onLogin: () => void; onNav: (id: string) => void }) {
  const navMap: Record<string, string> = { TECHNOLOGY: "technology", EXPERIENCE: "experience", RESEARCH: "research", FAQ: "faq" };
  return (
    <div style={{ position: "relative", zIndex: 3, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 24, padding: `34px ${PAD_X} 0` }}>
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 20, letterSpacing: "-0.02em", color: "#1A1611" }}>Personif<span style={{ color: "#2563EB" }}>AI</span><span style={{ color: "#2563EB" }}>.</span></div>
      <div className="t-label pai-hide-mobile" style={{ display: "flex", gap: 30 }}>
        {["TECHNOLOGY", "EXPERIENCE", "RESEARCH", "FAQ"].map((n) => (
          <span key={n} className="pai-navlink" onClick={() => onNav(navMap[n])} style={{ color: "#1A1611" }}>{n}</span>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
        <span className="t-label pai-hide-mobile" style={{ color: "#2563EB" }}>EARLY ACCESS</span>
        <button onClick={onLogin} className="btn btn-ghost" style={{ padding: "10px 16px", fontSize: 11 }}>LOG IN →</button>
      </div>
    </div>
  );
}

const HERO_BIG: CSSProperties = { fontFamily: "var(--ff-display)", fontSize: "clamp(60px, 13vw, 172px)", letterSpacing: "-0.05em", lineHeight: 1, whiteSpace: "nowrap" };

function Hero({ onLogin, onNav, reduce, isMobile }: { onLogin: () => void; onNav: (id: string) => void; reduce: boolean; isMobile: boolean }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const cueRef = useRef<HTMLDivElement>(null);
  const wordsRef = useRef<HTMLDivElement>(null);
  const pillsRef = useRef<HTMLDivElement>(null);
  const n = HERO_WORDS.length;

  useScrollDrive(wrapRef, (p) => {
    if (gridRef.current) gridRef.current.style.transform = `translate3d(0,${p * -30}px,0)`;
    if (glowRef.current) glowRef.current.style.transform = `translate3d(0,${p * -60}px,0)`;
    if (cueRef.current) cueRef.current.style.opacity = `${clamp(1 - p * 8)}`;

    const els = wordsRef.current?.querySelectorAll<HTMLElement>("[data-word]");
    els?.forEach((el, i) => {
      const c = i / (n - 1); // 0, 0.5, 1
      const vis = clamp(1 - Math.abs(p - c) / 0.5);
      el.style.opacity = `${vis}`;
      el.style.transform = `translateY(${(c - p) * 120}px)`;
      el.style.pointerEvents = vis > 0.5 ? "auto" : "none";
    });

    const pills = pillsRef.current?.querySelectorAll<HTMLElement>("[data-pill]");
    const active = Math.round(p * (n - 1));
    pills?.forEach((pl, i) => {
      pl.style.width = i === active ? "40px" : "8px";
      pl.style.background = i <= active ? "#2563EB" : "transparent";
      pl.style.borderColor = i <= active ? "#2563EB" : "#C8C0B0";
    });
  }, "sticky", !reduce);

  /* Background layers, shared by both modes */
  const Backgrounds = (
    <>
      <div ref={gridRef} style={{ position: "absolute", inset: "-6%", zIndex: 0, pointerEvents: "none" }}>
        <div style={{
          position: "absolute", inset: 0,
          backgroundImage: "linear-gradient(rgba(58,48,33,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(58,48,33,0.05) 1px, transparent 1px), linear-gradient(rgba(58,48,33,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(58,48,33,0.07) 1px, transparent 1px)",
          backgroundSize: "46px 46px, 46px 46px, 230px 230px, 230px 230px",
          WebkitMaskImage: "radial-gradient(ellipse 80% 75% at 42% 40%, #000 30%, transparent 86%)",
          maskImage: "radial-gradient(ellipse 80% 75% at 42% 40%, #000 30%, transparent 86%)",
          animation: reduce ? "none" : "paiDrift 26s ease-in-out infinite",
        }} />
      </div>
      <div ref={glowRef} style={{
        position: "absolute", inset: 0, zIndex: 0, pointerEvents: "none",
        background: "radial-gradient(38% 34% at 82% 72%, rgba(37,99,235,0.10), transparent 72%), radial-gradient(42% 34% at 14% 24%, rgba(37,99,235,0.07), transparent 72%), radial-gradient(30% 28% at 60% 50%, rgba(22,163,74,0.05), transparent 70%)",
      }} />
    </>
  );

  /* Reduced motion → static stacked hero (no pin). */
  if (reduce) {
    return (
      <section id="top" style={{ position: "relative", width: "100%", minHeight: "100vh", background: "var(--bg-primary)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {Backgrounds}
        <HeroNav onLogin={onLogin} onNav={onNav} />
        <div style={{ position: "relative", zIndex: 2, flex: 1, display: "flex", alignItems: "center", padding: `0 ${PAD_X}` }}>
          <div>
            <div className="t-label" style={{ color: "#2563EB", marginBottom: 22 }}>THE FIRST ADAPTIVE LEARNING PLATFORM</div>
            {HERO_WORDS.map((w, i) => (
              <div key={i} style={{ display: "flex", gap: "0.2em", lineHeight: 0.92 }}>
                <span style={{ ...HERO_BIG, fontWeight: 700, color: "#1A1611" }}>One</span>
                <span style={{ ...HERO_BIG, fontWeight: 500, color: w.blue ? "#2563EB" : "#1A1611" }}>{w.t}</span>
              </div>
            ))}
            <p style={{ maxWidth: 460, marginTop: 28, fontFamily: "var(--ff-body)", fontSize: 16, lineHeight: 1.65, color: "#6E665A" }}>
              The first learning platform that builds a different course for every person who enrolls.
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <div id="top" ref={wrapRef} style={{ position: "relative", height: isMobile ? "260vh" : "320vh", background: "var(--bg-primary)" }}>
      <div style={{ position: "sticky", top: 0, height: "100vh", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {Backgrounds}
        <HeroNav onLogin={onLogin} onNav={onNav} />

        {/* Center — rotating headline */}
        <div style={{ position: "relative", zIndex: 2, flex: 1, display: "flex", alignItems: "center", padding: `0 ${PAD_X}` }}>
          <div style={{ width: "100%", maxWidth: 1180 }}>
            <div className="t-label" style={{ color: "#2563EB", marginBottom: "clamp(20px,4vh,40px)" }}>THE FIRST ADAPTIVE LEARNING PLATFORM</div>

            <div style={{ display: "flex", alignItems: "baseline", flexWrap: "wrap", gap: "0.2em" }}>
              <span style={{ ...HERO_BIG, fontWeight: 700, color: "#1A1611" }}>One</span>
              <span style={{ position: "relative", display: "inline-block" }}>
                {/* invisible sizer reserves the widest word's box */}
                <span aria-hidden style={{ ...HERO_BIG, fontWeight: 500, visibility: "hidden" }}>platform.</span>
                <div ref={wordsRef} style={{ position: "absolute", inset: 0 }}>
                  {HERO_WORDS.map((w, i) => (
                    <span key={i} data-word style={{
                      ...HERO_BIG, fontWeight: 500, position: "absolute", left: 0, top: 0,
                      color: w.blue ? "#2563EB" : "#1A1611",
                      opacity: i === 0 ? 1 : 0,
                      willChange: "opacity, transform",
                    }}>{w.t}</span>
                  ))}
                </div>
              </span>
            </div>

            {/* word-progress pills */}
            <div ref={pillsRef} style={{ display: "flex", gap: 8, marginTop: "clamp(24px,5vh,48px)" }}>
              {HERO_WORDS.map((_, i) => (
                <div key={i} data-pill style={{ height: 8, width: i === 0 ? 40 : 8, borderRadius: 4, background: i === 0 ? "#2563EB" : "transparent", border: `1.5px solid ${i === 0 ? "#2563EB" : "#C8C0B0"}`, transition: "width 320ms cubic-bezier(0.16,1,0.3,1), background 320ms linear, border-color 320ms linear" }} />
              ))}
            </div>

            <p style={{ maxWidth: 440, marginTop: 22, fontFamily: "var(--ff-body)", fontSize: 15, lineHeight: 1.65, color: "#6E665A" }}>
              The first learning platform that builds a different course for every person who enrolls.
            </p>
          </div>
        </div>

        {/* scroll cue */}
        <div ref={cueRef} style={{ position: "relative", zIndex: 2, display: "flex", flexDirection: "column", alignItems: "center", gap: 10, paddingBottom: 30 }}>
          <span style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 10.5, letterSpacing: "0.22em", textTransform: "uppercase", color: "#6E665A" }}>Scroll</span>
          <div style={{ width: 1, height: 34, background: HAIRLINE, position: "relative", overflow: "hidden" }}>
            <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: 12, background: "#2563EB", animation: "paiBob 1.8s ease-in-out infinite" }} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── MANIFESTO — pinned word-by-word build ───────────────────── */
function Manifesto({ reduce }: { reduce: boolean }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const wordsRef = useRef<HTMLDivElement>(null);
  const words = ["A", "different", "course", "for", "every", "single", "student."];

  useScrollDrive(wrapRef, (p) => {
    const els = wordsRef.current?.querySelectorAll<HTMLElement>("[data-w]");
    if (!els) return;
    const n = els.length;
    els.forEach((el, i) => {
      const seg = 1 / n;
      const local = clamp((p - i * seg) / (seg * 1.5));
      el.style.opacity = `${lerp(0.16, 1, local)}`;
      el.style.transform = `translateY(${lerp(16, 0, local)}px)`;
      const last = i === n - 1;
      el.style.color = local > 0.55 ? (last ? "#2563EB" : "#1A1611") : "#A89E8C";
    });
  }, "sticky", !reduce);

  return (
    <div ref={wrapRef} style={{ position: "relative", height: reduce ? "auto" : "220vh", background: "var(--bg-primary)" }}>
      <div style={{ position: reduce ? "static" : "sticky", top: 0, height: reduce ? "auto" : "100vh", display: "flex", alignItems: "center", overflow: "hidden", padding: `90px ${PAD_X}` }}>
        <div ref={wordsRef} style={{ display: "flex", flexWrap: "wrap", gap: "0.28em", maxWidth: 1100 }}>
          {words.map((w, i) => (
            <span key={i} data-w style={{
              fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(44px, 9vw, 116px)",
              letterSpacing: "-0.04em", lineHeight: 1.0,
              color: reduce ? "#1A1611" : "#A89E8C",
              transition: "color 320ms ease",
            }}>{w}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── PLACEMENT (Chapter 01) ──────────────────────────────────── */
function Placement({ reduce }: { reduce: boolean }) {
  const secRef = useRef<HTMLElement>(null);
  const bigRef = useRef<HTMLDivElement>(null);
  const lineRef = useRef<SVGLineElement>(null);

  useScrollDrive(secRef, (p) => {
    const off = (p - 0.5) * 2;
    if (bigRef.current) bigRef.current.style.transform = `translate3d(${off * -60}px,0,0)`;
    if (lineRef.current) {
      const len = 1400;
      lineRef.current.style.strokeDasharray = `${len}`;
      lineRef.current.style.strokeDashoffset = `${lerp(len, 0, clamp((p - 0.15) / 0.5))}`;
    }
  }, "through", !reduce);

  return (
    <section id="technology" ref={secRef} style={{ position: "relative", width: "100%", minHeight: 760, background: "var(--bg-surface)", overflow: "hidden", borderTop: `1px solid ${HAIRLINE}`, borderBottom: `1px solid ${HAIRLINE}` }}>
      <div ref={bigRef} style={{ position: "absolute", top: 20, left: -20, fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(200px, 32vw, 460px)", lineHeight: 0.82, color: "rgba(19,16,13,0.045)", letterSpacing: "-0.06em", pointerEvents: "none", userSelect: "none", zIndex: 0 }}>01</div>
      <svg className="pai-hide-mobile" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 1 }} preserveAspectRatio="none">
        <line ref={lineRef} x1="30%" y1="0%" x2="70%" y2="100%" stroke="#2563EB" strokeWidth="1" style={{ strokeDasharray: 1400, strokeDashoffset: reduce ? 0 : 1400 }} />
      </svg>

      <div style={{ position: "absolute", top: 24, left: 24, zIndex: 3 }}>
        <span className="t-label" style={{ color: "#2563EB" }}>CHAPTER 01 · THE TECHNOLOGY</span>
      </div>

      <div className="pai-p1-heading" style={{ position: "relative", zIndex: 3, paddingTop: 110, paddingLeft: 14, paddingRight: "40%" }}>
        <Reveal variant="up">
          <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(48px, 9vw, 104px)", color: "#1A1611", lineHeight: 0.9, letterSpacing: "-0.04em" }}>
            We map<br />where<br />you are.
          </div>
          <p style={{ marginTop: 30, maxWidth: 520, fontFamily: "var(--ff-body)", fontSize: 17, lineHeight: 1.55, color: "#6E665A" }}>
            Before your first slide, we map your knowledge — every gap, every strength. A short survey that shapes everything that follows.
          </p>
        </Reveal>
      </div>

      <div className="pai-p1-data" style={{ position: "absolute", top: 0, right: 0, width: "34%", height: "100%", zIndex: 3, display: "flex", flexDirection: "column", justifyContent: "center", gap: 40, padding: "0 clamp(28px,5vw,72px) 0 40px" }}>
        {[
          { big: <CountUp to={5} />, label: "CATEGORIES", desc: "Every topic assessed independently." },
          { big: <CountUp to={1} />, label: "PROFILE", desc: "Built for you alone — nobody shares it." },
        ].map((d, i) => (
          <Reveal key={i} variant="right" delay={i * 140} style={{ borderTop: `1px solid ${HAIRLINE}`, paddingTop: 16 }}>
            <div className="t-label" style={{ color: "#2563EB" }}>{`0${i + 1}`}</div>
            <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(40px,6vw,68px)", color: "#1A1611", marginTop: 6, letterSpacing: "-0.02em", display: "flex", alignItems: "baseline", gap: 10 }}>
              {d.big}<span style={{ fontSize: 18, color: "#6E665A", letterSpacing: "0.12em" }}>{d.label}</span>
            </div>
            <div style={{ fontFamily: "var(--ff-body)", fontSize: 13, color: "#837A6C", marginTop: 8 }}>{d.desc}</div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/* ── CURRICULUM (Chapter 02) ─────────────────────────────────── */
function Curriculum() {
  const ruleColor = "rgba(37,99,235,0.26)";
  const lines = [
    { text: "A", blue: false, hl: false },
    { text: "curriculum", blue: false, hl: false },
    { text: "built", blue: false, hl: true },
    { text: "around", blue: false, hl: false },
    { text: "you.", blue: true, hl: false },
  ];
  const tags = ["Your sequence. Nobody else has it.", "Topics ordered around your results.", "Built from your gaps, not a syllabus."];
  return (
    <section style={{ position: "relative", width: "100%", background: "var(--bg-primary)", overflow: "hidden", borderBottom: `1px solid ${HAIRLINE}` }}>
      <div style={{ position: "absolute", top: 24, left: 24, zIndex: 5 }}><span className="t-label" style={{ color: "#2563EB" }}>CHAPTER 02</span></div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,260px)", gap: 32, alignItems: "center", padding: `96px ${PAD_X} 96px` }}>
        <div>
          {lines.map((l, i) => (
            <Reveal key={i} variant="up" delay={i * 80} style={{ borderBottom: `1px solid ${ruleColor}` }}>
              {l.hl ? (
                <span style={{ display: "inline-block", background: "#16A34A", padding: "0 6px", marginLeft: -6 }}>
                  <span style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(44px, 8.5vw, 96px)", color: "#13100D", lineHeight: 1.02, letterSpacing: "-0.04em", display: "block" }}>{l.text}</span>
                </span>
              ) : (
                <span style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(44px, 8.5vw, 96px)", color: l.blue ? "#2563EB" : "#1A1611", lineHeight: 1.02, letterSpacing: "-0.04em", display: "inline-block" }}>{l.text}</span>
              )}
            </Reveal>
          ))}
        </div>
        <div className="pai-hide-mobile" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {tags.map((t, i) => (
            <Reveal key={i} variant="right" delay={i * 120} style={{ border: "1px solid #6E665A", borderRadius: 6, padding: "8px 12px", fontFamily: "var(--ff-mono)", fontSize: 11, color: "#6E665A", lineHeight: 1.4 }}>{t}</Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── ADAPTIVE SLIDES (Chapter 03) — pinned Novice↔Expert morph ─ */
function AdaptiveSlides({ reduce, isMobile }: { reduce: boolean; isMobile: boolean }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLDivElement>(null);
  const novRef = useRef<HTMLDivElement>(null);
  const expRef = useRef<HTMLDivElement>(null);
  const labelRef = useRef<HTMLSpanElement>(null);
  const pinned = !reduce && !isMobile;

  useScrollDrive(wrapRef, (p) => {
    if (fillRef.current) fillRef.current.style.width = `${p * 100}%`;
    if (thumbRef.current) thumbRef.current.style.left = `${p * 100}%`;
    if (labelRef.current) labelRef.current.textContent = p < 0.34 ? "NOVICE" : p < 0.67 ? "INTERMEDIATE" : "EXPERT";
    const expT = clamp((p - 0.34) / 0.4);
    if (novRef.current) { novRef.current.style.opacity = `${clamp(1 - expT * 1.2)}`; novRef.current.style.transform = `translateY(${expT * -26}px) scale(${lerp(1, 0.96, expT)}) rotate(${lerp(2, 0, expT)}deg)`; }
    if (expRef.current) { expRef.current.style.opacity = `${clamp(expT * 1.2)}`; expRef.current.style.transform = `translateY(${lerp(26, 0, expT)}px) scale(${lerp(0.96, 1, expT)}) rotate(${lerp(0, -1.5, expT)}deg)`; }
  }, "sticky", pinned);

  return (
    <div ref={wrapRef} style={{ position: "relative", height: pinned ? "260vh" : "auto", background: "var(--bg-primary)", borderBottom: `1px solid ${HAIRLINE}` }}>
      <div style={{ position: pinned ? "sticky" : "static", top: 0, height: pinned ? "100vh" : "auto", overflow: "hidden", display: "flex", alignItems: "center" }}>
        <div className="pai-slides-stageGrid" style={{ width: "100%", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 40, alignItems: "center", padding: `80px ${PAD_X}` }}>
          {/* left copy + slider */}
          <div>
            <div className="t-label" style={{ color: "#2563EB", marginBottom: 16 }}>CHAPTER 03</div>
            <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(40px, 6.5vw, 84px)", color: "#1A1611", lineHeight: 0.95, letterSpacing: "-0.04em" }}>
              Slides that<br />know your level.
            </div>
            <p style={{ marginTop: 24, maxWidth: 440, fontFamily: "var(--ff-body)", fontSize: 16, lineHeight: 1.55, color: "#6E665A" }}>
              A Novice and an Expert open the same course and never see the same slide. {pinned ? "Scroll — and watch the same lesson rewrite itself." : "The content adapts in real time to where you actually are."}
            </p>
            <div style={{ marginTop: 40, maxWidth: 420 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                <span className="t-label" style={{ color: "#6E665A" }}>MASTERY</span>
                <span ref={labelRef} className="t-label" style={{ color: "#2563EB" }}>{reduce ? "ADAPTIVE" : "NOVICE"}</span>
              </div>
              <div style={{ position: "relative", height: 2, background: HAIRLINE }}>
                <div ref={fillRef} style={{ position: "absolute", inset: "0 auto 0 0", width: reduce ? "100%" : "0%", background: "linear-gradient(90deg,#2563EB,#16A34A)" }} />
                <div ref={thumbRef} style={{ position: "absolute", top: "50%", left: reduce ? "100%" : "0%", transform: "translate(-50%,-50%)", width: 14, height: 14, borderRadius: "50%", background: "#fff", border: "2px solid #2563EB" }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12, fontFamily: "var(--ff-mono)", fontSize: 10, color: "#837A6C" }}>
                <span>NOVICE</span><span>INTERMEDIATE</span><span>EXPERT</span>
              </div>
            </div>
          </div>

          {/* right — morphing slide cards */}
          <div style={{ position: "relative", minHeight: 300, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div ref={novRef} style={{ ...(pinned ? { position: "absolute" } : {}), width: "100%", maxWidth: 420 }}>
              <SlideNovice />
            </div>
            <div ref={expRef} style={{ ...(pinned ? { position: "absolute", opacity: 0 } : { marginTop: 24 }), width: "100%", maxWidth: 420 }}>
              <SlideExpert />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
function SlideNovice() {
  return (
    <div style={{ background: "var(--bg-primary)", border: "1px solid var(--bg-paper-line)", borderRadius: 10, padding: "24px 26px", boxShadow: "10px 10px 0 rgba(0,0,0,0.35)", position: "relative" }}>
      <div style={{ fontFamily: "var(--ff-mono)", fontSize: 9, color: "#837A6C", marginBottom: 10 }}>slide 04 · loops_fundamentals</div>
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 22, color: "#13100D", lineHeight: 1.1 }}>What is a loop?</div>
      <div style={{ borderLeft: "2px solid #2563EB", paddingLeft: 12, marginTop: 14 }}>
        <span className="t-label" style={{ fontSize: 10, color: "#2563EB" }}>DEFINE · LOOP</span>
        <div style={{ fontFamily: "var(--ff-body)", fontSize: 13, color: "#13100D", marginTop: 4, lineHeight: 1.45 }}>A loop repeats a block of code while a condition stays true.</div>
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: "14px 0 0", display: "flex", flexDirection: "column", gap: 7 }}>
        <li style={{ fontFamily: "var(--ff-body)", fontSize: 12, color: "#13100D", display: "flex", gap: 8 }}><span style={{ width: 5, height: 5, background: "#13100D", marginTop: 4, flexShrink: 0 }} />A for loop runs a fixed number of times.</li>
        <li style={{ fontFamily: "var(--ff-body)", fontSize: 12, color: "#13100D", display: "flex", gap: 8 }}><span style={{ width: 5, height: 5, background: "#13100D", marginTop: 4, flexShrink: 0 }} />A while loop runs until the condition is false.</li>
      </ul>
      <div style={{ position: "absolute", top: 12, right: 14 }}><span className="t-label" style={{ fontSize: 9, color: "#2563EB", background: "rgba(37,99,235,0.1)", padding: "3px 6px" }}>NOVICE</span></div>
    </div>
  );
}
function SlideExpert() {
  return (
    <div style={{ background: "var(--bg-primary)", border: "1px solid var(--bg-paper-line)", borderRadius: 10, padding: "24px 26px", boxShadow: "10px 10px 0 rgba(22,163,74,0.28)", position: "relative" }}>
      <div style={{ fontFamily: "var(--ff-mono)", fontSize: 9, color: "#837A6C", marginBottom: 10 }}>slide 04 · loops_fundamentals</div>
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 20, color: "#13100D", lineHeight: 1.12 }}>Loop invariants & amortized cost</div>
      <div style={{ fontFamily: "var(--ff-body)", fontSize: 12.5, color: "#6E665A", marginTop: 10, lineHeight: 1.55 }}>Reason about a loop by the invariant it preserves each iteration. Establish it before, maintain it through, and it holds at termination — the basis of a correctness proof.</div>
      <div style={{ background: "#1A1611", color: "#E7E9F5", marginTop: 12, padding: "10px 12px", borderRadius: 6, fontFamily: "var(--ff-mono)", fontSize: 10.5, lineHeight: 1.6 }}>
        <div><span style={{ color: "#6E7793" }}># invariant: prefix [0:i] is sorted</span></div>
        <div><span style={{ color: "#FF7B72" }}>for</span> i <span style={{ color: "#FF7B72" }}>in</span> <span style={{ color: "#D2A8FF" }}>range</span>(<span style={{ color: "#FFA657" }}>1</span>, n): insort(a, i)</div>
      </div>
      <div style={{ position: "absolute", top: 12, right: 14 }}><span className="t-label" style={{ fontSize: 9, color: "#16A34A", background: "rgba(22,163,74,0.12)", padding: "3px 6px" }}>EXPERT</span></div>
    </div>
  );
}

/* ── EXPERIENCE — pinned horizontal gallery ──────────────────── */
function ExperienceGallery({ reduce, isMobile }: { reduce: boolean; isMobile: boolean }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLDivElement>(null);
  const pinned = !reduce && !isMobile;

  const panels = [
    { k: "intro" as const },
    { k: "placement" as const, n: "01", cap: "SESSION ZERO. WE LISTEN FIRST.", sub: "Generated specifically for your mastery level." },
    { k: "results" as const, n: "02", cap: "YOUR PLACEMENT, IN CONTEXT.", sub: "Your pathway. Nobody else has this exact sequence." },
    { k: "pathway" as const, n: "03", cap: "14 SESSIONS. ALL YOURS.", sub: "Slides written for where you are right now." },
    { k: "slide" as const, n: "04", cap: "EVERY SLIDE, GENERATED FOR YOU.", sub: "Calibrated to your performance history." },
    { k: "mcq" as const, n: "05", cap: "CHECKPOINTS THAT ADAPT.", sub: "They remember what you got wrong last time." },
  ];

  useScrollDrive(wrapRef, (p) => {
    const track = trackRef.current;
    if (track) {
      const max = track.scrollWidth - window.innerWidth;
      track.style.transform = `translate3d(${-clamp(p) * Math.max(0, max)}px,0,0)`;
    }
    if (fillRef.current) fillRef.current.style.width = `${p * 100}%`;
  }, "sticky", pinned);

  return (
    <div id="experience" ref={wrapRef} style={{ position: "relative", height: pinned ? `${panels.length * 58}vh` : "auto", background: "var(--bg-surface)", borderTop: `1px solid ${HAIRLINE}`, borderBottom: `1px solid ${HAIRLINE}` }}>
      <div style={{ position: pinned ? "sticky" : "static", top: 0, height: pinned ? "100vh" : "auto", overflow: "hidden", display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <div
          ref={trackRef}
          style={
            pinned
              ? { display: "flex", flexWrap: "nowrap", willChange: "transform" }
              : { display: "flex", flexWrap: "nowrap", overflowX: "auto", scrollSnapType: "x mandatory" }
          }
        >
          {panels.map((p, i) => {
            if (p.k === "intro") {
              return (
                <div key={i} style={{ flex: pinned ? "0 0 86vw" : "0 0 88vw", maxWidth: 720, scrollSnapAlign: "start", display: "flex", flexDirection: "column", justifyContent: "center", padding: `0 ${PAD_X}` }}>
                  <div className="t-label" style={{ color: "#2563EB", marginBottom: 18 }}>THE EXPERIENCE {pinned && "· SCROLL →"}</div>
                  <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(40px, 7vw, 88px)", color: "#1A1611", lineHeight: 0.98, letterSpacing: "-0.03em" }}>
                    Every session.<br />Built for one<br />student. <span style={{ color: "#2563EB" }}>You.</span>
                  </div>
                </div>
              );
            }
            return (
              <div key={i} className="pai-gpanel" style={{ flex: pinned ? "0 0 min(560px, 78vw)" : "0 0 86vw", maxWidth: 560, scrollSnapAlign: "start", borderLeft: `1px solid ${HAIRLINE}`, display: "grid", gridTemplateColumns: "1fr 1fr", minHeight: 420 }}>
                <div style={{ padding: "36px 26px", display: "flex", flexDirection: "column", justifyContent: "space-between", borderRight: `1px solid ${HAIRLINE}` }}>
                  <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(80px,9vw,128px)", color: "#2563EB", lineHeight: 0.82, letterSpacing: "-0.04em" }}>{p.n}</div>
                  <div>
                    <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 16, color: "#1A1611", lineHeight: 1.2 }}>{p.cap}</div>
                    <div style={{ fontFamily: "var(--ff-body)", fontSize: 12, color: "#837A6C", marginTop: 8 }}>{p.sub}</div>
                  </div>
                </div>
                <div style={{ position: "relative", overflow: "hidden", background: "var(--bg-primary)" }}>
                  {p.k === "placement" && <SPlacement />}
                  {p.k === "results" && <SResults />}
                  {p.k === "pathway" && <SPathway />}
                  {p.k === "slide" && <SSlide />}
                  {p.k === "mcq" && <SMCQ />}
                </div>
              </div>
            );
          })}
        </div>

        {pinned && (
          <div style={{ position: "absolute", left: PAD_X, right: PAD_X, bottom: 40 }}>
            <div style={{ height: 2, background: HAIRLINE, position: "relative" }}>
              <div ref={fillRef} style={{ position: "absolute", inset: "0 auto 0 0", width: "0%", background: "#2563EB" }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SPlacement() {
  return (
    <div style={{ position: "absolute", inset: 0, padding: 22 }}>
      <div style={{ height: 2, background: "#2563EB", width: "40%", marginBottom: 14 }} />
      <div className="t-label" style={{ fontSize: 9, color: "#837A6C" }}>QUESTION 04 / 18</div>
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 16, color: "#13100D", marginTop: 12, lineHeight: 1.3 }}>Which describes Python list behavior when passed to a function?</div>
      <div style={{ marginTop: 14 }}>
        {["Copied; mutations local.", "Primitives by value.", "Reference shared.", "Cannot be passed."].map((t, i) => (
          <div key={i} style={{ padding: "9px 10px", borderLeft: i === 2 ? "2px solid #2563EB" : "2px solid var(--bg-paper-line)", borderBottom: "1px solid var(--bg-paper-line)", fontSize: 11, color: "#13100D", fontWeight: i === 2 ? 600 : 400 }}>{t}</div>
        ))}
      </div>
    </div>
  );
}
function SResults() {
  const rows: [string, number, boolean][] = [["Syntax", 92, true], ["Reading", 84, true], ["Recursion", 38, false], ["Big-O", 51, false]];
  return (
    <div style={{ position: "absolute", inset: 0, padding: 22 }}>
      <div style={{ background: "#2563EB", color: "#fff", padding: "9px 13px", display: "inline-block" }} className="t-label">NOVICE · 58/100</div>
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 16, color: "#1A1611", marginTop: 16 }}>You're closer than you think.</div>
      {rows.map(([n, p, s], i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "78px 1fr 30px", gap: 8, alignItems: "center", padding: "8px 0", borderBottom: `1px solid ${HAIRLINE}` }}>
          <span style={{ fontSize: 11, color: "#1A1611" }}>{n}</span>
          <div style={{ height: 3, background: HAIRLINE }}><div style={{ width: `${p}%`, height: "100%", background: s ? "#16A34A" : "#2563EB" }} /></div>
          <span style={{ fontFamily: "var(--ff-mono)", fontSize: 9, color: "#837A6C" }}>{p}%</span>
        </div>
      ))}
    </div>
  );
}
function SPathway() {
  const rows = [
    { n: "01", t: "Variables", s: "done" }, { n: "02", t: "Control flow", s: "done" }, { n: "03", t: "Functions", s: "done" },
    { n: "04", t: "Lists", s: "done" }, { n: "05", t: "Recursion", s: "cur" }, { n: "06", t: "Big-O", s: "lock" }, { n: "07", t: "Trees", s: "lock" },
  ];
  return (
    <div style={{ position: "absolute", inset: 0, padding: 22, overflow: "hidden" }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 0", borderLeft: r.s === "cur" ? "2px solid #2563EB" : "2px solid transparent", paddingLeft: 8, borderBottom: `1px solid ${HAIRLINE}`, opacity: r.s === "lock" ? 0.4 : 1 }}>
          <span style={{ fontFamily: "var(--ff-mono)", fontSize: 9, color: r.s === "cur" ? "#2563EB" : r.s === "done" ? "#16A34A" : "#6E665A", width: 16 }}>{r.n}</span>
          <span style={{ fontSize: 12, color: r.s === "lock" ? "#6E665A" : "#1A1611" }}>{r.t}</span>
          <span style={{ marginLeft: "auto", fontSize: 11, color: r.s === "done" ? "#16A34A" : r.s === "cur" ? "#2563EB" : "#6E665A" }}>{r.s === "done" ? "✓" : r.s === "cur" ? "●" : "⌗"}</span>
        </div>
      ))}
    </div>
  );
}
function SSlide() {
  return (
    <div style={{ position: "absolute", inset: 0, padding: 18 }}>
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 16, color: "#13100D" }}>Base cases & termination</div>
      <div style={{ borderLeft: "2px solid #2563EB", paddingLeft: 10, marginTop: 12 }}>
        <span className="t-label" style={{ fontSize: 9, color: "#2563EB" }}>DEFINE</span>
        <div style={{ fontSize: 12, color: "#13100D", marginTop: 4, lineHeight: 1.4 }}>The smallest input for which a function returns directly.</div>
      </div>
      <div style={{ background: "#1A1611", color: "#E7E9F5", marginTop: 12, padding: "10px 12px", fontFamily: "var(--ff-mono)", fontSize: 10, lineHeight: 1.6 }}>
        <div><span style={{ color: "#FF7B72" }}>def</span> <span style={{ color: "#D2A8FF" }}>factorial</span>(n):</div>
        <div>{"  "}<span style={{ color: "#FF7B72" }}>if</span> n {"<="} <span style={{ color: "#FFA657" }}>1</span>: <span style={{ color: "#FF7B72" }}>return</span> <span style={{ color: "#FFA657" }}>1</span></div>
        <div>{"  "}<span style={{ color: "#FF7B72" }}>return</span> n * <span style={{ color: "#D2A8FF" }}>factorial</span>(n-<span style={{ color: "#FFA657" }}>1</span>)</div>
      </div>
    </div>
  );
}
function SMCQ() {
  return (
    <div style={{ position: "absolute", inset: 0, borderLeft: "1px solid #2563EB", padding: 22, overflow: "hidden" }}>
      <div className="t-label" style={{ fontSize: 9, color: "#2563EB" }}>KNOWLEDGE CHECK</div>
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 16, color: "#1A1611", marginTop: 12, lineHeight: 1.3 }}>What happens when n reaches 0 with no check?</div>
      {["Returns 0 by default.", "Stack overflow.", "Stops at depth 1000.", "Optimized to a loop."].map((t, i) => (
        <div key={i} style={{ padding: "10px 8px", borderLeft: i === 1 ? "2px solid #16A34A" : `2px solid ${HAIRLINE}`, borderBottom: `1px solid ${HAIRLINE}`, fontSize: 11, color: i === 1 ? "#1A1611" : "#837A6C", fontWeight: i === 1 ? 600 : 400, display: "flex", alignItems: "center", gap: 6 }}>
          {t}{i === 1 && <span style={{ marginLeft: "auto", width: 14, height: 14, background: "#16A34A", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700 }}>✓</span>}
        </div>
      ))}
    </div>
  );
}

/* ── ASSESSMENTS (Chapter 04) — answer locks on scroll ───────── */
function Assessments({ reduce }: { reduce: boolean }) {
  const secRef = useRef<HTMLElement>(null);
  const [locked, setLocked] = useState(reduce);
  useScrollDrive(secRef, (p) => { if (p > 0.55) setLocked(true); }, "through", !reduce);

  const options = [
    { t: "Linked lists are not sorted by default", correct: false },
    { t: "Linked lists do not support O(1) random access", correct: true },
    { t: "Binary search requires recursion", correct: false },
    { t: "Linked lists have no end pointer", correct: false },
  ];
  return (
    <section ref={secRef} style={{ position: "relative", width: "100%", background: "var(--bg-primary)", overflow: "hidden", borderBottom: `1px solid ${HAIRLINE}`, padding: `100px ${PAD_X} 110px` }}>
      <Reveal variant="up">
        <div className="t-label" style={{ color: "#2563EB", marginBottom: 14 }}>CHAPTER 04</div>
        <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(40px, 8vw, 88px)", color: "#1A1611", lineHeight: 0.95, letterSpacing: "-0.04em", maxWidth: 900 }}>
          Assessments<br />that adapt.
        </div>
      </Reveal>

      <div style={{ marginTop: 36, maxWidth: 860 }}>
        <Reveal variant="up" delay={60}>
          <div className="t-label" style={{ color: "#6E665A", marginBottom: 16 }}>SAMPLE QUESTION — SESSION 03</div>
          <div style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 18, color: "#1A1611", lineHeight: 1.4, marginBottom: 22 }}>
            Which of the following correctly explains why binary search cannot be applied to a linked list?
          </div>
        </Reveal>
        <div style={{ borderTop: `1px solid ${HAIRLINE}` }}>
          {options.map((o, i) => {
            const on = locked && o.correct;
            return (
              <Reveal key={i} variant="up" delay={i * 70} style={{ display: "flex", alignItems: "center", gap: 16, padding: "18px 0 18px 16px", borderBottom: `1px solid ${HAIRLINE}`, borderLeft: `2px solid ${on ? "#16A34A" : HAIRLINE}`, background: on ? "rgba(22,163,74,0.05)" : "transparent", transition: "border-color 400ms ease, background 400ms ease" }}>
                <div style={{ width: 18, height: 18, borderRadius: "50%", border: on ? "none" : "1.5px solid #6E665A", background: on ? "#2563EB" : "transparent", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", transition: "all 400ms ease" }}>
                  {on && <div style={{ width: 8, height: 8, background: "#fff", borderRadius: "50%" }} />}
                </div>
                <span style={{ flex: 1, fontFamily: "var(--ff-body)", fontSize: 15, color: on ? "#1A1611" : "#837A6C", fontWeight: on ? 500 : 400 }}>{o.t}</span>
                {on && <span className="t-label" style={{ color: "#16A34A", display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 14, height: 14, background: "#16A34A", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700 }}>✓</span>CORRECT</span>}
              </Reveal>
            );
          })}
        </div>
      </div>

      <Reveal variant="up" delay={80} style={{ marginTop: 44, paddingTop: 32, borderTop: `1px solid ${HAIRLINE}` }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 0 }}>
          {[["WRONG ANSWER", "NEW QUESTION TYPE"], ["TOPIC SCORE", "DISTRACTOR DIFFICULTY"], ["SESSION SCORE", "NEXT SESSION CONTENT"]].map(([l, r], i) => (
            <div key={i} style={{ padding: "16px 24px", borderRight: i < 2 ? `1px solid ${HAIRLINE}` : "none", display: "flex", alignItems: "center", gap: 12 }}>
              <span className="t-label" style={{ color: "#6E665A", flex: 1 }}>{l}</span>
              <span style={{ fontFamily: "var(--ff-mono)", fontSize: 13, color: "#2563EB" }}>→</span>
              <span style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 13, color: "#1A1611" }}>{r}</span>
            </div>
          ))}
        </div>
      </Reveal>
    </section>
  );
}

/* ── PRINCIPLE ───────────────────────────────────────────────── */
function Principle({ reduce }: { reduce: boolean }) {
  const secRef = useRef<HTMLElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const comparisons = [
    ["Same slides for everyone", "Slides matched to your level"],
    ["Fixed question difficulty", "Questions that calibrate"],
    ["One pathway for all", "Your pathway, built from your gaps"],
    ["Static assessments", "Assessments that adapt in real time"],
  ];
  useScrollDrive(secRef, (p) => {
    const off = (p - 0.5) * 2;
    if (dotRef.current) dotRef.current.style.transform = `translate3d(0,${off * 60}px,0)`;
    if (headRef.current) headRef.current.style.transform = `translate3d(${off * -40}px,0,0)`;
  }, "through", !reduce);

  return (
    <section id="research" ref={secRef} style={{ position: "relative", width: "100%", background: "var(--bg-primary)", padding: `140px ${PAD_X}`, overflow: "hidden" }}>
      <div ref={dotRef} style={{
        position: "absolute", inset: "-10% 0 -10% 0", pointerEvents: "none",
        backgroundImage: `radial-gradient(circle, ${HAIRLINE} 1px, transparent 1px)`, backgroundSize: "32px 32px",
        WebkitMaskImage: "radial-gradient(ellipse 80% 80% at center, transparent 12%, black 72%)",
        maskImage: "radial-gradient(ellipse 80% 80% at center, transparent 12%, black 72%)",
      }} />
      <div style={{ position: "relative", zIndex: 2, maxWidth: 1100 }}>
        <div ref={headRef}>
          <Reveal variant="up">
            <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(52px, 11vw, 132px)", color: "#1A1611", lineHeight: 0.9, letterSpacing: "-0.045em" }}>
              This platform<br />
              <span style={{ color: "transparent", WebkitTextStroke: "1.5px #1A1611" }}>does not</span><br />
              treat you<br />
              <span style={{ color: "#2563EB" }}>the same.</span>
            </div>
          </Reveal>
        </div>
        <Reveal variant="up" delay={80} style={{ marginTop: 40, maxWidth: 680 }}>
          <div style={{ fontFamily: "var(--ff-body)", fontSize: 17, color: "#6E665A", lineHeight: 1.65 }}>
            Every student who enrolls receives a different course. Different slides. Different questions. Different pace.
          </div>
          <div className="t-label" style={{ color: "#2563EB", marginTop: 18 }}>AUTOMATICALLY. NO CONFIGURATION REQUIRED.</div>
        </Reveal>
        <div style={{ marginTop: 72, maxWidth: 860 }}>
          <Reveal variant="up" style={{ display: "grid", gridTemplateColumns: "1fr 48px 1fr", paddingBottom: 14, borderBottom: `1px solid ${HAIRLINE}`, marginBottom: 4 }}>
            <span className="t-label" style={{ color: "#6E665A" }}>OTHER PLATFORMS</span><span />
            <span className="t-label" style={{ color: "#2563EB" }}>PERSONIFAI</span>
          </Reveal>
          {comparisons.map(([l, r], i) => (
            <Reveal key={i} variant="up" delay={i * 80} style={{ display: "grid", gridTemplateColumns: "1fr 48px 1fr", padding: "16px 0", borderBottom: `1px solid ${HAIRLINE}`, alignItems: "center" }}>
              <span style={{ fontFamily: "var(--ff-body)", fontSize: 14, color: "#6E665A" }}>{l}</span>
              <span style={{ fontFamily: "var(--ff-mono)", fontSize: 14, color: "#2563EB", textAlign: "center" }}>→</span>
              <span style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 14, color: "#1A1611" }}>{r}</span>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── PROMISE finale ──────────────────────────────────────────── */
function Promise({ onLogin, reduce }: { onLogin: () => void; reduce: boolean }) {
  const secRef = useRef<HTMLElement>(null);
  const bgRef = useRef<HTMLDivElement>(null);
  useScrollDrive(secRef, (p) => {
    if (bgRef.current) bgRef.current.style.transform = `translate3d(0,${(p - 0.5) * 80}px,0)`;
  }, "through", !reduce);
  return (
    <section ref={secRef} style={{ position: "relative", width: "100%", background: "var(--bg-surface)", padding: `140px ${PAD_X} 130px`, overflow: "hidden", borderTop: `1px solid ${HAIRLINE}` }}>
      <div ref={bgRef} style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "radial-gradient(50% 40% at 80% 30%, rgba(37,99,235,0.10), transparent 70%), radial-gradient(40% 40% at 10% 90%, rgba(22,163,74,0.08), transparent 70%)" }} />
      <div style={{ position: "relative", zIndex: 2 }}>
        <Reveal variant="up">
          <div className="t-label" style={{ color: "#2563EB", marginBottom: 30 }}>CHAPTER 06 · THE PROMISE</div>
          <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(44px, 9vw, 104px)", color: "#1A1611", lineHeight: 0.9, letterSpacing: "-0.04em", maxWidth: 1100 }}>
            This platform does not<br />treat you like everyone else.
          </div>
        </Reveal>
        <Reveal variant="up" delay={80}>
          <p style={{ marginTop: 44, maxWidth: 560, fontFamily: "var(--ff-body)", fontSize: 18, lineHeight: 1.65, color: "#6E665A" }}>
            Most courses assume you know nothing. Or everything. PersonifAI reads where you actually are and teaches from there.
          </p>
          <button onClick={onLogin} className="pai-cta-mag" style={{ marginTop: 56, width: "100%", maxWidth: 720, background: "#1A1814", color: "var(--bg-primary)", border: "none", borderRadius: 10, padding: "30px 40px", fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 15, letterSpacing: "0.14em", textTransform: "uppercase", cursor: "pointer", textAlign: "center" }}>
            START YOUR PLACEMENT SURVEY →
          </button>
        </Reveal>
      </div>
    </section>
  );
}

/* ── FOOTER ───────────────────────────────────────────────────── */
function SiteFooter({ onLogin, onNav }: { onLogin: () => void; onNav: (id: string) => void }) {
  const navMap: Record<string, string> = { Technology: "technology", Experience: "experience", Research: "research", FAQ: "faq" };
  return (
    <footer id="faq" style={{ width: "100%", background: "#EAE6DC", position: "relative", overflow: "hidden", borderTop: `1px solid ${HAIRLINE}` }}>
      <div className="pai-foot-grid" style={{ padding: `80px ${PAD_X} 48px`, display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr", gap: 56 }}>
        <Reveal variant="up" style={{ position: "relative" }}>
          <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: "clamp(56px, 11vw, 120px)", color: "rgba(19,16,13,0.06)", lineHeight: 0.92, letterSpacing: "-0.04em" }}>PERSONIFAI</div>
          <div style={{ marginTop: 18 }}>
            <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 24, letterSpacing: "-0.025em", color: "#1A1611" }}>Personif<span style={{ color: "#2563EB" }}>AI</span><span style={{ color: "#2563EB" }}>.</span></div>
            <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 24, color: "#1A1611", marginTop: 14, maxWidth: 360, lineHeight: 1.15 }}>A different course for every person who enrolls.</div>
          </div>
        </Reveal>
        <Reveal variant="up" delay={80} style={{ display: "flex", flexDirection: "column", gap: 14, paddingTop: 6 }}>
          <div className="t-label" style={{ color: "#6E665A", marginBottom: 4 }}>EXPLORE</div>
          {["Technology", "Experience", "Research", "FAQ"].map((l) => (
            <span key={l} className="pai-navlink" onClick={() => onNav(navMap[l])} style={{ fontFamily: "var(--ff-body)", fontSize: 14, color: "#6E665A", width: "fit-content" }}>{l}</span>
          ))}
        </Reveal>
        <Reveal variant="up" delay={160}>
          <div className="t-label" style={{ color: "#2563EB", marginBottom: 14 }}>EARLY ACCESS OPEN</div>
          <div style={{ display: "flex", border: "1px solid #C8C0B0", borderRadius: 8, overflow: "hidden" }}>
            <input style={{ flex: 1, background: "transparent", border: "none", outline: "none", padding: "13px 14px", fontFamily: "var(--ff-body)", fontSize: 13, color: "#13100D" }} placeholder="you@institution.edu" />
            <button onClick={onLogin} style={{ background: "#1A1814", color: "var(--bg-primary)", border: "none", padding: "13px 20px", cursor: "pointer", fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 15, flexShrink: 0 }}>→</button>
          </div>
          <button onClick={onLogin} className="btn btn-paper" style={{ marginTop: 16, width: "100%", justifyContent: "space-between", padding: "16px 20px" }}>NOTIFY ME <span>→</span></button>
          <div style={{ fontFamily: "var(--ff-body)", fontSize: 12, color: "#6E665A", marginTop: 16 }}>Built as a graduation project. Open to collaborators and researchers.</div>
        </Reveal>
      </div>
      <div className="pai-foot-row" style={{ borderTop: `1px solid ${HAIRLINE}`, padding: `20px ${PAD_X}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--ff-mono)", fontSize: 11, color: "#9A9080", letterSpacing: "0.04em" }}>© 2026 PersonifAI</span>
        <span style={{ fontFamily: "var(--ff-body)", fontSize: 12, color: "#9A9080" }}>Your data is used only to personalize your learning.</span>
      </div>
    </footer>
  );
}
