import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useAuth } from "../../contexts/AuthContext";
import { getEnrollments } from "../../services/api";
import { getCourses, type Course } from "../../services/courses";
import { getStudentProfile, type StudentProfile } from "../../services/profile";
import { getLessonCompletions, type LessonCompletion } from "../../services/progress";
import { EnrolledCourseCard, ExploreCourseCard, type EnrolledView } from "../../components/personifai/CourseCards";

interface EnrollmentRow {
  id: number;
  course: number;
  course_title: string;
  current_lesson: number | null;
  progress_percentage: string;
  current_score: number;
  is_pathway_ready: boolean;
  last_accessed: string | null;
}

function todayLabel(): string {
  const now = new Date();
  const wd = now.toLocaleDateString("en-US", { weekday: "long" });
  const mo = now.toLocaleDateString("en-US", { month: "long" });
  return `${wd} · ${now.getDate()} ${mo} ${now.getFullYear()}`.toUpperCase();
}

export default function Dashboard() {
  const { user } = useAuth();
  const firstName = (user?.full_name || user?.username || "Learner").split(" ")[0];

  const [loading, setLoading] = useState(true);
  const [enrollments, setEnrollments] = useState<EnrollmentRow[]>([]);
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [completions, setCompletions] = useState<LessonCompletion[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [enrollRes, profileRes, completionsRes, coursesRes] = await Promise.allSettled([
        getEnrollments(),
        getStudentProfile(),
        getLessonCompletions(),
        getCourses({ ordering: "-created_at" }),
      ]);
      if (cancelled) return;
      if (enrollRes.status === "fulfilled") {
        const raw = enrollRes.value.data;
        setEnrollments(Array.isArray(raw) ? raw : raw.results ?? []);
      }
      if (profileRes.status === "fulfilled") setProfile(profileRes.value);
      if (completionsRes.status === "fulfilled") setCompletions(completionsRes.value);
      if (coursesRes.status === "fulfilled") setCourses(coursesRes.value.results);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  const courseMap = new Map(courses.map((c) => [c.id, c]));
  const enrolledIds = new Set(enrollments.map((e) => e.course));

  const enrolledViews: EnrolledView[] = enrollments.map((e) => {
    const c = courseMap.get(e.course);
    return {
      courseId: e.course,
      title: e.course_title,
      difficulty: c?.difficulty,
      totalLessons: c?.total_lessons_count,
      progress: parseFloat(e.progress_percentage) || 0,
      score: e.current_score,
      lastAccessed: e.last_accessed,
      resumeTo: e.is_pathway_ready && e.current_lesson
        ? `/course/${e.course}/lesson/${e.current_lesson}`
        : `/courses/${e.course}`,
    };
  });

  const exploreCourses = courses.filter((c) => !enrolledIds.has(c.id)).slice(0, 3);

  const completedCount = completions.filter((c) => c.status === "Completed").length;
  const totalHours = Math.floor((profile?.total_minutes_learned ?? 0) / 60);
  const avgProgress = enrolledViews.length
    ? Math.round(enrolledViews.reduce((s, e) => s + e.progress, 0) / enrolledViews.length)
    : 0;

  const stats: { label: string; value: string; sub: string }[] = [
    { label: "HOURS", value: `${totalHours}`, sub: "total learned" },
    { label: "STREAK", value: `${profile?.current_streak ?? 0}`, sub: "days running" },
    { label: "LESSONS", value: `${completedCount}`, sub: "completed" },
    { label: "LEVEL", value: `${profile?.level ?? 1}`, sub: `${profile?.current_xp ?? 0} XP` },
    { label: "MASTERY", value: `${avgProgress}%`, sub: "avg progress" },
  ];

  const pad = "clamp(20px,5vw,64px)";

  return (
    <div className="codex" style={{ flex: 1, overflowY: "auto", background: "var(--bg-primary)" }}>
      <div style={{ padding: `clamp(28px,4vw,48px) ${pad} 64px`, display: "flex", flexDirection: "column", gap: 40, maxWidth: 1320, marginInline: "auto" }}>

        {/* Greeting */}
        <div>
          <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 12 }}>{todayLabel()}</div>
          <div className="t-heading" style={{ fontSize: "clamp(36px,6vw,64px)", color: "var(--text-primary)" }}>
            Welcome back, {firstName}.<br />
            <span style={{ color: "var(--steel-light)" }}>
              {enrollments.length ? "Pick up where you left off." : "Let's find your first course."}
            </span>
          </div>
        </div>

        {/* Stat strip */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          {stats.map((s, i) => (
            <div key={s.label} style={{ padding: "24px 26px", borderRight: "1px solid var(--hairline)", borderBottom: "1px solid var(--hairline)", ...(i === stats.length - 1 ? { borderRight: "none" } : {}) }}>
              <div className="t-label" style={{ color: "var(--text-secondary)" }}>{s.label}</div>
              <div className="t-display" style={{ fontSize: "clamp(32px,4vw,46px)", marginTop: 12, color: loading ? "var(--steel)" : "var(--text-primary)" }}>{loading ? "—" : s.value}</div>
              <div className="t-mono steel" style={{ marginTop: 8 }}>{s.sub}</div>
            </div>
          ))}
        </div>

        {/* Enrolled courses OR onboarding */}
        {enrollments.length > 0 ? (
          <section>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 22, gap: 12, flexWrap: "wrap" }}>
              <div className="t-label" style={{ color: "var(--accent-primary)" }}>YOUR COURSES · {enrollments.length} ENROLLED</div>
              <Link to="/courses" className="t-label" style={{ color: "var(--text-secondary)", textDecoration: "none" }}>BROWSE ALL →</Link>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 22 }}>
              {enrolledViews.map((e) => <EnrolledCourseCard key={e.courseId} e={e} />)}
            </div>
          </section>
        ) : (
          <Onboarding loading={loading} />
        )}

        {/* Explore preview */}
        {exploreCourses.length > 0 && (
          <section>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 22, gap: 12, flexWrap: "wrap" }}>
              <div className="t-label" style={{ color: "var(--accent-primary)" }}>EXPLORE · {courses.filter((c) => !enrolledIds.has(c.id)).length} AVAILABLE</div>
              <Link to="/courses" className="t-label" style={{ color: "var(--text-secondary)", textDecoration: "none" }}>SEE FULL CATALOG →</Link>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 22 }}>
              {exploreCourses.map((c) => <ExploreCourseCard key={c.id} course={c} />)}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/* Friendly first-run state instead of a blank dashboard. */
function Onboarding({ loading }: { loading: boolean }) {
  const steps = [
    { n: "01", t: "Pick a course", d: "Choose any subject from the catalog below." },
    { n: "02", t: "Take a 5-minute placement", d: "We map exactly what you already know." },
    { n: "03", t: "Get your own pathway", d: "Slides and checkpoints built around you." },
  ];
  return (
    <section style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, padding: "clamp(28px,4vw,44px)", overflow: "hidden", position: "relative" }}>
      <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 14 }}>GET STARTED</div>
      <div className="t-heading" style={{ fontSize: "clamp(28px,4vw,44px)", color: "var(--text-primary)", maxWidth: 720 }}>
        You haven't enrolled yet. <span style={{ color: "var(--steel-light)" }}>Three steps to your first personalized course.</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 0, marginTop: 32, borderTop: "1px solid var(--hairline)" }}>
        {steps.map((s, i) => (
          <div key={s.n} style={{ padding: "24px 24px 24px 0", borderRight: i < steps.length - 1 ? "1px solid var(--hairline)" : "none", paddingLeft: i === 0 ? 0 : 24 }}>
            <div className="t-display" style={{ fontSize: 40, color: "var(--accent-primary)", lineHeight: 1 }}>{s.n}</div>
            <div className="t-heading" style={{ fontSize: 19, color: "var(--text-primary)", marginTop: 14 }}>{s.t}</div>
            <div className="t-body" style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 8 }}>{s.d}</div>
          </div>
        ))}
      </div>
      <Link to="/courses" className="btn btn-primary" style={{ marginTop: 32, textDecoration: "none", display: "inline-flex" }}>
        {loading ? "LOADING…" : "BROWSE COURSES →"}
      </Link>
    </section>
  );
}
