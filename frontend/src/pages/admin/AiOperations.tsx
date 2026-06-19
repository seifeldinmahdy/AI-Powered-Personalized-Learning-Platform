import { useState, useEffect, useCallback } from "react";
import {
  Brain,
  RefreshCw,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Tag,
  ThumbsUp,
  ThumbsDown,
  Play,
  Settings,
  BarChart3,
  MessageSquare,
} from "lucide-react";
import { toast } from "sonner";
import api from "../../services/api";
import {
  getIntentFeedbackBuffer,
  getRetrainingCounter,
  relabelFeedback,
  updateThreshold,
  type IntentFeedbackEntry,
  type RetrainingCounter,
} from "../../services/admin";
import { INTENT_LABELS } from "../../lib/intents";

/* ─── Tabs ─── */
const TABS = ["Feedback Queue", "Retraining"] as const;
type Tab = (typeof TABS)[number];

export default function AiOperations() {
  const [tab, setTab] = useState<Tab>("Feedback Queue");

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="admin-heading" id="ai-operations-title">
          AI Operations
        </h1>
        <p className="admin-subheading mt-1">
          Intent classifier feedback queue and model retraining
        </p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 admin-card p-1 w-fit">
        {TABS.map((t) => {
          const Icon = t === "Feedback Queue" ? MessageSquare : Brain;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all"
              style={{
                background: tab === t ? "var(--admin-accent)" : "transparent",
                color: tab === t ? "var(--admin-ink)" : "var(--admin-muted)",
              }}
            >
              <Icon size={16} />
              {t}
            </button>
          );
        })}
      </div>

      {tab === "Feedback Queue" && <FeedbackQueueTab />}
      {tab === "Retraining" && <RetrainingTab />}
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   Feedback Queue Tab
   ══════════════════════════════════════════════════════ */

function FeedbackQueueTab() {
  const [entries, setEntries] = useState<IntentFeedbackEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "pending" | "relabelled">("all");
  const [relabeling, setRelabeling] = useState<number | null>(null);
  const [editIntent, setEditIntent] = useState<{ id: number; value: string } | null>(null);

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getIntentFeedbackBuffer();
      setEntries(data);
    } catch {
      toast.error("Failed to load feedback buffer");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const filtered = entries.filter(
    (e) => filter === "all" || e.status === filter
  );

  const handleRelabel = async (id: number, newIntent: string) => {
    setRelabeling(id);
    try {
      await relabelFeedback(id, newIntent);
      toast.success("Entry relabelled");
      setEditIntent(null);
      fetchEntries();
    } catch {
      toast.error("Failed to relabel");
    } finally {
      setRelabeling(null);
    }
  };

  const pendingCount = entries.filter((e) => e.status === "pending").length;
  const relabelledCount = entries.filter((e) => e.status === "relabelled").length;
  const thumbsUpCount = entries.filter((e) => e.feedback === "thumbs_up").length;
  const thumbsDownCount = entries.filter((e) => e.feedback === "thumbs_down").length;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--admin-accent)" }} />
      </div>
    );
  }

  return (
    <div>
      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[
          { label: "Total", value: entries.length, icon: BarChart3, color: "var(--admin-accent)" },
          { label: "Pending", value: pendingCount, icon: Clock, color: "var(--admin-accent)" },
          { label: "Thumbs Up", value: thumbsUpCount, icon: ThumbsUp, color: "var(--admin-lime)" },
          { label: "Thumbs Down", value: thumbsDownCount, icon: ThumbsDown, color: "var(--admin-red, #ff4444)" },
        ].map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="admin-card flex items-center gap-4 p-4">
              <Icon size={20} style={{ color: s.color }} />
              <div>
                <p className="text-xl font-bold" style={{ color: "var(--admin-ink)" }}>{s.value}</p>
                <p className="text-xs" style={{ color: "var(--admin-muted)" }}>{s.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Filter + Refresh */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-1 admin-card p-1">
          {(["all", "pending", "relabelled"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={{
                background: filter === f ? "var(--admin-accent)" : "transparent",
                color: filter === f ? "var(--admin-ink)" : "var(--admin-muted)",
              }}
            >
              {f === "all" ? "All" : f === "pending" ? `Pending (${pendingCount})` : `Relabelled (${relabelledCount})`}
            </button>
          ))}
        </div>
        <button onClick={fetchEntries} className="admin-btn admin-btn-secondary flex items-center gap-2">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Entry List */}
      <div className="space-y-3">
        {filtered.map((entry) => (
          <div key={entry.id} className="admin-card p-5">
            <div className="flex items-start justify-between mb-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm" style={{ color: "var(--admin-ink)" }}>
                  "{entry.student_input}"
                </p>
                {entry.session_context && (
                  <p className="text-xs mt-1 truncate" style={{ color: "var(--admin-muted)" }} title={entry.session_context}>
                    Context: {entry.session_context.slice(0, 100)}...
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                {entry.feedback === "thumbs_up" ? (
                  <ThumbsUp size={16} style={{ color: "var(--admin-lime)" }} />
                ) : (
                  <ThumbsDown size={16} style={{ color: "var(--admin-red, #ff4444)" }} />
                )}
                <span className="text-xs" style={{ color: "var(--admin-muted)" }}>
                  {new Date(entry.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              {/* Predicted intent */}
              <div className="flex items-center gap-1.5">
                <Tag size={12} style={{ color: "var(--admin-muted)" }} />
                <span
                  className="admin-badge text-xs px-2 py-0.5 rounded"
                  style={{ background: "var(--admin-surface)", color: "var(--admin-ink)" }}
                >
                  {entry.predicted_intent}
                </span>
                {entry.confidence !== null && (
                  <span className="text-xs font-mono" style={{ color: "var(--admin-muted)" }}>
                    {(entry.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>

              {/* Corrected intent */}
              {entry.corrected_intent && (
                <div className="flex items-center gap-1.5">
                  <span className="text-xs" style={{ color: "var(--admin-muted)" }}>→</span>
                  <span
                    className="admin-badge text-xs px-2 py-0.5 rounded"
                    style={{ background: "var(--admin-lime)22", color: "var(--admin-lime)" }}
                  >
                    {entry.corrected_intent}
                  </span>
                </div>
              )}

              {/* Status badge */}
              <span
                className="admin-badge text-xs px-2 py-0.5 rounded"
                style={{
                  background: entry.status === "pending" ? "var(--admin-accent)22" : "var(--admin-lime)22",
                  color: entry.status === "pending" ? "var(--admin-accent)" : "var(--admin-lime)",
                }}
              >
                {entry.status}
              </span>

              {/* Relabel button (only for thumbs_down without correction) */}
              {entry.feedback === "thumbs_down" && !entry.corrected_intent && (
                <>
                  {editIntent?.id === entry.id ? (
                    <div className="flex items-center gap-2">
                      <select
                        value={editIntent.value}
                        onChange={(e) => setEditIntent({ id: entry.id, value: e.target.value })}
                        className="admin-input text-xs py-1 px-2"
                      >
                        <option value="">Select intent...</option>
                        {INTENT_LABELS.filter((l) => l !== entry.predicted_intent).map((l) => (
                          <option key={l} value={l}>{l}</option>
                        ))}
                      </select>
                      <button
                        onClick={() => editIntent.value && handleRelabel(entry.id, editIntent.value)}
                        disabled={!editIntent.value || relabeling === entry.id}
                        className="admin-btn admin-btn-primary text-xs px-2 py-1"
                      >
                        {relabeling === entry.id ? <Loader2 size={12} className="animate-spin" /> : "Save"}
                      </button>
                      <button
                        onClick={() => setEditIntent(null)}
                        className="admin-btn admin-btn-secondary text-xs px-2 py-1"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setEditIntent({ id: entry.id, value: "" })}
                      className="admin-btn admin-btn-secondary text-xs px-2 py-1 flex items-center gap-1"
                    >
                      <Tag size={12} /> Relabel
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="admin-card py-16 text-center" style={{ color: "var(--admin-muted)" }}>
            <CheckCircle2 size={48} className="mx-auto mb-4 opacity-40" />
            <p>No feedback entries in this category</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   Retraining Tab
   ══════════════════════════════════════════════════════ */

function RetrainingTab() {
  const [counter, setCounter] = useState<RetrainingCounter | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [editThreshold, setEditThreshold] = useState(false);
  const [newThreshold, setNewThreshold] = useState("");

  const fetchCounter = useCallback(async () => {
    try {
      const data = await getRetrainingCounter();
      setCounter(data);
      setNewThreshold(String(data.threshold));
    } catch {
      toast.error("Failed to load retraining counter");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCounter();
  }, [fetchCounter]);

  const handleTriggerRetraining = async () => {
    if (
      !confirm(
        "Are you sure you want to trigger intent model retraining?\n\nThis will export feedback data and retrain the model. The process may take several minutes."
      )
    )
      return;

    setTriggering(true);
    try {
      await api.post("/progress/trigger-retraining/");
      toast.success("Retraining triggered successfully");
      fetchCounter();
    } catch {
      toast.error("Failed to trigger retraining");
    } finally {
      setTriggering(false);
    }
  };

  const handleUpdateThreshold = async () => {
    const val = parseInt(newThreshold);
    if (isNaN(val) || val < 1) {
      toast.error("Threshold must be a positive number");
      return;
    }
    try {
      const updated = await updateThreshold(val);
      setCounter(updated);
      setEditThreshold(false);
      toast.success("Threshold updated");
    } catch {
      toast.error("Failed to update threshold");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--admin-accent)" }} />
      </div>
    );
  }

  if (!counter) {
    return (
      <div className="admin-card p-8 text-center" style={{ color: "var(--admin-muted)" }}>
        Failed to load retraining data.
      </div>
    );
  }

  const progress = Math.min(
    (counter.reviews_since_last_train / counter.threshold) * 100,
    100
  );
  const thresholdReached = counter.reviews_since_last_train >= counter.threshold;

  return (
    <div className="max-w-2xl space-y-6">
      {/* Counter Card */}
      <div className="admin-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-lg" style={{ color: "var(--admin-ink)" }}>
            Retraining Counter
          </h3>
          <button onClick={fetchCounter} className="admin-btn admin-btn-secondary text-xs flex items-center gap-1">
            <RefreshCw size={12} /> Refresh
          </button>
        </div>

        {/* Progress Bar */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold" style={{ color: "var(--admin-ink)" }}>
              {counter.reviews_since_last_train} / {counter.threshold} reviews
            </span>
            <span className="text-xs" style={{ color: thresholdReached ? "var(--admin-lime)" : "var(--admin-muted)" }}>
              {thresholdReached ? "Threshold Reached!" : `${Math.round(progress)}%`}
            </span>
          </div>
          <div className="h-3 rounded-full" style={{ background: "var(--admin-surface)" }}>
            <div
              className="h-3 rounded-full transition-all"
              style={{
                width: `${progress}%`,
                background: thresholdReached ? "var(--admin-lime)" : "var(--admin-accent)",
              }}
            />
          </div>
        </div>

        {/* Last Trained */}
        <div className="flex items-center gap-2 text-xs" style={{ color: "var(--admin-muted)" }}>
          <Clock size={14} />
          Last trained:{" "}
          {counter.last_trained_at
            ? new Date(counter.last_trained_at).toLocaleString()
            : "Never"}
        </div>
      </div>

      {/* Threshold Config */}
      <div className="admin-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold" style={{ color: "var(--admin-ink)" }}>
            Threshold Configuration
          </h3>
          <Settings size={16} style={{ color: "var(--admin-muted)" }} />
        </div>

        {editThreshold ? (
          <div className="flex items-center gap-3">
            <input
              type="number"
              value={newThreshold}
              onChange={(e) => setNewThreshold(e.target.value)}
              className="admin-input w-32"
              min="1"
            />
            <button onClick={handleUpdateThreshold} className="admin-btn admin-btn-primary text-sm">
              Save
            </button>
            <button onClick={() => setEditThreshold(false)} className="admin-btn admin-btn-secondary text-sm">
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm" style={{ color: "var(--admin-ink)" }}>
                Retraining triggers after{" "}
                <span className="font-bold">{counter.threshold}</span> new feedback reviews
              </p>
            </div>
            <button
              onClick={() => setEditThreshold(true)}
              className="admin-btn admin-btn-secondary text-xs"
            >
              Edit
            </button>
          </div>
        )}
      </div>

      {/* Trigger Retraining */}
      <div className="admin-card p-6">
        <div className="flex items-center gap-3 mb-4">
          <AlertTriangle size={20} style={{ color: "var(--admin-accent)" }} />
          <h3 className="font-bold" style={{ color: "var(--admin-ink)" }}>
            Manual Retraining
          </h3>
        </div>
        <p className="text-sm mb-4" style={{ color: "var(--admin-muted)" }}>
          Manually trigger intent model retraining. This exports all pending feedback
          data and starts a retraining run. The process may take several minutes.
        </p>
        <button
          onClick={handleTriggerRetraining}
          disabled={triggering}
          className="admin-btn admin-btn-primary flex items-center gap-2"
          id="trigger-retraining-btn"
        >
          {triggering ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Play size={16} />
          )}
          {triggering ? "Retraining in Progress..." : "Trigger Retraining"}
        </button>
      </div>
    </div>
  );
}
