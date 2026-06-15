import { useState, useEffect, useMemo } from "react";
import {
  Search,
  Loader2,
  BookOpen,
  Edit2,
  Eye,
  Trash2,
  BarChart3,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { useNavigate } from "react-router";
import {
  getAdminCourses,
  deleteCourse,
  type AdminCourse,
} from "../../services/admin";

export default function ContentManagement() {
  const navigate = useNavigate();
  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [difficultyFilter, setDifficultyFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [deleting, setDeleting] = useState<number | null>(null);

  useEffect(() => {
    getAdminCourses()
      .then(setCourses)
      .catch(() => toast.error("Failed to load courses"))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    return courses.filter((c) => {
      const matchSearch =
        c.title.toLowerCase().includes(search.toLowerCase()) ||
        c.description?.toLowerCase().includes(search.toLowerCase());
      const matchDifficulty =
        difficultyFilter === "all" ||
        c.difficulty?.toLowerCase() === difficultyFilter;
      const matchStatus =
        statusFilter === "all" ||
        c.status?.toLowerCase() === statusFilter;
      return matchSearch && matchDifficulty && matchStatus;
    });
  }, [courses, search, difficultyFilter, statusFilter]);

  const handleDelete = async (id: number) => {
    if (!confirm("Are you sure you want to delete this course? This cannot be undone.")) return;
    setDeleting(id);
    try {
      await deleteCourse(id);
      setCourses((prev) => prev.filter((c) => c.id !== id));
      toast.success("Course deleted");
    } catch (err: any) {
      const message = err?.response?.data?.detail || err?.response?.data?.error || err?.message || "Failed to delete course";
      toast.error(message);
    } finally {
      setDeleting(null);
    }
  };

  const difficulties = [...new Set(courses.map((c) => c.difficulty?.toLowerCase()).filter(Boolean))];
  const statuses = [...new Set(courses.map((c) => c.status?.toLowerCase()).filter(Boolean))];

  // Compute avg rating safely - default to 0 when no valid ratings
  const avgRating = useMemo(() => {
    const ratings = courses
      .map((c) => Number(c.avg_rating))
      .filter((r) => Number.isFinite(r) && r > 0);
    if (ratings.length === 0) return "0.0";
    return (ratings.reduce((s, r) => s + r, 0) / ratings.length).toFixed(1);
  }, [courses]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="admin-loading-spinner" />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="admin-heading" id="content-management-title">
          Content Management
        </h1>
        <p className="admin-subheading mt-1">
          {courses.length} courses • {filtered.length} shown
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          { label: "Total Courses", value: courses.length, icon: BookOpen, color: "var(--admin-accent)" },
          {
            label: "Published",
            value: courses.filter((c) => c.status?.toLowerCase() === "published").length,
            icon: Eye, color: "var(--admin-success)",
          },
          {
            label: "Draft",
            value: courses.filter((c) => c.status?.toLowerCase() === "draft").length,
            icon: Edit2, color: "var(--admin-ink-tertiary)",
          },
          {
            label: "Avg. Rating",
            value: avgRating,
            icon: BarChart3, color: "var(--admin-accent)",
          },
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
                <p className="text-2xl font-bold" style={{ color: "var(--admin-ink)" }}>
                  {card.value}
                </p>
                <p className="text-xs" style={{ color: "var(--admin-ink-secondary)" }}>{card.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <div className="relative flex-1 max-w-md">
          <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "var(--admin-ink-tertiary)" }} />
          <input
            type="text"
            placeholder="Search courses..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="admin-input w-full pl-12"
            id="content-search"
          />
        </div>
        <select
          value={difficultyFilter}
          onChange={(e) => setDifficultyFilter(e.target.value)}
          className="admin-input admin-select"
          id="content-difficulty-filter"
        >
          <option value="all">All Difficulties</option>
          {difficulties.map((d) => (
            <option key={d} value={d}>{d && d.charAt(0).toUpperCase() + d.slice(1)}</option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="admin-input admin-select"
          id="content-status-filter"
        >
          <option value="all">All Statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>{s && s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
      </div>

      {/* Course Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filtered.map((course) => (
          <div key={course.id} className="admin-card p-5 transition-all hover:translate-y-[-2px]">
            <div className="flex items-start justify-between mb-3">
              <div className="flex-1 min-w-0">
                <h3
                  className="font-bold text-sm truncate"
                  style={{ color: "var(--admin-ink)" }}
                  title={course.title}
                >
                  {course.title}
                </h3>
                <p className="text-xs mt-1 line-clamp-2" style={{ color: "var(--admin-ink-secondary)" }}>
                  {course.description || "No description"}
                </p>
              </div>
              <span
                className="admin-badge text-xs px-2 py-1 rounded-lg flex-shrink-0 ml-2"
                style={{
                  background:
                    course.status?.toLowerCase() === "published"
                      ? "var(--admin-success)22"
                      : "var(--admin-paper-muted)",
                  color:
                    course.status?.toLowerCase() === "published"
                      ? "var(--admin-success)"
                      : "var(--admin-ink-tertiary)",
                }}
              >
                {course.status || "Draft"}
              </span>
            </div>

            <div className="flex items-center gap-3 mb-4 text-xs" style={{ color: "var(--admin-muted)" }}>
              <span className="flex items-center gap-1">
                <Users size={12} /> {course.difficulty || "—"}
              </span>
              <span className="flex items-center gap-1">
                ★ {(course.avg_rating != null && !isNaN(course.avg_rating)) ? Number(course.avg_rating).toFixed(1) : "0.0"}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => navigate(`/courses/${course.id}`)}
                className="admin-btn admin-btn-ghost admin-btn-icon text-xs"
                title="View course"
              >
                <Eye size={14} />
              </button>
              <button
                onClick={() => navigate(`/admin/courses/${course.id}/editor`)}
                className="admin-btn admin-btn-ghost admin-btn-icon text-xs"
                title="Edit course"
              >
                <Edit2 size={14} />
              </button>
              <button
                onClick={() => handleDelete(course.id)}
                disabled={deleting === course.id}
                className="admin-btn text-xs px-3 py-1.5 flex items-center gap-1"
                style={{
                  border: "1px solid var(--admin-hairline)",
                  color: "var(--admin-error)",
                }}
              >
                {deleting === course.id ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Trash2 size={12} />
                )}
                Delete
              </button>
            </div>
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="col-span-full py-16 text-center" style={{ color: "var(--admin-ink-tertiary)" }}>
            <BookOpen size={48} className="mx-auto mb-4 opacity-40" />
            <p>No courses found</p>
          </div>
        )}
      </div>
    </div>
  );
}
