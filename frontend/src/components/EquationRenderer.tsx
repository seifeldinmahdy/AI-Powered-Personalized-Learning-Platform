import React, { useRef, useEffect, useState } from 'react';
import type { SlideEquationItem } from '../services/pathway';

interface EquationRendererProps {
  equations: SlideEquationItem[];
}

/**
 * Renders mathematical equations using KaTeX (loaded via CDN in index.html).
 * 
 * - Display equations: centered block with label and copy button
 * - Inline equations: rendered inline within text flow
 * - throwOnError: false — bad LaTeX shows a fallback error token, never crashes
 */
export function EquationRenderer({ equations }: EquationRendererProps) {
  if (!equations || equations.length === 0) return null;

  const displayEquations = equations.filter((eq) => eq.display);
  const inlineEquations = equations.filter((eq) => !eq.display);

  return (
    <div className="mt-6 mb-4" id="equation-block">
      {/* Display equations — centered blocks */}
      {displayEquations.length > 0 && (
        <div className="space-y-4">
          {displayEquations.map((eq, i) => (
            <DisplayEquation key={`display-${i}`} equation={eq} />
          ))}
        </div>
      )}

      {/* Inline equations — horizontal flow */}
      {inlineEquations.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {inlineEquations.map((eq, i) => (
            <InlineEquation key={`inline-${i}`} equation={eq} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Display equation (centered block) ──────────────────────────

function DisplayEquation({ equation }: { equation: SlideEquationItem }) {
  const mathRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (mathRef.current && (window as any).katex) {
      try {
        (window as any).katex.render(equation.latex, mathRef.current, {
          throwOnError: false,
          displayMode: true,
        });
      } catch {
        mathRef.current.textContent = equation.latex;
      }
    }
  }, [equation.latex]);

  const handleCopy = () => {
    navigator.clipboard.writeText(equation.latex).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div
      className="relative bg-gradient-to-r from-indigo-500/5 via-purple-500/5 to-transparent border border-indigo-300/30 rounded-xl p-5"
      style={{ fontFamily: "'Computer Modern', 'Latin Modern Math', serif" }}
    >
      {/* Label */}
      <div className="text-xs text-indigo-500/70 font-medium mb-2 tracking-wide uppercase">
        {equation.label}
      </div>

      {/* Rendered math */}
      <div
        ref={mathRef}
        className="text-center py-2 overflow-x-auto"
        style={{ fontSize: '1.15em' }}
      />

      {/* Copy button */}
      <button
        onClick={handleCopy}
        className="absolute top-3 right-3 text-xs px-2 py-1 rounded border transition-all"
        style={{
          color: copied ? '#22c55e' : '#888',
          borderColor: copied ? '#22c55e55' : '#3e3e4244',
          backgroundColor: copied ? '#22c55e11' : 'transparent',
        }}
        title="Copy LaTeX to clipboard"
      >
        {copied ? '✓ Copied' : 'Copy LaTeX'}
      </button>
    </div>
  );
}

// ── Inline equation ────────────────────────────────────────────

function InlineEquation({ equation }: { equation: SlideEquationItem }) {
  const mathRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (mathRef.current && (window as any).katex) {
      try {
        (window as any).katex.render(equation.latex, mathRef.current, {
          throwOnError: false,
          displayMode: false,
        });
      } catch {
        mathRef.current.textContent = equation.latex;
      }
    }
  }, [equation.latex]);

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 bg-indigo-500/5 border border-indigo-300/20 rounded-lg"
      style={{ fontFamily: "'Computer Modern', 'Latin Modern Math', serif" }}
    >
      <span className="text-[10px] text-indigo-400/60 font-medium">{equation.label}:</span>
      <span ref={mathRef} className="text-sm" />
    </span>
  );
}
