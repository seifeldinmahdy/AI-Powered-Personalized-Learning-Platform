import { useState, useEffect, useCallback, useRef } from "react";
import type { MouseEvent } from "react";
import {
  Activity,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Wifi,
  WifiOff,
  Clock,
  Brain,
  MessageSquare,
  BookOpen,
  Presentation,
  Mic,
  Volume2,
  Eye,
  AudioLines,
  Route,
  ClipboardList,
  MonitorSpeaker,
} from "lucide-react";
import {
  getAllServicesHealth,
  type ServiceHealth,
} from "../../services/admin";

/* ──────────── Service Metadata ──────────── */

interface ServiceMeta {
  label: string;
  description: string;
  icon: typeof Activity;
}

const SERVICE_META: Record<string, ServiceMeta> = {
  intent:      { label: "Intent Classifier",     description: "TinyBERT intent classification",      icon: Brain },
  tutor:       { label: "AI Tutor",              description: "Conversational tutoring engine",       icon: MessageSquare },
  rag:         { label: "RAG / QA",              description: "Retrieval-augmented Q&A",              icon: BookOpen },
  slides:      { label: "Slide Generator",       description: "PDF → slide deck pipeline",            icon: Presentation },
  asr:         { label: "Speech-to-Text",        description: "Whisper ASR transcription",            icon: Mic },
  tts:         { label: "Text-to-Speech",        description: "Edge-TTS voice synthesis",             icon: Volume2 },
  fer:         { label: "Facial Emotion",        description: "CNN facial emotion recognition",       icon: Eye },
  ser:         { label: "Speech Emotion",        description: "Speech emotion recognition",           icon: AudioLines },
  pathway:     { label: "Course Pathway",        description: "Personalized session-plan generator",  icon: Route },
  assessments: { label: "MCQ Assessments",       description: "MCQ generation & scoring",             icon: ClipboardList },
  a2f:         { label: "Audio2Face",            description: "NVIDIA A2F gRPC bridge",               icon: MonitorSpeaker },
};

const INTERVAL_OPTIONS = [
  { label: "5s",  value: 5000 },
  { label: "15s", value: 15000 },
  { label: "30s", value: 30000 },
  { label: "Off", value: 0 },
];

const MAX_HISTORY = 30; // max data points on timeline

/* ──────────── Status Helpers ──────────── */

function statusColor(s: string) {
  switch (s) {
    case "healthy":
      return "var(--admin-success)";
    case "degraded":
      return "var(--admin-warning)";
    default:
      return "var(--admin-error)";
  }
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "healthy":
      return <CheckCircle2 size={20} style={{ color: "var(--admin-success)" }} />;
    case "degraded":
      return <AlertTriangle size={20} style={{ color: "var(--admin-warning)" }} />;
    default:
      return <XCircle size={20} style={{ color: "var(--admin-error)" }} />;
  }
}

/* ──────────── Health Timeline Chart (SVG) ──────────── */

interface HealthSnapshot {
  time: string;
  healthy: number;
  degraded: number;
  down: number;
  total: number;
}

function HealthTimelineChart({ history }: { history: HealthSnapshot[] }) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; data: HealthSnapshot } | null>(null);

  if (history.length < 2) {
    return (
      <div className="admin-card p-6 mb-8">
        <h3 className="admin-heading-xs mb-2 flex items-center gap-2">
          <Activity size={18} style={{ color: "var(--admin-accent)" }} />
          Health Over Time
        </h3>
        <p className="admin-body-sm">Collecting data… (first points will appear after two checks)</p>
      </div>
    );
  }

  const W = 800;
  const H = 160;
  const padL = 40;
  const padR = 16;
  const padT = 16;
  const padB = 32;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const maxVal = Math.max(1, ...history.map((h) => h.total));
  const xStep = innerW / (history.length - 1);

  const line = (key: keyof HealthSnapshot, color: string) => {
    const points = history.map((h, i) => {
      const x = padL + i * xStep;
      const y = padT + innerH - ((h[key] as number) / maxVal) * innerH;
      return `${x},${y}`;
    });
    return (
      <polyline
        key={key}
        points={points.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    );
  };

  // Area fill for healthy
  const healthyPoints = history.map((h, i) => {
    const x = padL + i * xStep;
    const y = padT + innerH - (h.healthy / maxVal) * innerH;
    return `${x},${y}`;
  });
  const areaPath = `M${healthyPoints[0]} ${healthyPoints.join(" L")} L${padL + (history.length - 1) * xStep},${padT + innerH} L${padL},${padT + innerH} Z`;

  const handleMove = (e: MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const svgX = ((e.clientX - rect.left) / rect.width) * W;
    let index = Math.round((svgX - padL) / xStep);
    index = Math.max(0, Math.min(history.length - 1, index));
    const point = history[index];
    if (!point) return;
    setTooltip({
      x: e.clientX - rect.left + 12,
      y: e.clientY - rect.top - 12,
      data: point,
    });
  };

  return (
    <div className="admin-card p-6 mb-8 relative">
      <h3 className="admin-heading-xs mb-4 flex items-center gap-2">
        <Activity size={18} style={{ color: "var(--admin-accent)" }} />
        Health Over Time
      </h3>
      <div className="flex items-center gap-6 mb-3 text-xs" style={{ color: "var(--admin-ink-secondary)" }}>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-[3px] rounded" style={{ background: "var(--admin-success)" }} /> Healthy
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-[3px] rounded" style={{ background: "var(--admin-warning)" }} /> Degraded
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-[3px] rounded" style={{ background: "var(--admin-error)" }} /> Down
        </span>
      </div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          preserveAspectRatio="none"
          style={{ height: 160 }}
          onMouseMove={handleMove}
          onMouseLeave={() => setTooltip(null)}
        >
          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <line
              key={f}
              x1={padL}
              x2={W - padR}
              y1={padT + innerH * (1 - f)}
              y2={padT + innerH * (1 - f)}
              stroke="var(--admin-hairline-light)"
              strokeWidth="1"
            />
          ))}
          {/* Y labels */}
          {[0, 0.5, 1].map((f) => (
            <text
              key={f}
              x={padL - 6}
              y={padT + innerH * (1 - f) + 4}
              textAnchor="end"
              fill="var(--admin-ink-tertiary)"
              fontSize="10"
              fontFamily="var(--admin-font-body)"
            >
              {Math.round(maxVal * f)}
            </text>
          ))}
          {/* Healthy area */}
          <path d={areaPath} fill="var(--admin-success)" opacity="0.08" />
          {/* Lines */}
          {line("healthy", "var(--admin-success)")}
          {line("degraded", "var(--admin-warning)")}
          {line("down", "var(--admin-error)")}
          {/* Time labels (first, middle, last) */}
          {[0, Math.floor(history.length / 2), history.length - 1].map((i) => (
            <text
              key={i}
              x={padL + i * xStep}
              y={H - 6}
              textAnchor="middle"
              fill="var(--admin-ink-tertiary)"
              fontSize="10"
              fontFamily="var(--admin-font-body)"
            >
              {history[i]?.time}
            </text>
          ))}
        </svg>
        {tooltip && (
          <div
            className="absolute z-10 px-3 py-2 rounded-lg text-xs shadow-lg pointer-events-none"
            style={{
              left: tooltip.x,
              top: tooltip.y,
              background: "var(--admin-paper-dark)",
              color: "var(--admin-ink-inverse)",
              transform: "translateY(-100%)",
            }}
          >
            <div className="font-semibold mb-1">{tooltip.data.time}</div>
            <div className="flex items-center gap-3">
              <span style={{ color: "var(--admin-success)" }}>● {tooltip.data.healthy}</span>
              <span style={{ color: "var(--admin-warning)" }}>● {tooltip.data.degraded}</span>
              <span style={{ color: "var(--admin-error)" }}>● {tooltip.data.down}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ──────────── Component ──────────── */

export default function HealthMonitor() {
  const [services, setServices] = useState<Record<string, ServiceHealth>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);
  const [interval, setInterval_] = useState(15000);
  const [history, setHistory] = useState<HealthSnapshot[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const fetchAll = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await getAllServicesHealth();
      setServices(data);
      setLastCheck(new Date());

      // Record to history
      const entries = Object.values(data);
      const snapshot: HealthSnapshot = {
        time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        healthy: entries.filter((v) => v.status === "healthy").length,
        degraded: entries.filter((v) => v.status === "degraded").length,
        down: entries.filter((v) => v.status !== "healthy" && v.status !== "degraded").length,
        total: entries.length,
      };
      setHistory((prev) => [...prev.slice(-(MAX_HISTORY - 1)), snapshot]);
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, []);

  // Initial fetch + interval
  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    clearInterval(timerRef.current);
    if (interval > 0) {
      timerRef.current = setInterval(fetchAll, interval);
    }
    return () => clearInterval(timerRef.current);
  }, [interval, fetchAll]);

  /* ──────────── Summary Counts ──────────── */
  const entries = Object.entries(services);
  const healthyCount = entries.filter(([, v]) => v.status === "healthy").length;
  const degradedCount = entries.filter(([, v]) => v.status === "degraded").length;
  const downCount = entries.filter(([, v]) => v.status !== "healthy" && v.status !== "degraded").length;

  return (
    <div className="admin-animate-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="admin-heading-md" id="health-monitor-title">
            System Health
          </h1>
          <p className="admin-body-lg mt-1">
            Real-time status of all AI microservices
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Interval selector */}
          <div className="admin-card flex items-center gap-1 p-1">
            {INTERVAL_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setInterval_(opt.value)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
                style={{
                  background: interval === opt.value ? "var(--admin-accent)" : "transparent",
                  color: interval === opt.value ? "#fff" : "var(--admin-ink-secondary)",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* Refresh button */}
          <button
            onClick={fetchAll}
            disabled={refreshing}
            className="admin-btn admin-btn-ghost flex items-center gap-2"
            id="health-refresh-btn"
          >
            <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Health over time chart */}
      {loading ? (
        <div className="admin-card p-6 mb-8">
          <div className="admin-skeleton h-7 w-48 mb-4" />
          <div className="admin-skeleton h-4 w-full mb-2" />
          <div className="admin-skeleton h-40 w-full" />
        </div>
      ) : (
        <HealthTimelineChart history={history} />
      )}

      {/* Summary Strip */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {loading
          ? Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="admin-card flex items-center gap-4 p-5">
                <div className="admin-skeleton w-12 h-12 rounded-xl flex-shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="admin-skeleton h-7 w-12" />
                  <div className="admin-skeleton h-4 w-20" />
                </div>
              </div>
            ))
          : [
              { label: "Healthy",  count: healthyCount,  icon: Wifi,       color: "var(--admin-success)" },
              { label: "Degraded", count: degradedCount,  icon: AlertTriangle, color: "var(--admin-warning)" },
              { label: "Down",     count: downCount,      icon: WifiOff,    color: "var(--admin-error)" },
            ].map((s) => {
              const Icon = s.icon;
              return (
                <div key={s.label} className="admin-card flex items-center gap-4 p-5">
                  <div
                    className="w-12 h-12 rounded-xl flex items-center justify-center"
                    style={{ background: `${s.color}22` }}
                  >
                    <Icon size={22} style={{ color: s.color }} />
                  </div>
                  <div>
                    <p className="text-2xl font-bold" style={{ color: "var(--admin-ink)" }}>
                      {s.count}
                    </p>
                    <p className="text-xs" style={{ color: "var(--admin-ink-secondary)" }}>
                      {s.label}
                    </p>
                  </div>
                </div>
              );
            })}
      </div>

      {/* Last check timestamp */}
      {lastCheck && (
        <div className="flex items-center gap-2 mb-6 text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>
          <Clock size={14} />
          Last checked: {lastCheck.toLocaleTimeString()}
        </div>
      )}

      {/* Service Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {loading
          ? Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="admin-card p-5">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="admin-skeleton w-10 h-10 rounded-lg" />
                    <div className="space-y-2">
                      <div className="admin-skeleton h-4 w-32" />
                      <div className="admin-skeleton h-3 w-40" />
                    </div>
                  </div>
                  <div className="admin-skeleton w-5 h-5 rounded-full" />
                </div>
                <div className="admin-skeleton h-6 w-24" />
              </div>
            ))
          : Object.keys(SERVICE_META).map((key) => {
          const meta = SERVICE_META[key];
          const health = services[key] || { status: "unknown" };
          const Icon = meta.icon;
          return (
            <div
              key={key}
              className="admin-card p-5 transition-all hover:translate-y-[-2px]"
              style={{
                borderLeft: `3px solid ${statusColor(health.status)}`,
              }}
              id={`health-card-${key}`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{ background: "var(--admin-paper-muted)" }}
                  >
                    <Icon size={20} style={{ color: "var(--admin-accent)" }} />
                  </div>
                  <div>
                    <h3 className="font-bold text-sm" style={{ color: "var(--admin-ink)" }}>
                      {meta.label}
                    </h3>
                    <p className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>
                      {meta.description}
                    </p>
                  </div>
                </div>
                <StatusIcon status={health.status} />
              </div>

              <div className="flex items-center gap-2">
                <span
                  className="admin-badge text-xs font-semibold px-2.5 py-1 rounded-lg"
                  style={{
                    background: `${statusColor(health.status)}22`,
                    color: statusColor(health.status),
                  }}
                >
                  {health.status.toUpperCase()}
                </span>
                {health.model_loaded !== undefined && (
                  <span
                    className="text-xs px-2 py-1 rounded-lg"
                    style={{
                      background: "var(--admin-paper-muted)",
                      color: "var(--admin-ink-secondary)",
                    }}
                  >
                    Model: {health.model_loaded ? "✓" : "✗"}
                  </span>
                )}
              </div>

              {health.error && (
                <p
                  className="mt-3 text-xs truncate"
                  style={{ color: "var(--admin-error)" }}
                  title={health.error}
                >
                  {health.error}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
