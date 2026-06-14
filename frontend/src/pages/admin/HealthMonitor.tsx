import { useState, useEffect, useCallback, useRef } from "react";
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

/* ──────────── Status Helpers ──────────── */

function statusColor(s: string) {
  switch (s) {
    case "healthy":
      return "var(--admin-lime)";
    case "degraded":
      return "var(--admin-accent)";
    default:
      return "var(--admin-red, #ff4444)";
  }
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "healthy":
      return <CheckCircle2 size={20} style={{ color: "var(--admin-lime)" }} />;
    case "degraded":
      return <AlertTriangle size={20} style={{ color: "var(--admin-accent)" }} />;
    default:
      return <XCircle size={20} style={{ color: "var(--admin-red, #ff4444)" }} />;
  }
}

/* ──────────── Component ──────────── */

export default function HealthMonitor() {
  const [services, setServices] = useState<Record<string, ServiceHealth>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);
  const [interval, setInterval_] = useState(15000);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  const fetchAll = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await getAllServicesHealth();
      setServices(data);
      setLastCheck(new Date());
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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <RefreshCw size={32} className="animate-spin" style={{ color: "var(--admin-accent)" }} />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="admin-heading" id="health-monitor-title">
            System Health
          </h1>
          <p className="admin-subheading mt-1">
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
                  color: interval === opt.value ? "var(--admin-ink)" : "var(--admin-muted)",
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
            className="admin-btn admin-btn-secondary flex items-center gap-2"
            id="health-refresh-btn"
          >
            <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary Strip */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {[
          { label: "Healthy",  count: healthyCount,  icon: Wifi,       color: "var(--admin-lime)" },
          { label: "Degraded", count: degradedCount,  icon: AlertTriangle, color: "var(--admin-accent)" },
          { label: "Down",     count: downCount,      icon: WifiOff,    color: "var(--admin-red, #ff4444)" },
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
                <p className="text-xs" style={{ color: "var(--admin-muted)" }}>
                  {s.label}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Last check timestamp */}
      {lastCheck && (
        <div className="flex items-center gap-2 mb-6 text-xs" style={{ color: "var(--admin-muted)" }}>
          <Clock size={14} />
          Last checked: {lastCheck.toLocaleTimeString()}
        </div>
      )}

      {/* Service Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {Object.keys(SERVICE_META).map((key) => {
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
                    style={{ background: "var(--admin-surface)" }}
                  >
                    <Icon size={20} style={{ color: "var(--admin-accent)" }} />
                  </div>
                  <div>
                    <h3 className="font-bold text-sm" style={{ color: "var(--admin-ink)" }}>
                      {meta.label}
                    </h3>
                    <p className="text-xs" style={{ color: "var(--admin-muted)" }}>
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
                      background: "var(--admin-surface)",
                      color: "var(--admin-muted)",
                    }}
                  >
                    Model: {health.model_loaded ? "✓" : "✗"}
                  </span>
                )}
              </div>

              {health.error && (
                <p
                  className="mt-3 text-xs truncate"
                  style={{ color: "var(--admin-red, #ff4444)" }}
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
