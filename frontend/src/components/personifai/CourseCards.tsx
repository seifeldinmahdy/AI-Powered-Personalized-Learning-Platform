import { Link } from "react-router";
import type { Course } from "../../services/courses";

/* Shared course cards for the redesigned Dashboard + Courses pages.
   Everything renders from real schema fields only. */

export const DIFF_COLOR: Record<string, string> = {
  Beginner: "#16A34A",
  Intermediate: "#2563EB",
  Advanced: "#DC2626",
};

export function relativeTime(dateStr?: string | null): string {
  if (!dateStr) return "—";
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

export interface EnrolledView {
  courseId: number;
  title: string;
  difficulty?: string;
  totalLessons?: number;
  progress: number; // 0..100
  score: number;
  lastAccessed?: string | null;
  resumeTo: string;
}

export function EnrolledCourseCard({ e }: { e: EnrolledView }) {
  const diffColor = e.difficulty ? DIFF_COLOR[e.difficulty] : undefined;
  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderLeft: "3px solid var(--accent-primary)", borderRadius: 8, padding: 26, display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <span className="tag-red" style={diffColor ? { color: diffColor, borderColor: diffColor } : undefined}>{e.difficulty || "COURSE"}</span>
        {e.totalLessons ? <span className="t-mono steel">{e.totalLessons} LESSONS</span> : null}
      </div>
      <div className="t-display" style={{ fontSize: "clamp(24px,3vw,32px)", lineHeight: 1.0, color: "var(--text-primary)" }}>{e.title}</div>
      <div>
        <div className="progress"><i style={{ width: `${Math.max(2, e.progress)}%` }} /></div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, gap: 8 }}>
          <span className="t-mono" style={{ color: "var(--accent-primary)" }}>{Math.round(e.progress)}% COMPLETE</span>
          <span className="t-mono steel">last active · {relativeTime(e.lastAccessed)}</span>
        </div>
      </div>
      <Link to={e.resumeTo} className="btn" style={{ justifyContent: "space-between", width: "100%", padding: "15px 20px", background: "var(--accent-soft)", color: "#fff", textTransform: "none", letterSpacing: "0.01em", fontSize: 14, textDecoration: "none" }}>
        Continue <span>→</span>
      </Link>
    </div>
  );
}

/* The last-accessed enrolled course, rendered as a wide horizontal hero that
   sits above the regular enrolled grid — deliberately a different shape so the
   "pick up where you left off" course is unmistakable at a glance. */
export function ContinueLearningCard({ e }: { e: EnrolledView }) {
  const diffColor = e.difficulty ? DIFF_COLOR[e.difficulty] : undefined;
  return (
    <div
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--hairline)",
        borderLeft: "4px solid var(--accent-primary)",
        borderRadius: 10,
        padding: "clamp(22px,3vw,32px)",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: "clamp(20px,4vw,48px)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* faint accent wash on the right edge */}
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, transparent 55%, rgba(37,99,235,0.05))", pointerEvents: "none" }} />

      {/* left — identity + progress */}
      <div style={{ flex: "1 1 360px", minWidth: 0, position: "relative" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
          <span className="t-label" style={{ color: "var(--accent-primary)" }}>PICK UP WHERE YOU LEFT OFF</span>
          {e.difficulty && <span className="tag-red" style={diffColor ? { color: diffColor, borderColor: diffColor } : undefined}>{e.difficulty}</span>}
        </div>
        <div className="t-display" style={{ fontSize: "clamp(28px,4vw,46px)", lineHeight: 1.0, color: "var(--text-primary)" }}>{e.title}</div>
        <div style={{ marginTop: 20, maxWidth: 520 }}>
          <div className="progress"><i style={{ width: `${Math.max(2, e.progress)}%` }} /></div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, gap: 8, flexWrap: "wrap" }}>
            <span className="t-mono" style={{ color: "var(--accent-primary)" }}>{Math.round(e.progress)}% COMPLETE</span>
            <span className="t-mono steel">
              {e.totalLessons ? `${e.totalLessons} LESSONS · ` : ""}last active · {relativeTime(e.lastAccessed)}
            </span>
          </div>
        </div>
      </div>

      {/* right — primary continue action */}
      <div style={{ flex: "0 0 auto", position: "relative" }}>
        <Link
          to={e.resumeTo}
          className="btn btn-red"
          style={{ justifyContent: "space-between", gap: 14, padding: "18px 28px", fontSize: 15, textTransform: "none", letterSpacing: "0.01em", textDecoration: "none", minWidth: 220 }}
        >
          {e.progress > 0 ? "Continue learning" : "Start course"} <span>→</span>
        </Link>
      </div>
    </div>
  );
}

export function ExploreCourseCard({ course, enrolled }: { course: Course; enrolled?: boolean }) {
  const color = DIFF_COLOR[course.difficulty] || "#6E665A";
  const rating = parseFloat(course.avg_rating);
  const price = parseFloat(course.price);
  return (
    <Link
      to={`/courses/${course.id}`}
      className="under-red"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderLeft: enrolled ? "3px solid var(--accent-primary)" : "1px solid var(--hairline)", borderRadius: 8, padding: 24, display: "flex", flexDirection: "column", gap: 12, textDecoration: "none", color: "inherit", minHeight: 232 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <span className="tag-red" style={{ color, borderColor: color }}>{course.difficulty || "COURSE"}</span>
        {enrolled
          ? <span className="t-label" style={{ color: "var(--accent-primary)", border: "1px solid var(--accent-primary)", borderRadius: 4, padding: "3px 8px" }}>ENROLLED</span>
          : <span className="t-mono steel">{price > 0 ? `$${course.price}` : "FREE"}</span>}
      </div>
      <div className="t-display" style={{ fontSize: "clamp(22px,2.6vw,28px)", lineHeight: 1.02, color: "var(--text-primary)" }}>{course.title}</div>
      <p style={{ margin: 0, fontFamily: "var(--ff-body)", fontSize: 13, lineHeight: 1.5, color: "var(--text-secondary)", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {course.description || "No description available."}
      </p>
      {course.tags && course.tags.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {course.tags.slice(0, 3).map((t, i) => (
            <span key={i} className="t-mono" style={{ color: "var(--steel-light)", border: "1px solid var(--hairline)", padding: "2px 6px", borderRadius: 4 }}>{t}</span>
          ))}
        </div>
      ) : null}
      <div className="t-mono steel" style={{ marginTop: "auto", paddingTop: 12, borderTop: "1px solid var(--hairline)", display: "flex", gap: 16 }}>
        <span>{course.total_lessons_count} LESSONS</span>
        <span>{rating > 0 ? `★ ${course.avg_rating}` : "UNRATED"}</span>
      </div>
    </Link>
  );
}
