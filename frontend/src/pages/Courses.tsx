import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router";
import { getCourses, type Course } from "../services/courses";
import { getEnrollments } from "../services/api";
import { useAuth } from "../contexts/AuthContext";
import { ExploreCourseCard } from "../components/personifai/CourseCards";

const DIFFICULTY_OPTIONS = ["All", "Beginner", "Intermediate", "Advanced"];
const SORT_OPTIONS = [
  { label: "Newest", value: "-created_at" },
  { label: "Title A–Z", value: "title" },
  { label: "Top rated", value: "-avg_rating" },
  { label: "Price ↑", value: "price" },
];

export default function Courses() {
  const [searchParams] = useSearchParams();
  const { isAuthenticated } = useAuth();
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState(searchParams.get("search") || "");
  const [difficulty, setDifficulty] = useState("All");
  const [ordering, setOrdering] = useState("-created_at");
  const [totalCount, setTotalCount] = useState(0);
  const [enrolledIds, setEnrolledIds] = useState<Set<number>>(new Set());

  const fetchCourses = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { ordering };
      if (search.trim()) params.search = search.trim();
      if (difficulty !== "All") params.difficulty = difficulty;
      const data = await getCourses(params);
      setCourses(data.results);
      setTotalCount(data.count);
    } catch {
      setCourses([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [search, difficulty, ordering]);

  useEffect(() => {
    const t = setTimeout(fetchCourses, 300);
    return () => clearTimeout(t);
  }, [fetchCourses]);

  useEffect(() => {
    if (!isAuthenticated) return;
    getEnrollments()
      .then(({ data: raw }) => {
        const list: Array<{ course: number }> = Array.isArray(raw) ? raw : raw.results ?? [];
        setEnrolledIds(new Set(list.map((e) => e.course)));
      })
      .catch(() => {});
  }, [isAuthenticated]);

  const pad = "clamp(20px,5vw,64px)";

  return (
    <div className="codex" style={{ flex: 1, overflowY: "auto", background: "var(--bg-primary)" }}>
      <div style={{ padding: `clamp(28px,4vw,48px) ${pad} 64px`, display: "flex", flexDirection: "column", gap: 32, maxWidth: 1320, marginInline: "auto" }}>

        {/* Header */}
        <div>
          <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 12 }}>THE CATALOG</div>
          <div className="t-heading" style={{ fontSize: "clamp(34px,5vw,56px)", color: "var(--text-primary)" }}>
            Browse courses<span style={{ color: "var(--steel-light)" }}>.</span>
          </div>
          <div className="t-body" style={{ color: "var(--text-secondary)", fontSize: 14, marginTop: 10 }}>
            {loading ? "Loading…" : `${totalCount} course${totalCount === 1 ? "" : "s"} available`}
          </div>
        </div>

        {/* Controls */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center" }}>
          <input
            className="input"
            placeholder="Search by title, description, or tag…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ flex: "1 1 280px", minWidth: 0 }}
          />
          <div style={{ display: "flex", gap: 0, flexWrap: "wrap" }}>
            {DIFFICULTY_OPTIONS.map((opt, i) => {
              const active = difficulty === opt;
              return (
                <button
                  key={opt}
                  onClick={() => setDifficulty(opt)}
                  className="t-label"
                  style={{
                    padding: "10px 16px",
                    cursor: "pointer",
                    background: active ? "var(--ink-black)" : "transparent",
                    color: active ? "var(--bg-primary)" : "var(--steel-light)",
                    border: "1px solid var(--hairline)",
                    borderLeft: i > 0 ? "none" : "1px solid var(--hairline)",
                  }}
                >
                  {opt}
                </button>
              );
            })}
          </div>
          <select
            value={ordering}
            onChange={(e) => setOrdering(e.target.value)}
            className="input"
            style={{ width: "auto", cursor: "pointer", flex: "0 0 auto" }}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        {/* Grid / states */}
        {loading ? (
          <div className="t-mono steel" style={{ padding: "80px 0", textAlign: "center" }}>LOADING COURSES…</div>
        ) : courses.length === 0 ? (
          <div style={{ padding: "80px 24px", textAlign: "center", border: "1px solid var(--hairline)", borderRadius: 8, background: "var(--bg-surface)" }}>
            <div className="t-heading" style={{ fontSize: 26, color: "var(--text-primary)" }}>No courses found</div>
            <div className="t-body" style={{ color: "var(--text-secondary)", fontSize: 14, marginTop: 10 }}>
              {search ? `No results for "${search}". Try a different term or filter.` : "No courses available yet — check back soon."}
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 22 }}>
            {courses.map((c) => (
              <ExploreCourseCard key={c.id} course={c} enrolled={enrolledIds.has(c.id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
