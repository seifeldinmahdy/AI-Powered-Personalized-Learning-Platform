import { useState, useEffect, useMemo } from "react";
import {
  Search,
  Loader2,
  GraduationCap,
  RefreshCw,
  RotateCcw,
  Route,
  Filter,
  CheckCircle2,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import api from "../../services/api";

/* ─── Types ─── */
interface AdminEnrollment {
  id: number;
  student_username: string;
  student_email: string;
  course_title: string;
  course_id: number;
  progress_percentage: number;
  enrolled_at: string;
  is_pathway_ready: boolean;
  current_pathway: Record<string, unknown> | null;
}

export default function Enrollments() {
  const [enrollments, setEnrollments] = useState<AdminEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "pathway" | "no_pathway">("all");
  const [regenerating, setRegenerating] = useState<number | null>(null);

  useEffect(() => {
    fetchEnrollments();
  }, []);

  const fetchEnrollments = async () => {
    setLoading(true);
    try {
      const res = await api.get("/courses/enrollments/");
      const data = Array.isArray(res.data) ? res.data : res.data.results ?? [];
      const mapped = data.map((e: Record<string, unknown>) => ({
        id: e.id as number,
        student_username: (e.student_username || (e.student as Record<string, unknown>)?.username || "—") as string,
        student_email: (e.student_email || (e.student as Record<string, unknown>)?.email || "") as string,
        course_title: (e.course_title || (e.course as Record<string, unknown>)?.title || "—") as string,
        course_id: (e.course_id || (e.course as Record<string, unknown>)?.id || 0) as number,
        progress_percentage: (e.progress_percentage || 0) as number,
        enrolled_at: (e.enrolled_at || "") as string,
        is_pathway_ready: (e.is_pathway_ready || false) as boolean,
        current_pathway: (e.current_pathway || null) as Record<string, unknown> | null,
      }));
      setEnrollments(mapped);
    } catch {
      toast.error("Failed to load enrollments");
    } finally {
      setLoading(false);
    }
  };

  const filtered = useMemo(() => {
    return enrollments.filter((e) => {
      const matchSearch =
        e.student_username.toLowerCase().includes(search.toLowerCase()) ||
        e.course_title.toLowerCase().includes(search.toLowerCase()) ||
        e.student_email.toLowerCase().includes(search.toLowerCase());
      const matchStatus =
        statusFilter === "all" ||
        (statusFilter === "pathway" && e.is_pathway_ready) ||
        (statusFilter === "no_pathway" && !e.is_pathway_ready);
      return matchSearch && matchStatus;
    });
  }, [enrollments, search, statusFilter]);

  const handleRegeneratePathway = async (enrollment: AdminEnrollment) => {
    if (
      !confirm(
        `Regenerate pathway for "${enrollment.student_username}" in "${enrollment.course_title}"?\n\nThis will replace the existing pathway.`
      )
    )
      return;

    setRegenerating(enrollment.id);
    try {
      // Call the AI service pathway generation through Django
      await api.post(`/courses/enrollments/${enrollment.id}/save_pathway/`, {
        pathway: {},
        slides: [],
        regenerate: true,
      });
      toast.success("Pathway regeneration triggered");
      fetchEnrollments();
    } catch {
      toast.error("Failed to regenerate pathway");
    } finally {
      setRegenerating(null);
    }
  };

  const completedCount = enrollments.filter((e) => e.progress_percentage >= 100).length;
  const inProgressCount = enrollments.filter((e) => e.progress_percentage > 0 && e.progress_percentage < 100).length;
  const avgProgress =
    enrollments.length > 0
      ? Math.round(enrollments.reduce((s, e) => s + e.progress_percentage, 0) / enrollments.length)
      : 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--admin-accent)" }} />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="admin-heading" id="enrollments-title">
            Enrollment Management
          </h1>
          <p className="admin-subheading mt-1">
            {enrollments.length} total enrollments
          </p>
        </div>
        <button
          onClick={fetchEnrollments}
          className="admin-btn admin-btn-secondary flex items-center gap-2"
        >
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          { label: "Total Enrollments", value: enrollments.length, icon: GraduationCap, color: "var(--admin-accent)" },
          { label: "In Progress", value: inProgressCount, icon: Clock, color: "var(--admin-accent)" },
          { label: "Completed", value: completedCount, icon: CheckCircle2, color: "var(--admin-lime)" },
          { label: "Avg. Progress", value: `${avgProgress}%`, icon: Route, color: "var(--admin-accent)" },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="admin-card flex items-center gap-4 p-5">
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center"
                style={{ background: `${card.color}22` }}
              >
                <Icon size={22} style={{ color: card.color }} />
              </div>
              <div>
                <p className="text-2xl font-bold" style={{ color: "var(--admin-ink)" }}>{card.value}</p>
                <p className="text-xs" style={{ color: "var(--admin-muted)" }}>{card.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <div className="relative flex-1 max-w-md">
          <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2" style={{ color: "var(--admin-muted)" }} />
          <input
            type="text"
            placeholder="Search by student or course..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="admin-input w-full pl-11"
            id="enrollment-search"
          />
        </div>
        <div className="flex items-center gap-1 admin-card p-1">
          <Filter size={14} style={{ color: "var(--admin-muted)" }} className="ml-2" />
          {(["all", "pathway", "no_pathway"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={{
                background: statusFilter === f ? "var(--admin-accent)" : "transparent",
                color: statusFilter === f ? "var(--admin-ink)" : "var(--admin-muted)",
              }}
            >
              {f === "all" ? "All" : f === "pathway" ? "Has Pathway" : "No Pathway"}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="admin-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: "2px solid var(--admin-border)" }}>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Student</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Course</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Progress</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Pathway</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Enrolled</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr
                  key={e.id}
                  className="transition-colors"
                  style={{ borderBottom: "1px solid var(--admin-border)" }}
                  onMouseEnter={(ev) => (ev.currentTarget.style.background = "var(--admin-surface)")}
                  onMouseLeave={(ev) => (ev.currentTarget.style.background = "transparent")}
                >
                  <td className="px-6 py-4">
                    <div>
                      <p className="text-sm font-semibold" style={{ color: "var(--admin-ink)" }}>{e.student_username}</p>
                      <p className="text-xs" style={{ color: "var(--admin-muted)" }}>{e.student_email}</p>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <p className="text-sm font-medium" style={{ color: "var(--admin-ink)" }}>{e.course_title}</p>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-2 rounded-full" style={{ background: "var(--admin-surface)" }}>
                        <div
                          className="h-2 rounded-full transition-all"
                          style={{
                            width: `${Math.min(e.progress_percentage, 100)}%`,
                            background:
                              e.progress_percentage >= 100
                                ? "var(--admin-lime)"
                                : "var(--admin-accent)",
                          }}
                        />
                      </div>
                      <span className="text-xs font-mono" style={{ color: "var(--admin-ink)" }}>
                        {e.progress_percentage}%
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className="admin-badge text-xs px-2 py-1 rounded-lg"
                      style={{
                        background: e.is_pathway_ready ? "var(--admin-lime)22" : "var(--admin-surface)",
                        color: e.is_pathway_ready ? "var(--admin-lime)" : "var(--admin-muted)",
                      }}
                    >
                      {e.is_pathway_ready ? "Ready" : "Pending"}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-xs" style={{ color: "var(--admin-muted)" }}>
                    {e.enrolled_at ? new Date(e.enrolled_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-6 py-4">
                    <button
                      onClick={() => handleRegeneratePathway(e)}
                      disabled={regenerating === e.id}
                      className="admin-btn admin-btn-secondary text-xs px-3 py-1.5 flex items-center gap-1"
                    >
                      {regenerating === e.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <RotateCcw size={12} />
                      )}
                      Regen Pathway
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filtered.length === 0 && (
            <div className="py-16 text-center" style={{ color: "var(--admin-muted)" }}>
              <GraduationCap size={48} className="mx-auto mb-4 opacity-40" />
              <p>No enrollments found</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
