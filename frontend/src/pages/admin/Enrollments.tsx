import { useState, useEffect, useMemo } from "react";
import {
  Search,
  Loader2,
  GraduationCap,
  RefreshCw,
  RotateCcw,
  Route,
  CheckCircle2,
  Clock,
  CalendarDays,
  ArrowUpDown,
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

type SortKey = "student" | "course" | "progress" | "enrolled_at";
type SortDir = "asc" | "desc";

export default function Enrollments() {
  const [enrollments, setEnrollments] = useState<AdminEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "pathway" | "no_pathway">("all");
  const [courseFilter, setCourseFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("enrolled_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
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

  // Unique course titles for filter
  const courseNames = useMemo(() => {
    return [...new Set(enrollments.map((e) => e.course_title))].sort();
  }, [enrollments]);

  const filtered = useMemo(() => {
    return enrollments
      .filter((e) => {
        const matchSearch =
          e.student_username.toLowerCase().includes(search.toLowerCase()) ||
          e.course_title.toLowerCase().includes(search.toLowerCase()) ||
          e.student_email.toLowerCase().includes(search.toLowerCase());
        const matchStatus =
          statusFilter === "all" ||
          (statusFilter === "pathway" && e.is_pathway_ready) ||
          (statusFilter === "no_pathway" && !e.is_pathway_ready);
        const matchCourse =
          courseFilter === "all" || e.course_title === courseFilter;
        const enrollDate = e.enrolled_at ? new Date(e.enrolled_at) : null;
        const matchDateFrom = !dateFrom || (enrollDate && enrollDate >= new Date(dateFrom));
        const matchDateTo = !dateTo || (enrollDate && enrollDate <= new Date(dateTo + "T23:59:59"));
        return matchSearch && matchStatus && matchCourse && matchDateFrom && matchDateTo;
      })
      .sort((a, b) => {
        let cmp = 0;
        switch (sortKey) {
          case "student":
            cmp = a.student_username.localeCompare(b.student_username);
            break;
          case "course":
            cmp = a.course_title.localeCompare(b.course_title);
            break;
          case "progress":
            cmp = a.progress_percentage - b.progress_percentage;
            break;
          case "enrolled_at":
            cmp = new Date(a.enrolled_at).getTime() - new Date(b.enrolled_at).getTime();
            break;
        }
        return sortDir === "asc" ? cmp : -cmp;
      });
  }, [enrollments, search, statusFilter, courseFilter, dateFrom, dateTo, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const handleRegeneratePathway = async (enrollment: AdminEnrollment) => {
    if (
      !confirm(
        `Regenerate pathway for "${enrollment.student_username}" in "${enrollment.course_title}"?\n\nThis will replace the existing pathway.`
      )
    )
      return;

    setRegenerating(enrollment.id);
    try {
      await api.post(`/courses/courses/${enrollment.course_id}/pathway/regenerate/`, {
        student_id: enrollment.id,
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

  const SortHeader = ({ label, sortKeyVal }: { label: string; sortKeyVal: SortKey }) => (
    <th
      className="px-6 py-4 text-left text-xs font-semibold cursor-pointer select-none hover:text-[var(--admin-ink)]"
      style={{ color: "var(--admin-ink-secondary)" }}
      onClick={() => toggleSort(sortKeyVal)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown size={12} className={sortKey === sortKeyVal ? "opacity-100" : "opacity-30"} />
      </span>
    </th>
  );

  if (loading) {
    return (
      <div className="admin-animate-page">
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="admin-skeleton h-10 w-64 mb-2" />
            <div className="admin-skeleton h-5 w-48" />
          </div>
          <div className="admin-skeleton h-10 w-28" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="admin-card p-5 flex items-center gap-4">
              <div className="admin-skeleton w-12 h-12 rounded-xl flex-shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="admin-skeleton h-6 w-16" />
                <div className="admin-skeleton h-4 w-24" />
              </div>
            </div>
          ))}
        </div>
        <div className="admin-card p-4 mb-6">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="admin-skeleton h-10 w-full max-w-md flex-1 min-w-[200px]" />
            <div className="admin-skeleton h-10 w-40" />
            <div className="admin-skeleton h-10 w-48" />
            <div className="admin-skeleton h-10 w-64" />
          </div>
        </div>
        <div className="admin-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Student</th>
                  <th>Course</th>
                  <th>Progress</th>
                  <th>Pathway</th>
                  <th>Enrolled</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    <td><div className="admin-skeleton h-10 w-40" /></td>
                    <td><div className="admin-skeleton h-6 w-32" /></td>
                    <td><div className="admin-skeleton h-4 w-32" /></td>
                    <td><div className="admin-skeleton h-6 w-20" /></td>
                    <td><div className="admin-skeleton h-6 w-24" /></td>
                    <td><div className="admin-skeleton h-8 w-24" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="admin-heading-md" id="enrollments-title">
            Enrollment Management
          </h1>
          <p className="admin-body-lg mt-1">
            {enrollments.length} total enrollments
          </p>
        </div>
        <button
          onClick={fetchEnrollments}
          className="admin-btn admin-btn-ghost flex items-center gap-2"
        >
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          { label: "Total Enrollments", value: enrollments.length, icon: GraduationCap, color: "var(--admin-accent)" },
          { label: "In Progress", value: inProgressCount, icon: Clock, color: "var(--admin-warning)" },
          { label: "Completed", value: completedCount, icon: CheckCircle2, color: "var(--admin-success)" },
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
                <p className="text-xs" style={{ color: "var(--admin-ink-secondary)" }}>{card.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Filters */}
      <div className="admin-card p-4 mb-6">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "var(--admin-ink-tertiary)" }} />
            <input
              type="text"
              placeholder="Search student or course..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="admin-input w-full pl-11"
              id="enrollment-search"
            />
          </div>

          {/* Course filter */}
          <select
            value={courseFilter}
            onChange={(e) => setCourseFilter(e.target.value)}
            className="admin-input admin-select"
          >
            <option value="all">All Courses</option>
            {courseNames.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          {/* Status filter */}
          <div className="flex items-center gap-1 admin-card p-1">
            {(["all", "pathway", "no_pathway"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
                style={{
                  background: statusFilter === f ? "var(--admin-accent)" : "transparent",
                  color: statusFilter === f ? "#fff" : "var(--admin-ink-secondary)",
                }}
              >
                {f === "all" ? "All" : f === "pathway" ? "Has Pathway" : "No Pathway"}
              </button>
            ))}
          </div>

          {/* Date range */}
          <div className="flex items-center gap-2">
            <CalendarDays size={16} style={{ color: "var(--admin-ink-tertiary)" }} />
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="admin-input text-sm py-1.5"
              title="From date"
            />
            <span className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="admin-input text-sm py-1.5"
              title="To date"
            />
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="admin-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="admin-table">
            <thead>
              <tr>
                <SortHeader label="Student" sortKeyVal="student" />
                <SortHeader label="Course" sortKeyVal="course" />
                <SortHeader label="Progress" sortKeyVal="progress" />
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-ink-secondary)" }}>Pathway</th>
                <SortHeader label="Enrolled" sortKeyVal="enrolled_at" />
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-ink-secondary)" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id}>
                  <td>
                    <div>
                      <p className="text-sm font-semibold" style={{ color: "var(--admin-ink)" }}>{e.student_username}</p>
                      <p className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>{e.student_email}</p>
                    </div>
                  </td>
                  <td>
                    <p className="text-sm font-medium" style={{ color: "var(--admin-ink)" }}>{e.course_title}</p>
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-2 rounded-full" style={{ background: "var(--admin-paper-muted)" }}>
                        <div
                          className="h-2 rounded-full transition-all"
                          style={{
                            width: `${Math.min(e.progress_percentage, 100)}%`,
                            background:
                              e.progress_percentage >= 100
                                ? "var(--admin-success)"
                                : "var(--admin-accent)",
                          }}
                        />
                      </div>
                      <span className="text-xs font-mono" style={{ color: "var(--admin-ink)" }}>
                        {Math.round(e.progress_percentage)}%
                      </span>
                    </div>
                  </td>
                  <td>
                    <span
                      className="admin-badge text-xs px-2 py-1 rounded-lg"
                      style={{
                        background: e.is_pathway_ready ? "var(--admin-success)22" : "var(--admin-paper-muted)",
                        color: e.is_pathway_ready ? "var(--admin-success)" : "var(--admin-ink-tertiary)",
                      }}
                    >
                      {e.is_pathway_ready ? "Ready" : "Pending"}
                    </span>
                  </td>
                  <td className="text-xs" style={{ color: "var(--admin-ink-secondary)" }}>
                    {e.enrolled_at ? new Date(e.enrolled_at).toLocaleDateString() : "—"}
                  </td>
                  <td>
                    <button
                      onClick={() => handleRegeneratePathway(e)}
                      disabled={regenerating === e.id}
                      className="admin-btn admin-btn-ghost text-xs px-3 py-1.5 flex items-center gap-1"
                    >
                      {regenerating === e.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <RotateCcw size={12} />
                      )}
                      Regen
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filtered.length === 0 && (
            <div className="py-16 text-center" style={{ color: "var(--admin-ink-tertiary)" }}>
              <GraduationCap size={48} className="mx-auto mb-4 opacity-40" />
              <p>No enrollments found</p>
            </div>
          )}
        </div>
      </div>
      <p className="admin-body-sm mt-3">{filtered.length} of {enrollments.length} enrollments shown</p>
    </div>
  );
}
