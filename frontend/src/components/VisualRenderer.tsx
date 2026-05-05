import React from 'react';
import type { SlideVisual } from '../services/pathway';

interface VisualRendererProps {
  visual: SlideVisual;
}

export function VisualRenderer({ visual }: VisualRendererProps) {
  const tid = visual.template;
  const p = visual.params || {};

  const boxBase = 'mt-3 mb-2 rounded-lg text-sm box-border w-full flex-shrink-0';

  // Helper to guarantee we don't pass objects into ReactNodes which causes a fatal white-screen crash
  const safeText = (val: any): string => {
    if (typeof val === 'string') return val;
    if (typeof val === 'number') return String(val);
    if (typeof val === 'object' && val !== null) {
      return val.text || val.label || val.value || val.name || JSON.stringify(val);
    }
    return '';
  };

  // ── concept_box: a simple summary box ────────────────────────
  if (tid === 'concept_box') {
    const title = p.title || '';
    const points = Array.isArray(p.points) ? p.points : [];
    return (
      <div className={`${boxBase} bg-green-50 border border-green-300 p-4`}>
        <div className="font-bold text-green-800 text-base mb-2">{safeText(title)}</div>
        <ul className="list-disc m-0 pl-5 text-gray-700 space-y-1">
          {points.map((pt, i) => (
            <li key={i}>{safeText(pt)}</li>
          ))}
        </ul>
      </div>
    );
  }

  // ── comparison: two-column layout ────────────────────────────
  if (tid === 'comparison') {
    const lt = p.left_title || 'A';
    const rt = p.right_title || 'B';
    const li = Array.isArray(p.left_items) ? p.left_items : [];
    const ri = Array.isArray(p.right_items) ? p.right_items : [];
    return (
      <div className={`${boxBase} flex gap-4`}>
        <div className="flex-1 bg-blue-50 border border-blue-300 rounded-lg p-3">
          <div className="font-bold text-blue-800 text-center mb-2">{safeText(lt)}</div>
          <ul className="list-disc m-0 pl-5 text-gray-700 space-y-1 text-xs">
            {li.map((x, i) => (
              <li key={i}>{safeText(x)}</li>
            ))}
          </ul>
        </div>
        <div className="flex-1 bg-amber-50 border border-amber-300 rounded-lg p-3">
          <div className="font-bold text-amber-900 text-center mb-2">{safeText(rt)}</div>
          <ul className="list-disc m-0 pl-5 text-gray-700 space-y-1 text-xs">
            {ri.map((x, i) => (
              <li key={i}>{safeText(x)}</li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  // ── flowchart / process_flow: vertical steps with arrows ─────
  if (tid === 'flowchart' || tid === 'process_flow') {
    let labels: string[] = [];
    if (Array.isArray(p.steps) && p.steps.length > 0) {
      labels = p.steps;
    } else if (Array.isArray(p.nodes)) {
      labels = p.nodes.map((n: any) =>
        typeof n === 'object' ? n.label || n.id || '' : String(n)
      );
    }
    if (labels.length === 0) labels = ['Step 1', 'Step 2', 'Step 3'];

    return (
      <div className={`${boxBase} py-2 flex flex-col items-center`}>
        {labels.slice(0, 6).map((lbl, i) => (
          <React.Fragment key={i}>
            <div
              className={`border border-blue-300 rounded pb-1 pt-1 px-4 text-center text-blue-900 text-xs w-[80%] shadow-sm ${
                i % 2 === 0 ? 'bg-blue-100' : 'bg-indigo-50'
              }`}
            >
              {safeText(lbl)}
            </div>
            {i < labels.length - 1 && i < 5 && (
              <div className="text-center text-gray-500 text-lg leading-none py-1">
                ↓
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
    );
  }

  // ── linear_chain: horizontal boxes with arrows ───────────────
  if (tid === 'linear_chain') {
    const nodes = Array.isArray(p.nodes) ? p.nodes : ['A', 'B', 'C'];
    return (
      <div className={`${boxBase} flex flex-wrap items-center justify-center gap-2 py-2`}>
        {nodes.slice(0, 6).map((nd, i) => (
          <React.Fragment key={i}>
            <div className="bg-sky-100 border border-sky-300 shadow-sm rounded px-3 py-1 text-xs text-sky-900 whitespace-nowrap">
              {safeText(nd)}
            </div>
            {i < nodes.length - 1 && i < 5 && (
              <div className="text-gray-500 text-lg font-bold">→</div>
            )}
          </React.Fragment>
        ))}
      </div>
    );
  }

  // ── stack: vertical boxes (top on top) ───────────────────────
  if (tid === 'stack') {
    const items = Array.isArray(p.items) ? p.items : ['Item 1', 'Item 2', 'Item 3'];
    const topLabel = p.top_label || 'TOP';
    return (
      <div className={`${boxBase} border-2 border-blue-300 rounded-lg overflow-hidden w-2/3 mx-auto mt-4 shadow-sm`}>
        {items.slice(0, 5).map((item, i) => {
          const isTop = i === 0;
          return (
            <div
              key={i}
              className={`border-b border-blue-300 p-2 text-center text-xs text-sky-900 ${
                isTop ? 'bg-blue-200 font-bold' : 'bg-sky-50'
              }`}
            >
              {isTop ? `${topLabel} → ${safeText(item)}` : safeText(item)}
            </div>
          );
        })}
      </div>
    );
  }

  // ── cycle: circular arrows ───────────────────────────────────
  if (tid === 'cycle') {
    const nodes = Array.isArray(p.nodes) ? p.nodes : ['A', 'B', 'C'];
    return (
      <div className={`${boxBase} flex items-center justify-center flex-wrap gap-2 py-2`}>
        {nodes.slice(0, 5).map((nd, i) => (
          <React.Fragment key={i}>
            <span className="bg-amber-100 border border-amber-300 shadow-sm rounded px-3 py-1 text-xs text-amber-900">
              {safeText(nd)}
            </span>
            <span className="text-gray-500 text-lg font-bold">→</span>
          </React.Fragment>
        ))}
        <span className="text-gray-500 text-2xl font-bold">↻</span>
      </div>
    );
  }

  // ── info_card: key/value pairs ───────────────────────────────
  if (tid === 'info_card') {
    const title = p.title || 'Information';
    const items = Array.isArray(p.items) ? p.items : [];
    return (
      <div className={`${boxBase} overflow-hidden rounded-lg border border-blue-300 shadow-sm`}>
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <td colSpan={2} className="bg-blue-700 text-white p-2 font-bold text-center text-xs">
                {safeText(title)}
              </td>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 5).map((item: any, i) => (
              <tr key={i} className="border-b border-blue-200 last:border-b-0">
                <td className="p-2 bg-blue-50 font-semibold border-r border-blue-200 text-xs w-1/3">
                  {safeText(item.key)}
                </td>
                <td className="p-2 bg-white text-xs">{safeText(item.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // ── default / fallback ───────────────────────────────────────
  return (
    <div className="mt-4 p-4 bg-accent/5 border border-accent/20 rounded-xl w-full">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold text-accent font-mono">
          [Visual Component Active]
        </span>
      </div>
      <p className="text-xs font-bold text-secondary">
        {tid.replace(/_/g, ' ').toUpperCase()}
      </p>
    </div>
  );
}
