import { useParams, useNavigate, Link } from "react-router";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { getCourseById, submitCourseRating, type Course } from "../services/courses";
import { getEnrollments, enroll } from "../services/api";
import { getCLOs, type CLO } from "../services/clos";
import { DIFF_COLOR } from "../components/personifai/CourseCards";
import { CapstoneStartCTA } from '../components/CapstoneStartCTA';

/* Single course page — codex. Every value shown is pulled from the database
   (course, modules, lessons, enrollment, completions, rating). Nothing is
   fabricated: there is no invented "duration" estimate, no fake enrollment
   counts, and lessons are not shown as artificially "locked". */

function parseSyllabus(raw: Course["syllabus"]): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as string[];
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.map(String);
      if (parsed && typeof parsed === "object") return Object.values(parsed).map(String);
      return [raw];
    } catch {
      return raw.split("\n").map((s) => s.trim()).filter(Boolean);
    }
  }
  if (typeof raw === "object") return Object.values(raw as Record<string, unknown>).map(String);
  return [];
}

interface EnrollmentInfo {
  id: number;
  course: number;
  current_lesson: number | null;
  placement_score: number | null;
  is_pathway_ready: boolean;
  is_assessment_started: boolean;
  progress_percentage: string;
  current_score: number;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ transition: "transform 220ms cubic-bezier(.7,0,.2,1)", transform: open ? "rotate(180deg)" : "none", flexShrink: 0 }}>
      <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function CourseDetail() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const id = Number(courseId);

  const [course, setCourse] = useState<Course | null>(null);
  const [enrollment, setEnrollment] = useState<EnrollmentInfo | null>(null);
  const [clos, setClos] = useState<CLO[]>([]);
  const [loading, setLoading] = useState(true);
  const [enrolling, setEnrolling] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isNaN(id)) { setError("Invalid course ID"); setLoading(false); return; }
    let cancelled = false;
    (async () => {
      try {
        const [courseData, enrollRes] = await Promise.all([
          getCourseById(id),
          getEnrollments().catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setCourse(courseData);

        const raw = enrollRes.data;
        const list: EnrollmentInfo[] = Array.isArray(raw) ? raw : (raw as { results?: EnrollmentInfo[] }).results ?? [];
        const found = list.find((e) => e.course === id) ?? null;
        setEnrollment(found);

        // Already enrolled with a built pathway → the student doesn't need the
        // marketing page (price / outcomes / syllabus) again. Send them straight
        // to the "where you are" pathway view with its continue-to-session CTA.
        if (found?.is_pathway_ready) {
          navigate(`/course/${id}/pathway`, { replace: true });
          return;
        }

        // Course Learning Outcomes — shown to students browsing the course.
        getCLOs(id).then((c) => { if (!cancelled) setClos(c); }).catch(() => { /* non-critical */ });


      } catch {
        if (!cancelled) setError("Failed to load course details.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [id]);



  const handleStart = async () => {
    if (!course) return;
    setEnrolling(true);
    try {
      if (enrollment) {
        // Already enrolled + pathway built → the resume/progress view, which
        // shows where they are and offers "continue to current lesson".
        if (enrollment.is_pathway_ready) {
          navigate(`/course/${id}/pathway`);
          return;
        }
        // Enrolled but placement not finished → (resume) assessment.
        navigate(`/courses/${id}/assessment`, { state: { enrollmentId: enrollment.id, courseTitle: course.title } });
        return;
      }
      const { data } = await enroll(id);
      navigate(`/courses/${id}/assessment`, { state: { enrollmentId: data.id, courseTitle: course.title } });
    } catch {
      toast.error("Failed to start. Please try again.");
    } finally {
      setEnrolling(false);
    }
  };

  if (loading) {
    return (
      <div className="codex" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-primary)" }}>
        <span className="t-mono steel">LOADING COURSE…</span>
      </div>
    );
  }

  if (error || !course) {
    return (
      <div className="codex" style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 18, background: "var(--bg-primary)" }}>
        <span className="t-heading" style={{ fontSize: 24, color: "var(--text-primary)" }}>{error || "Course not found."}</span>
        <Link to="/courses" className="t-label" style={{ color: "var(--accent-primary)", textDecoration: "none" }}>← ALL COURSES</Link>
      </div>
    );
  }

  const syllabus = parseSyllabus(course.syllabus);
  const isEnrolled = !!enrollment;
  const diffColor = DIFF_COLOR[course.difficulty] || "#6E665A";
  const rating = parseFloat(course.avg_rating);
  const price = parseFloat(course.price);
  const progress = enrollment ? parseFloat(enrollment.progress_percentage) || 0 : 0;
  const pad = "clamp(20px,5vw,64px)";

  return (
    <div className="codex" style={{ flex: 1, overflowY: "auto", background: "var(--bg-primary)" }}>
      <style>{`
        .cd-grid { display:grid; grid-template-columns: minmax(0,1fr) 340px; gap: 44px; align-items:start; }
        .cd-aside { position: sticky; top: 24px; }
        @media (max-width: 900px) {
          .cd-grid { grid-template-columns: 1fr; gap: 32px; }
          .cd-main { grid-row: 2; }
          .cd-aside { grid-row: 1; position: static; }
        }
      `}</style>

      <div style={{ padding: `clamp(24px,3vw,40px) ${pad} 64px`, maxWidth: 1180, marginInline: "auto" }}>
        {/* Back */}
        <Link to="/courses" className="t-label" style={{ color: "var(--text-secondary)", textDecoration: "none", display: "inline-block", marginBottom: 28 }}>← ALL COURSES</Link>

        {/* Header */}
        <div style={{ marginBottom: 40 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 18, flexWrap: "wrap" }}>
            <span className="tag-red" style={{ color: diffColor, borderColor: diffColor }}>{course.difficulty || "COURSE"}</span>
            <span className="tag-steel">{price > 0 ? `$${course.price}` : "FREE"}</span>
            {course.status && course.status !== "Published" ? <span className="tag-steel">{course.status.toUpperCase()}</span> : null}
          </div>

          <div className="t-display" style={{ fontSize: "clamp(38px,6vw,72px)", color: "var(--text-primary)", maxWidth: 920 }}>{course.title}</div>

          {course.description ? (
            <p className="t-body" style={{ color: "var(--text-secondary)", fontSize: 16, lineHeight: 1.6, maxWidth: 680, marginTop: 20 }}>{course.description}</p>
          ) : null}

          {/* Real stat row */}
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 24 }} className="t-mono steel">
            <span>{course.total_lessons_count} SESSIONS</span>
            {rating > 0 ? <span style={{ color: "var(--text-primary)" }}>★ {course.avg_rating}</span> : <span>UNRATED</span>}
          </div>

          {/* Enrolled progress */}
          {isEnrolled && (
            <div style={{ maxWidth: 540, marginTop: 28 }}>
              <div className="progress"><i style={{ width: `${Math.max(2, progress)}%` }} /></div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, gap: 8 }}>
                <span className="t-mono" style={{ color: "var(--accent-primary)" }}>{Math.round(progress)}% COMPLETE</span>
                {enrollment?.placement_score != null && (
                  <span className="t-mono steel">PLACEMENT · {Math.round(enrollment.placement_score)}/100</span>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="cd-grid">
          {/* Main */}
          <div className="cd-main" style={{ display: "flex", flexDirection: "column", gap: 40 }}>
            {/* Tags */}
            {course.tags && course.tags.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {course.tags.map((t, i) => (
                  <span key={i} className="t-mono" style={{ color: "var(--steel-light)", border: "1px solid var(--hairline)", padding: "4px 8px", borderRadius: 4 }}>{t}</span>
                ))}
              </div>
            )}

            {/* What you'll learn */}
            {syllabus.length > 0 && (
              <section>
                <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 18 }}>WHAT YOU'LL LEARN</div>
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
                  {syllabus.map((item, i) => (
                    <li key={i} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                      <span style={{ width: 6, height: 6, background: "var(--accent-success)", marginTop: 8, flexShrink: 0 }} />
                      <span className="t-body" style={{ fontSize: 14, color: "var(--text-primary)" }}>{item}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Course Learning Outcomes — what the student will be able to do */}
            {clos.length > 0 && (
              <section>
                <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 18 }}>
                  COURSE LEARNING OUTCOMES · {clos.length}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {clos.map((clo) => (
                    <div key={clo.id} style={{ display: "flex", gap: 16, alignItems: "flex-start", background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, padding: "16px 18px" }}>
                      <span className="t-mono" style={{ color: "var(--accent-primary)", flexShrink: 0, paddingTop: 2 }}>{clo.code}</span>
                      <span className="t-body" style={{ fontSize: 14, color: "var(--text-primary)", flex: 1, lineHeight: 1.55 }}>{clo.text}</span>
                      {clo.bloom_level && (
                        <span className="t-mono steel" style={{ flexShrink: 0, border: "1px solid var(--hairline)", borderRadius: 4, padding: "2px 8px", textTransform: "uppercase" }}>{clo.bloom_level}</span>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}


          </div>

          {/* Aside CTA */}
          <aside className="cd-aside">
            <CtaPanel
              course={course}
              price={price}
              isEnrolled={isEnrolled}
              enrolling={enrolling}
              enrollment={enrollment}
              courseId={id}
              onStart={handleStart}
              onRated={(avg) => setCourse((prev) => (prev ? { ...prev, avg_rating: String(avg) } : prev))}
            />
          </aside>
        </div>
      </div>
    </div>
  );
}

function CtaPanel({
  course, price, isEnrolled, enrolling, enrollment, courseId, onStart, onRated,
}: {
  course: Course;
  price: number;
  isEnrolled: boolean;
  enrolling: boolean;
  enrollment: EnrollmentInfo | null;
  courseId: number;
  onStart: () => void;
  onRated: (avg: number) => void;
}) {
  const [hovered, setHovered] = useState(0);
  const [myRating, setMyRating] = useState(0);
  const [rating, setRating] = useState(false);

  const rate = async (stars: number) => {
    if (rating) return;
    setRating(true);
    try {
      const res = await submitCourseRating(courseId, stars);
      setMyRating(stars);
      onRated(res.avg_rating);
      toast.success(`Rated ${stars} star${stars !== 1 ? "s" : ""}`);
    } catch {
      toast.error("Failed to submit rating.");
    } finally {
      setRating(false);
    }
  };

  const primaryLabel = !isEnrolled
    ? "START ASSESSMENT & ENROLL"
    : enrollment?.is_pathway_ready
      ? "CONTINUE LEARNING"
      : enrollment?.is_assessment_started
        ? "RESUME ASSESSMENT"
        : "START ASSESSMENT";

  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, padding: 26, display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <div className="t-display" style={{ fontSize: 40, color: price > 0 ? "var(--text-primary)" : "var(--accent-success)" }}>
          {price > 0 ? `$${course.price}` : "Free"}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 4, borderTop: "1px solid var(--hairline)" }}>
        {[
          ["LEVEL", course.difficulty || "—"],
          ...(parseFloat(course.avg_rating) > 0 ? [["RATING", `★ ${course.avg_rating}`]] : []),
        ].map(([k, v]) => (
          <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 12 }}>
            <span className="t-label" style={{ color: "var(--text-secondary)" }}>{k}</span>
            <span className="t-mono" style={{ color: "var(--text-primary)" }}>{v}</span>
          </div>
        ))}
      </div>

      <button onClick={onStart} disabled={enrolling} className="btn btn-primary" style={{ width: "100%", justifyContent: "space-between" }}>
        {enrolling ? "WORKING…" : primaryLabel} <span>→</span>
      </button>

            {/* Capstone entry — appears once the coursework is finished */}
            {isEnrolled && enrollment && parseFloat(enrollment.progress_percentage ?? '0') >= 100 && (
                <CapstoneStartCTA courseId={courseId} variant="card" />
            )}

      {isEnrolled ? (
        <div style={{ paddingTop: 4 }}>
          <div className="t-label" style={{ color: "var(--text-secondary)", textAlign: "center", marginBottom: 10 }}>{myRating > 0 ? "YOUR RATING" : "RATE THIS COURSE"}</div>
          <div style={{ display: "flex", justifyContent: "center", gap: 6 }}>
            {[1, 2, 3, 4, 5].map((star) => (
              <button key={star} disabled={rating} onClick={() => rate(star)} onMouseEnter={() => setHovered(star)} onMouseLeave={() => setHovered(0)} style={{ background: "transparent", border: "none", cursor: rating ? "default" : "pointer", padding: 0, fontSize: 22, lineHeight: 1, color: star <= (hovered || myRating) ? "var(--ink-black)" : "var(--steel)" }}>★</button>
            ))}
          </div>
        </div>
      ) : (
        <p className="t-mono steel" style={{ textAlign: "center", lineHeight: 1.5, margin: 0 }}>
          A short placement test personalizes your pathway before the first slide.
        </p>
      )}
    </div>
  );
}
