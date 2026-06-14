import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router";
import {
  ArrowLeft,
  Loader2,
  User,
  Trophy,
  Flame,
  Clock,
  BookOpen,
  Star,
  GraduationCap,
  MessageSquare,
  Brain,
} from "lucide-react";
import { toast } from "sonner";
import api from "../../services/api";

/* ─── Types ─── */
interface StudentDetailData {
  id: number;
  username: string;
  email: string;
  role: string;
  date_joined: string;
  profile: {
    level: number;
    current_xp: number;
    current_streak: number;
    longest_streak: number;
    total_minutes_learned: number;
    daily_goal_minutes: number;
    days_active: number;
    messages_count: number;
  } | null;
  enrollments: {
    id: number;
    course_title: string;
    progress_percentage: number;
    enrolled_at: string;
    is_pathway_ready: boolean;
  }[];
  recent_chats: {
    id: number;
    lesson_title: string;
    transcript_text: string;
    ai_response_text: string;
    predicted_intent: string;
    confidence: number | null;
    created_at: string;
  }[];
  learning_profile: {
    sessions_count: number;
    profile_summary: string;
    last_updated: string;
  } | null;
  achievements_count: number;
}

const TABS = ["Overview", "Enrollments", "Chat History", "Learning Profile"] as const;
type Tab = (typeof TABS)[number];

/* ─── Tab Icons ─── */
const TAB_ICONS: Record<Tab, typeof User> = {
  Overview: User,
  Enrollments: BookOpen,
  "Chat History": MessageSquare,
  "Learning Profile": Brain,
};

export default function StudentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<StudentDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("Overview");

  useEffect(() => {
    if (!id) return;
    api
      .get(`/users/admin-student-detail/${id}/`)
      .then((res) => setData(res.data))
      .catch(() => toast.error("Failed to load student details"))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--admin-accent)" }} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-center py-32" style={{ color: "var(--admin-muted)" }}>
        Student not found.
      </div>
    );
  }

  const profile = data.profile;

  return (
    <div>
      {/* Back */}
      <button
        onClick={() => navigate("/admin/students")}
        className="flex items-center gap-2 mb-6 text-sm font-medium transition-colors"
        style={{ color: "var(--admin-muted)" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "var(--admin-accent)")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "var(--admin-muted)")}
      >
        <ArrowLeft size={16} /> Back to Students
      </button>

      {/* Header Card */}
      <div className="admin-card p-6 mb-8">
        <div className="flex items-center gap-5">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center text-2xl font-black"
            style={{ background: "var(--admin-accent)", color: "var(--admin-ink)" }}
          >
            {data.username.slice(0, 2).toUpperCase()}
          </div>
          <div className="flex-1">
            <h1 className="admin-heading" id="student-detail-title">
              {data.username}
            </h1>
            <p className="admin-subheading">{data.email}</p>
          </div>
          <div className="text-right text-sm" style={{ color: "var(--admin-muted)" }}>
            <p>Joined {new Date(data.date_joined).toLocaleDateString()}</p>
            <p className="font-semibold" style={{ color: "var(--admin-ink)" }}>
              Level {profile?.level ?? 1}
            </p>
          </div>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-6">
          {[
            { label: "XP", value: profile?.current_xp ?? 0, icon: Star, color: "var(--admin-accent)" },
            { label: "Streak", value: `${profile?.current_streak ?? 0}d`, icon: Flame, color: "var(--admin-red, #ff6b35)" },
            { label: "Time Learned", value: `${Math.floor((profile?.total_minutes_learned ?? 0) / 60)}h`, icon: Clock, color: "var(--admin-lime)" },
            { label: "Enrollments", value: data.enrollments.length, icon: GraduationCap, color: "var(--admin-accent)" },
            { label: "Achievements", value: data.achievements_count, icon: Trophy, color: "var(--admin-accent)" },
          ].map((s) => {
            const Icon = s.icon;
            return (
              <div key={s.label} className="flex items-center gap-3 p-3 rounded-xl" style={{ background: "var(--admin-surface)" }}>
                <Icon size={18} style={{ color: s.color }} />
                <div>
                  <p className="text-lg font-bold" style={{ color: "var(--admin-ink)" }}>{s.value}</p>
                  <p className="text-xs" style={{ color: "var(--admin-muted)" }}>{s.label}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 admin-card p-1 w-fit">
        {TABS.map((t) => {
          const Icon = TAB_ICONS[t];
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

      {/* Tab Content */}
      {tab === "Overview" && <OverviewTab data={data} />}
      {tab === "Enrollments" && <EnrollmentsTab enrollments={data.enrollments} />}
      {tab === "Chat History" && <ChatHistoryTab chats={data.recent_chats} />}
      {tab === "Learning Profile" && <LearningProfileTab profile={data.learning_profile} />}
    </div>
  );
}

/* ─── Tab Components ─── */

function OverviewTab({ data }: { data: StudentDetailData }) {
  const p = data.profile;
  if (!p) {
    return (
      <div className="admin-card p-8 text-center" style={{ color: "var(--admin-muted)" }}>
        No profile data available yet.
      </div>
    );
  }

  const stats = [
    { label: "Level", value: p.level },
    { label: "Current XP", value: p.current_xp },
    { label: "Current Streak", value: `${p.current_streak} days` },
    { label: "Longest Streak", value: `${p.longest_streak} days` },
    { label: "Total Time Learned", value: `${Math.floor(p.total_minutes_learned / 60)}h ${p.total_minutes_learned % 60}m` },
    { label: "Daily Goal", value: `${p.daily_goal_minutes} min` },
    { label: "Days Active", value: p.days_active },
    { label: "Messages Sent", value: p.messages_count },
  ];

  return (
    <div className="admin-card p-6">
      <h3 className="font-bold text-lg mb-4" style={{ color: "var(--admin-ink)" }}>
        Profile Details
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s) => (
          <div key={s.label} className="p-4 rounded-xl" style={{ background: "var(--admin-surface)" }}>
            <p className="text-xs mb-1" style={{ color: "var(--admin-muted)" }}>{s.label}</p>
            <p className="text-lg font-bold" style={{ color: "var(--admin-ink)" }}>{s.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function EnrollmentsTab({ enrollments }: { enrollments: StudentDetailData["enrollments"] }) {
  if (enrollments.length === 0) {
    return (
      <div className="admin-card p-8 text-center" style={{ color: "var(--admin-muted)" }}>
        No enrollments yet.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {enrollments.map((e) => (
        <div key={e.id} className="admin-card p-5">
          <div className="flex items-center justify-between mb-3">
            <h4 className="font-bold text-sm" style={{ color: "var(--admin-ink)" }}>
              {e.course_title}
            </h4>
            <span className="text-xs" style={{ color: "var(--admin-muted)" }}>
              {new Date(e.enrolled_at).toLocaleDateString()}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {/* Progress bar */}
            <div className="flex-1 h-2 rounded-full" style={{ background: "var(--admin-surface)" }}>
              <div
                className="h-2 rounded-full transition-all"
                style={{
                  width: `${e.progress_percentage}%`,
                  background: "var(--admin-accent)",
                }}
              />
            </div>
            <span className="text-sm font-semibold" style={{ color: "var(--admin-ink)" }}>
              {e.progress_percentage}%
            </span>
            {e.is_pathway_ready && (
              <span className="admin-badge text-xs" style={{ background: "var(--admin-lime)22", color: "var(--admin-lime)" }}>
                Pathway Ready
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function ChatHistoryTab({ chats }: { chats: StudentDetailData["recent_chats"] }) {
  if (chats.length === 0) {
    return (
      <div className="admin-card p-8 text-center" style={{ color: "var(--admin-muted)" }}>
        No chat history available.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {chats.map((c) => (
        <div key={c.id} className="admin-card p-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold" style={{ color: "var(--admin-accent)" }}>
              {c.lesson_title}
            </span>
            <div className="flex items-center gap-2">
              {c.predicted_intent && (
                <span
                  className="admin-badge text-xs px-2 py-0.5 rounded"
                  style={{ background: "var(--admin-surface)", color: "var(--admin-ink)" }}
                >
                  {c.predicted_intent}
                  {c.confidence !== null && ` (${(c.confidence * 100).toFixed(0)}%)`}
                </span>
              )}
              <span className="text-xs" style={{ color: "var(--admin-muted)" }}>
                {new Date(c.created_at).toLocaleString()}
              </span>
            </div>
          </div>
          <div className="space-y-2 text-sm">
            <div className="p-3 rounded-lg" style={{ background: "var(--admin-surface)" }}>
              <p className="text-xs font-semibold mb-1" style={{ color: "var(--admin-muted)" }}>Student:</p>
              <p style={{ color: "var(--admin-ink)" }}>{c.transcript_text}</p>
            </div>
            <div className="p-3 rounded-lg" style={{ background: "var(--admin-accent)11" }}>
              <p className="text-xs font-semibold mb-1" style={{ color: "var(--admin-accent)" }}>AI Response:</p>
              <p style={{ color: "var(--admin-ink)" }}>{c.ai_response_text.slice(0, 300)}{c.ai_response_text.length > 300 ? "..." : ""}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function LearningProfileTab({ profile }: { profile: StudentDetailData["learning_profile"] }) {
  if (!profile) {
    return (
      <div className="admin-card p-8 text-center" style={{ color: "var(--admin-muted)" }}>
        No learning profile yet. Profile is generated after the first tutoring session.
      </div>
    );
  }

  return (
    <div className="admin-card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-lg" style={{ color: "var(--admin-ink)" }}>
          AI Learning Profile
        </h3>
        <div className="text-xs" style={{ color: "var(--admin-muted)" }}>
          <p>{profile.sessions_count} sessions • Last updated {new Date(profile.last_updated).toLocaleDateString()}</p>
        </div>
      </div>
      <div className="p-5 rounded-xl" style={{ background: "var(--admin-surface)" }}>
        <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--admin-ink)" }}>
          {profile.profile_summary || "Profile summary not available."}
        </p>
      </div>
    </div>
  );
}
