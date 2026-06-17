import { useEffect, useRef, useState } from "react";

/* Shared loading screen for the student experience (codex / pai design).
   Instead of a single static line, it types out a rotating set of messages
   with a typewriter + blinking-caret animation. Each caller passes messages
   that describe the specific thing being built, so the words always relate to
   what the student is actually waiting for. */

interface TypewriterLoaderProps {
  /** Small uppercase eyebrow, e.g. "PREPARING". */
  label?: string;
  /** Rotating phrases; each is typed, held, deleted, then the next begins. */
  messages: string[];
  /** Static caption under the typed line, e.g. "Tailored to <course>". */
  caption?: string;
  /** Fill the parent (flex:1) vs cover the viewport (fixed inset:0). */
  variant?: "inline" | "fixed";
}

/** Drives the type → hold → delete → next-message cycle for one string at a time. */
export function useTypewriter(
  messages: string[],
  { typeMs = 42, deleteMs = 22, holdMs = 1200 }: { typeMs?: number; deleteMs?: number; holdMs?: number } = {},
) {
  const [text, setText] = useState("");
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<"typing" | "holding" | "deleting">("typing");
  // Keep the latest messages without retriggering the effect on identity change.
  const msgRef = useRef(messages);
  msgRef.current = messages;

  useEffect(() => {
    const list = msgRef.current;
    if (list.length === 0) return;
    const current = list[idx % list.length] ?? "";
    let t: ReturnType<typeof setTimeout>;

    if (phase === "typing") {
      if (text.length < current.length) {
        t = setTimeout(() => setText(current.slice(0, text.length + 1)), typeMs);
      } else {
        t = setTimeout(() => setPhase("holding"), holdMs);
      }
    } else if (phase === "holding") {
      // A single message just types and holds — no jittery delete/retype loop.
      if (list.length > 1) t = setTimeout(() => setPhase("deleting"), 250);
    } else {
      if (text.length > 0) {
        t = setTimeout(() => setText(current.slice(0, text.length - 1)), deleteMs);
      } else {
        setIdx((i) => (i + 1) % list.length);
        setPhase("typing");
      }
    }
    return () => clearTimeout(t);
  }, [text, phase, idx, typeMs, deleteMs, holdMs]);

  return text;
}

export function TypewriterLoader({ label, messages, caption, variant = "inline" }: TypewriterLoaderProps) {
  const text = useTypewriter(messages);

  const shell: React.CSSProperties = variant === "fixed"
    ? { position: "fixed", inset: 0, zIndex: 60 }
    : { flex: 1 };

  return (
    <div
      className="codex"
      style={{ ...shell, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 18, textAlign: "center", padding: 24, background: "var(--bg-primary)" }}
    >
      {label && <div className="t-label" style={{ color: "var(--accent-primary)" }}>{label}</div>}
      <div className="t-display" style={{ fontSize: "clamp(26px,4vw,46px)", color: "var(--text-primary)", maxWidth: 720, minHeight: "1.35em", lineHeight: 1.15 }}>
        {text}
        <span className="pai-tw-caret" />
      </div>
      {caption && <div className="t-mono steel">{caption}</div>}
      <div style={{ width: 180, height: 2, background: "var(--hairline)", overflow: "hidden", marginTop: 8, position: "relative" }}>
        <div style={{ position: "absolute", height: "100%", width: "40%", background: "var(--accent-primary)", animation: "paiTwBar 1.1s ease-in-out infinite" }} />
      </div>
      <style>{`
        @keyframes paiTwBar { 0%{left:-40%} 100%{left:100%} }
        .pai-tw-caret { display:inline-block; width:3px; height:0.95em; margin-left:5px; background:var(--accent-primary); vertical-align:baseline; animation:paiTwBlink 1s step-end infinite; }
        @keyframes paiTwBlink { 0%,100%{opacity:1} 50%{opacity:0} }
      `}</style>
    </div>
  );
}
