import React from 'react';
import type { CSSProperties } from 'react';
import type { SlideVisual } from '../services/pathway';

/**
 * Renders the slide generator's `{ template, params }` visuals client-side, in
 * the personifAI design language (paper palette, hairlines, accent blue/green,
 * JetBrains Mono labels). Covers every template the generator can emit
 * (see slides-generator/.../visual_param_generator.py + visual_classifier.py):
 *
 *   linear_chain · binary_tree · general_tree · stack · queue · graph
 *   flowchart · cycle · comparison · venn_diagram · bar_chart
 *   concept_box · analogy_diagram · architecture_diagram (XML) · conceptual
 *
 * `conceptual` carries the real layout in params._enriched_template;
 * `architecture_diagram` carries a raw XML string as its params.
 */

interface VisualRendererProps {
  visual: SlideVisual;
}

// ── Shared style tokens (personifAI) ───────────────────────────────
const wrap: CSSProperties = { marginTop: 14, marginBottom: 4, width: '100%', boxSizing: 'border-box' };
const card: CSSProperties = { background: 'var(--bg-paper)', border: '1px solid var(--hairline)', borderRadius: 8, padding: 16 };
const node: CSSProperties = {
  padding: '8px 12px', background: 'var(--bg-surface)', border: '1px solid var(--hairline)',
  borderRadius: 8, fontSize: 13, color: 'var(--text-primary)', textAlign: 'center', lineHeight: 1.4,
};
const accentNode: CSSProperties = {
  ...node, background: 'rgba(37,99,235,0.06)', borderColor: 'var(--accent-primary)',
  color: 'var(--accent-primary)', fontWeight: 600,
};
const arrowStyle: CSSProperties = { color: 'var(--steel-light)', fontSize: 18, lineHeight: 1, textAlign: 'center', flexShrink: 0 };

// Guarantee we never pass an object into a ReactNode (would white-screen crash).
const safeText = (val: any): string => {
  if (typeof val === 'string') return val;
  if (typeof val === 'number') return String(val);
  if (typeof val === 'object' && val !== null) {
    return val.text || val.label || val.value || val.name || JSON.stringify(val);
  }
  return '';
};
const asArray = (v: any): any[] => (Array.isArray(v) ? v : []);

function VTitle({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 12, textAlign: 'center' }}>
      {children}
    </div>
  );
}

function Bullets({ items }: { items: any[] }) {
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((pt, i) => (
        <li key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span style={{ width: 6, height: 6, marginTop: 7, flexShrink: 0, background: 'var(--accent-primary)' }} />
          <span className="t-body" style={{ fontSize: 13, color: 'var(--text-primary)' }}>{safeText(pt)}</span>
        </li>
      ))}
    </ul>
  );
}

// ── Architecture XML parsing ────────────────────────────────────────
interface ArchComponent { id: string; label: string; role: string; connects: { to: string; label: string }[]; }
interface Arch { title: string; layout: string; style: string; comps: ArchComponent[]; }

function parseArchitecture(xml: string): Arch | null {
  try {
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    if (doc.querySelector('parsererror')) return null;
    const archEl = doc.querySelector('architecture');
    if (!archEl) return null;
    const layout = archEl.getAttribute('layout') || 'hierarchical';
    if (layout === 'none') return null;
    const comps: ArchComponent[] = Array.from(archEl.querySelectorAll('component')).map((c) => ({
      id: c.getAttribute('id') || '',
      label: c.getAttribute('label') || '',
      role: c.getAttribute('role') || 'worker',
      connects: Array.from(c.querySelectorAll('connects')).map((cn) => ({
        to: cn.getAttribute('to') || '',
        label: cn.getAttribute('label') || '',
      })),
    }));
    if (comps.length === 0) return null;
    return { title: archEl.getAttribute('title') || '', layout, style: archEl.getAttribute('style') || 'component', comps };
  } catch {
    return null;
  }
}

const ROLE_LABEL: Record<string, string> = {
  master: 'MASTER', worker: 'WORKER', processor: 'PROCESSOR',
  storage: 'STORAGE', input: 'INPUT', output: 'OUTPUT', layer: 'LAYER',
};

export function VisualRenderer({ visual }: VisualRendererProps) {
  const rawParams = visual.params as unknown;
  const p: Record<string, any> = (rawParams && typeof rawParams === 'object') ? (rawParams as Record<string, any>) : {};

  // conceptual → the real layout lives in _enriched_template
  let tid = visual.template;
  if (tid === 'conceptual' || p._enriched_template) {
    tid = (p._enriched_template as string) || 'concept_box';
  }
  if (tid === 'process_flow') tid = 'flowchart'; // legacy alias

  // ── architecture_diagram: params is a raw XML string ──────────────
  if (tid === 'architecture_diagram') {
    const xml = typeof rawParams === 'string' ? rawParams : (typeof p.xml === 'string' ? p.xml : '');
    const arch = xml ? parseArchitecture(xml) : null;
    if (!arch) return <Fallback tid={tid} />;
    return <ArchitectureView arch={arch} />;
  }

  // ── concept_box ───────────────────────────────────────────────────
  if (tid === 'concept_box') {
    return (
      <div style={wrap}>
        <div style={{ ...card, borderLeft: '3px solid var(--accent-success)' }}>
          {p.title && <div className="t-label" style={{ color: 'var(--accent-success)', marginBottom: 12 }}>{safeText(p.title)}</div>}
          <Bullets items={asArray(p.points)} />
        </div>
      </div>
    );
  }

  // ── comparison ────────────────────────────────────────────────────
  if (tid === 'comparison') {
    const li = asArray(p.left_items);
    const ri = asArray(p.right_items);
    return (
      <div style={wrap}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <ComparisonCol title={safeText(p.left_title || 'A')} items={li} accent="var(--accent-primary)" tint="rgba(37,99,235,0.05)" />
          <ComparisonCol title={safeText(p.right_title || 'B')} items={ri} accent="var(--accent-warm)" tint="rgba(22,163,74,0.05)" />
        </div>
      </div>
    );
  }

  // ── venn_diagram ──────────────────────────────────────────────────
  if (tid === 'venn_diagram') {
    return (
      <div style={wrap}>
        <VTitle>{p.title ? safeText(p.title) : ''}</VTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, alignItems: 'stretch' }}>
          <VennZone label={safeText(p.left_label || 'Left')} items={asArray(p.left_only)} accent="var(--accent-primary)" tint="rgba(37,99,235,0.05)" />
          <VennZone label="Shared" items={asArray(p.shared)} accent="var(--accent-success)" tint="rgba(22,163,74,0.08)" emphasized />
          <VennZone label={safeText(p.right_label || 'Right')} items={asArray(p.right_only)} accent="var(--accent-warm)" tint="rgba(22,163,74,0.05)" />
        </div>
      </div>
    );
  }

  // ── analogy_diagram ───────────────────────────────────────────────
  if (tid === 'analogy_diagram') {
    const mappings = asArray(p.mappings);
    return (
      <div style={wrap}>
        <VTitle>{p.title ? safeText(p.title) : ''}</VTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 8, alignItems: 'center' }}>
          <div className="t-label" style={{ textAlign: 'center', color: 'var(--accent-primary)' }}>{safeText(p.familiar_label || 'Familiar')}</div>
          <div />
          <div className="t-label" style={{ textAlign: 'center', color: 'var(--accent-warm)' }}>{safeText(p.technical_label || 'Technical')}</div>
          {mappings.map((m: any, i: number) => (
            <React.Fragment key={i}>
              <div style={node}>{safeText(m.familiar)}</div>
              <div style={{ ...arrowStyle, fontSize: 15 }}>↔</div>
              <div style={accentNode}>{safeText(m.technical)}</div>
            </React.Fragment>
          ))}
        </div>
      </div>
    );
  }

  // ── linear_chain ──────────────────────────────────────────────────
  if (tid === 'linear_chain') {
    const nodes = asArray(p.nodes);
    const showNull = p.show_null !== false;
    return (
      <div style={wrap}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
          {nodes.slice(0, 8).map((nd, i) => (
            <React.Fragment key={i}>
              <div style={node}>{safeText(nd)}</div>
              {i < nodes.length - 1 && <span style={arrowStyle}>→</span>}
            </React.Fragment>
          ))}
          {showNull && nodes.length > 0 && (
            <>
              <span style={arrowStyle}>→</span>
              <div className="t-mono" style={{ ...node, color: 'var(--steel-light)', fontStyle: 'italic' }}>null</div>
            </>
          )}
        </div>
      </div>
    );
  }

  // ── cycle ─────────────────────────────────────────────────────────
  if (tid === 'cycle') {
    const nodes = asArray(p.nodes);
    return (
      <div style={wrap}>
        <VTitle>{p.title ? safeText(p.title) : ''}</VTitle>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
          {nodes.slice(0, 6).map((nd, i) => (
            <React.Fragment key={i}>
              <div style={accentNode}>{safeText(nd)}</div>
              {i < nodes.length - 1 && <span style={arrowStyle}>→</span>}
            </React.Fragment>
          ))}
          {nodes.length > 1 && (
            <span className="t-mono" style={{ color: 'var(--steel-light)', fontSize: 12, marginLeft: 4 }}>↻ back to {safeText(nodes[0])}</span>
          )}
        </div>
      </div>
    );
  }

  // ── flowchart (typed nodes + edge labels) ─────────────────────────
  if (tid === 'flowchart') {
    let steps: { label: string; type: string }[] = [];
    if (asArray(p.nodes).length > 0 && typeof p.nodes[0] === 'object') {
      steps = p.nodes.map((n: any) => ({ label: safeText(n.label || n.id), type: n.type || 'box' }));
    } else if (asArray(p.steps).length > 0) {
      steps = p.steps.map((s: any) => ({ label: safeText(s), type: 'box' }));
    } else if (asArray(p.nodes).length > 0) {
      steps = p.nodes.map((n: any) => ({ label: safeText(n), type: 'box' }));
    }
    if (steps.length === 0) steps = [{ label: 'Step 1', type: 'box' }];

    // edge labels keyed by source node id/label → list of {to,label}
    const edges = asArray(p.edges);
    const labelOf = (id: string) => {
      const m = asArray(p.nodes).find((n: any) => (n?.id ?? n) === id);
      return m ? safeText(m.label || m.id || m) : id;
    };

    return (
      <div style={wrap}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          {steps.slice(0, 6).map((st, i) => {
            const isDecision = st.type === 'diamond';
            const isTerminal = st.type === 'circle';
            const ns: CSSProperties = isDecision
              ? { ...accentNode, borderStyle: 'dashed' }
              : isTerminal
                ? { ...node, borderRadius: 999, padding: '6px 18px' }
                : node;
            return (
              <React.Fragment key={i}>
                <div style={{ ...ns, minWidth: 120, maxWidth: '85%' }}>
                  {isDecision && <span className="t-mono" style={{ fontSize: 9, display: 'block', opacity: 0.7 }}>DECISION</span>}
                  {st.label}
                </div>
                {i < steps.length - 1 && i < 5 && <span style={arrowStyle}>↓</span>}
              </React.Fragment>
            );
          })}
        </div>
        {edges.some((e: any) => e?.label) && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginTop: 12 }}>
            {edges.filter((e: any) => e?.label).slice(0, 6).map((e: any, i: number) => (
              <span key={i} className="t-mono" style={{ fontSize: 11, padding: '3px 8px', borderRadius: 6, border: '1px solid var(--hairline)', background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
                {labelOf(e.from)} —{safeText(e.label)}→ {labelOf(e.to)}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── stack (LIFO, top first) ───────────────────────────────────────
  if (tid === 'stack') {
    const items = asArray(p.items);
    return (
      <div style={wrap}>
        <div style={{ width: '60%', minWidth: 200, margin: '0 auto', border: '1px solid var(--hairline)', borderRadius: 8, overflow: 'hidden' }}>
          {items.slice(0, 6).map((it, i) => (
            <div key={i} style={{ padding: '9px 12px', textAlign: 'center', fontSize: 13, color: i === 0 ? 'var(--accent-primary)' : 'var(--text-primary)', fontWeight: i === 0 ? 600 : 400, background: i === 0 ? 'rgba(37,99,235,0.06)' : 'var(--bg-surface)', borderBottom: i < items.length - 1 ? '1px solid var(--hairline)' : 'none' }}>
              {i === 0 && <span className="t-mono" style={{ fontSize: 10, marginRight: 6, opacity: 0.8 }}>{safeText(p.top_label || 'TOP')} →</span>}
              {safeText(it)}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── queue (FIFO, front → back) ────────────────────────────────────
  if (tid === 'queue') {
    const items = asArray(p.items);
    return (
      <div style={wrap}>
        <div style={{ display: 'flex', justifyContent: 'space-between', maxWidth: 420, margin: '0 auto 6px' }}>
          <span className="t-mono" style={{ fontSize: 10, color: 'var(--accent-primary)' }}>← {safeText(p.front_label || 'FRONT')}</span>
          <span className="t-mono" style={{ fontSize: 10, color: 'var(--accent-warm)' }}>{safeText(p.back_label || 'BACK')} ←</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, flexWrap: 'wrap' }}>
          {items.slice(0, 6).map((it, i) => (
            <React.Fragment key={i}>
              <div style={node}>{safeText(it)}</div>
              {i < items.length - 1 && <span style={arrowStyle}>→</span>}
            </React.Fragment>
          ))}
        </div>
      </div>
    );
  }

  // ── binary_tree ───────────────────────────────────────────────────
  if (tid === 'binary_tree') {
    const lc = asArray(p.left_children);
    const rc = asArray(p.right_children);
    return (
      <div style={wrap}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <div style={accentNode}>{safeText(p.root || 'root')}</div>
          <span style={arrowStyle}>╱ ╲</span>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
            <TreeBranch parent={safeText(p.left)} children={lc} />
            <TreeBranch parent={safeText(p.right)} children={rc} />
          </div>
        </div>
      </div>
    );
  }

  // ── general_tree (recursive) ──────────────────────────────────────
  if (tid === 'general_tree') {
    const root = safeText(p.root);
    const children: Record<string, any[]> = (p.children && typeof p.children === 'object') ? p.children : {};
    const rel = safeText(p.relationship_label);
    return (
      <div style={wrap}>
        <VTitle>{p.title ? safeText(p.title) : ''}</VTitle>
        <GeneralTreeNode label={root} children={children} rel={rel} depth={0} />
      </div>
    );
  }

  // ── graph (nodes + edges) ─────────────────────────────────────────
  if (tid === 'graph') {
    const nodes = asArray(p.nodes);
    const edges = asArray(p.edges);
    const directed = p.directed !== false;
    return (
      <div style={wrap}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginBottom: 12 }}>
          {nodes.slice(0, 8).map((nd, i) => <div key={i} style={accentNode}>{safeText(nd)}</div>)}
        </div>
        {edges.length > 0 && (
          <div style={{ ...card, padding: 12 }}>
            <div className="t-label" style={{ color: 'var(--text-secondary)', marginBottom: 8 }}>{directed ? 'Edges' : 'Connections'}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {edges.slice(0, 12).map((e: any, i: number) => {
                const a = Array.isArray(e) ? e[0] : e?.from;
                const b = Array.isArray(e) ? e[1] : e?.to;
                return (
                  <span key={i} className="t-mono" style={{ fontSize: 11, padding: '3px 8px', borderRadius: 6, border: '1px solid var(--hairline)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}>
                    {safeText(nodes[a] ?? a)} {directed ? '→' : '—'} {safeText(nodes[b] ?? b)}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── bar_chart ─────────────────────────────────────────────────────
  if (tid === 'bar_chart') {
    const labels = asArray(p.labels);
    const values = asArray(p.values).map((v: any) => Number(v) || 0);
    const max = Math.max(1, ...values);
    return (
      <div style={wrap}>
        <VTitle>{p.title ? safeText(p.title) : ''}</VTitle>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {labels.slice(0, 8).map((lbl, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="t-mono" style={{ fontSize: 11, color: 'var(--text-secondary)', width: 90, textAlign: 'right', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{safeText(lbl)}</span>
              <div style={{ flex: 1, height: 22, background: 'var(--bg-surface)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${(values[i] ?? 0) / max * 100}%`, height: '100%', background: 'var(--accent-primary)', borderRadius: 4, transition: 'width 300ms ease' }} />
              </div>
              <span className="t-mono" style={{ fontSize: 11, color: 'var(--text-primary)', width: 40, flexShrink: 0 }}>{values[i] ?? 0}</span>
            </div>
          ))}
        </div>
        {(p.xlabel || p.ylabel) && (
          <div className="t-mono" style={{ fontSize: 10, color: 'var(--steel-light)', textAlign: 'center', marginTop: 8 }}>
            {safeText(p.ylabel)}{p.ylabel && p.xlabel ? ' · ' : ''}{safeText(p.xlabel)}
          </div>
        )}
      </div>
    );
  }

  // ── info_card (legacy key/value) ──────────────────────────────────
  if (tid === 'info_card') {
    const items = asArray(p.items);
    return (
      <div style={wrap}>
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          {p.title && <div className="t-label" style={{ background: 'var(--ink-black)', color: 'var(--bg-paper)', padding: '10px 14px', textAlign: 'center' }}>{safeText(p.title)}</div>}
          {items.slice(0, 6).map((it: any, i: number) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1.6fr', borderTop: '1px solid var(--hairline)' }}>
              <div className="t-mono" style={{ padding: '8px 12px', fontSize: 12, background: 'var(--bg-surface)', color: 'var(--text-secondary)', borderRight: '1px solid var(--hairline)' }}>{safeText(it.key)}</div>
              <div className="t-body" style={{ padding: '8px 12px', fontSize: 13, color: 'var(--text-primary)' }}>{safeText(it.value)}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── default / unknown ─────────────────────────────────────────────
  return <Fallback tid={tid} />;
}

// ── Sub-components ──────────────────────────────────────────────────

function ComparisonCol({ title, items, accent, tint }: { title: string; items: any[]; accent: string; tint: string }) {
  return (
    <div style={{ background: tint, border: `1px solid ${accent}`, borderRadius: 8, padding: 14 }}>
      <div className="t-label" style={{ color: accent, textAlign: 'center', marginBottom: 10 }}>{title}</div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 7 }}>
        {items.slice(0, 6).map((x, i) => (
          <li key={i} className="t-body" style={{ fontSize: 12, color: 'var(--text-primary)', display: 'flex', gap: 8 }}>
            <span style={{ width: 5, height: 5, marginTop: 6, flexShrink: 0, background: accent, borderRadius: '50%' }} />
            {safeText(x)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function VennZone({ label, items, accent, tint, emphasized }: { label: string; items: any[]; accent: string; tint: string; emphasized?: boolean }) {
  return (
    <div style={{ background: tint, border: `${emphasized ? 2 : 1}px solid ${accent}`, borderRadius: emphasized ? 8 : 80, padding: 14, display: 'flex', flexDirection: 'column' }}>
      <div className="t-label" style={{ color: accent, textAlign: 'center', marginBottom: 8 }}>{label}</div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 5 }}>
        {items.slice(0, 5).map((x, i) => (
          <li key={i} className="t-body" style={{ fontSize: 11, color: 'var(--text-primary)', textAlign: 'center' }}>{safeText(x)}</li>
        ))}
      </ul>
    </div>
  );
}

function TreeBranch({ parent, children }: { parent: string; children: any[] }) {
  if (!parent) return <div />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <div style={node}>{parent}</div>
      {children.length > 0 && (
        <>
          <span style={{ ...arrowStyle, fontSize: 13 }}>↓</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'center' }}>
            {children.slice(0, 4).map((c, i) => (
              <div key={i} style={{ ...node, padding: '5px 9px', fontSize: 12 }}>{safeText(c)}</div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function GeneralTreeNode({ label, children, rel, depth }: { label: string; children: Record<string, any[]>; rel: string; depth: number }) {
  const kids = asArray(children[label]);
  return (
    <div style={{ marginLeft: depth > 0 ? 18 : 0 }}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <div style={depth === 0 ? accentNode : { ...node, padding: '5px 10px', fontSize: 12 }}>{label}</div>
        {rel && kids.length > 0 && <span className="t-mono" style={{ fontSize: 9, color: 'var(--steel-light)' }}>{rel}</span>}
      </div>
      {kids.length > 0 && (
        <div style={{ borderLeft: '1px solid var(--hairline)', marginLeft: 12, marginTop: 6, paddingLeft: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {kids.slice(0, 6).map((k, i) => (
            <GeneralTreeNode key={i} label={safeText(k)} children={children} rel={rel} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function ArchitectureView({ arch }: { arch: Arch }) {
  const labelOf = (id: string) => arch.comps.find((c) => c.id === id)?.label || id;

  if (arch.style === 'layered') {
    return (
      <div style={wrap}>
        <VTitle>{arch.title}</VTitle>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          {arch.comps.slice(0, 8).map((c, i) => (
            <React.Fragment key={c.id}>
              <div style={{ ...node, width: '100%', maxWidth: 360, padding: '10px 14px', fontWeight: 500 }}>{c.label}</div>
              {i < arch.comps.length - 1 && <span style={arrowStyle}>↓</span>}
            </React.Fragment>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={wrap}>
      <VTitle>{arch.title}</VTitle>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {arch.comps.slice(0, 8).map((c) => (
          <div key={c.id} style={{ ...card, padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="t-mono" style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--accent-primary)', color: 'var(--accent-primary)' }}>{ROLE_LABEL[c.role] || c.role.toUpperCase()}</span>
              <span className="t-body" style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{c.label}</span>
            </div>
            {c.connects.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {c.connects.map((cn, j) => (
                  <span key={j} className="t-mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                    → {labelOf(cn.to)}{cn.label ? ` (${cn.label})` : ''}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Fallback({ tid }: { tid: string }) {
  return (
    <div style={wrap}>
      <div style={{ ...card, borderStyle: 'dashed', textAlign: 'center' }}>
        <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 4 }}>Visual</div>
        <div className="t-mono" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{tid.replace(/_/g, ' ').toUpperCase()}</div>
      </div>
    </div>
  );
}
