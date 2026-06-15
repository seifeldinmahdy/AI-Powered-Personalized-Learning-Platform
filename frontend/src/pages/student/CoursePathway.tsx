import { useParams, useNavigate } from "react-router";
import { useState, useEffect, useRef } from "react";
import { getCurrentPathway, type PathwayPlan, type PathwaySession } from "../../services/pathway";
import {
  getCourseResume, getRemediationReview,
  type CourseResume, type ResumeTimelineEntry, type RemediationReview,
} from "../../services/resume";
import { getCourseById } from "../../services/courses";

/* Course Pathway — codex, two modes on one page:
   - GENERATE: first visit (no saved pathway) → build it, reveal the plan.
   - PROGRESS: pathway already saved → load enrollment.current_pathway and show
     where the student is (done / current / upcoming), derived from the real
     enrollment.progress_percentage spread across the sessions.
   Everything shown is real (saved PathwayPlan + course title + progress).
   No fabricated time estimates, no hardcoded course name. */

const LOADING_MESSAGES = [
  "Analyzing your placement results…",
  "Mapping the book's knowledge structure…",
  "Building your personalized curriculum…",
  "Ordering topics for optimal learning…",
  "Grouping content into focused sessions…",
  "Applying adaptive difficulty calibration…",
  "Finalizing your session plan…",
];

type Phase = "init" | "generating" | "ready" | "error";
type SessionStatus = "done" | "current" | "upcoming" | "start" | "locked";

// ── progress-view derivations (all from real enrollment data) ──
const MASTERY_TIERS = ["NOVICE", "INTERMEDIATE", "EXPERT"];
const pad2 = (n: number) => String(n).padStart(2, "0");

function tierFromScore(s: number | null): string | null {
  if (s == null) return null;
  if (s < 40) return "NOVICE";
  if (s < 70) return "INTERMEDIATE";
  return "EXPERT";
}
function nextTier(t: string): string | null {
  const i = MASTERY_TIERS.indexOf(t);
  return i >= 0 && i < MASTERY_TIERS.length - 1 ? MASTERY_TIERS[i + 1] : null;
}
function fmtDate(d: Date): string {
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }).toUpperCase();
}

interface EnrollmentRow {
  id: number;
  course: number;
  current_lesson: number | null;
  progress_percentage: string;
  is_pathway_ready: boolean;
  current_pathway: PathwayPlan | Record<string, never> | null;
  placement_score: number | null;
  enrolled_at: string;
  last_accessed: string;
}

interface StudentContextProfile {
  student_id?: string; course_id?: string; mastery_level?: string;
  composition_mode?: string; language_proficiency?: string;
  strengths?: string[]; weaknesses?: string[];
  topic_performance?: Record<string, number>;
  incorrectly_answered?: Array<{ question: string; chosen_option: string; correct_option: string }>;
}

function hasSessions(cp: EnrollmentRow["current_pathway"]): cp is PathwayPlan {
  return !!cp && Array.isArray((cp as PathwayPlan).sessions) && (cp as PathwayPlan).sessions.length > 0;
}

export default function CoursePathway() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();

  const [phase, setPhase] = useState<Phase>("init");
  const [mode, setMode] = useState<"generate" | "progress">("generate");
  const [plan, setPlan] = useState<PathwayPlan | null>(null);
  const [courseTitle, setCourseTitle] = useState("");
  const [error, setError] = useState("");
  const [messageIndex, setMessageIndex] = useState(0);
  const [firstLessonId, setFirstLessonId] = useState<number | null>(null);
  const [resume, setResume] = useState<CourseResume | null>(null);
  const [reviewOpenId, setReviewOpenId] = useState<number | null>(null);
  const [reviewChunks, setReviewChunks] = useState<RemediationReview['chunks']>([]);
  const [reviewLoading, setReviewLoading] = useState(false);

  // Resume summary (index + current plan; no content scan).
  useEffect(() => {
    if (!courseId) return;
    getCourseResume(courseId).then(setResume).catch(() => setResume(null));
  }, [courseId]);

  // Open/close a remediation step's review content (fetched on demand).
  async function openReview(e: ResumeTimelineEntry) {
    if (e.concept == null || !courseId) return;
    if (reviewOpenId === e.id) { setReviewOpenId(null); return; }
    setReviewLoading(true);
    setReviewOpenId(e.id ?? null);
    try {
      const r = await getRemediationReview(e.concept, courseId);
      setReviewChunks(r.chunks);
    } catch {
      setReviewChunks([]);
    } finally {
      setReviewLoading(false);
    }
  }
  const [currentLessonId, setCurrentLessonId] = useState<number | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [placementScore, setPlacementScore] = useState<number | null>(null);
  const [enrolledAt, setEnrolledAt] = useState<string>("");
  const [lastAccessed, setLastAccessed] = useState<string>("");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!courseId) return;
    getCourseById(Number(courseId)).then((c) => setCourseTitle(c.title)).catch(() => {});
  }, [courseId]);

  // cycle messages only while generating
  useEffect(() => {
    if (phase !== "generating") return;
    intervalRef.current = setInterval(() => setMessageIndex((p) => (p + 1) % LOADING_MESSAGES.length), 25000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [phase]);

  // READ the current authoritative plan on mount — never generate here.
  // The plan is generated once, server-side, after placement.
  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;

    // resolve first lesson id for routing/fallback
    import("../../services/lessons").then(async ({ getModules, getLessons }) => {
      try {
        const mods = await getModules(Number(courseId));
        if (mods.length > 0) {
          mods.sort((a, b) => a.module_order - b.module_order);
          const lessons = await getLessons(mods[0].id);
          if (lessons.length > 0) { lessons.sort((a, b) => a.lesson_order - b.lesson_order); if (!cancelled) setFirstLessonId(lessons[0].id); }
          else if (!cancelled) setFirstLessonId(1);
        } else if (!cancelled) setFirstLessonId(1);
      } catch { if (!cancelled) setFirstLessonId(1); }
    });

    async function run() {
      let enrollment: EnrollmentRow | undefined;
      try {
        const res = await getEnrollments();
        const list: EnrollmentRow[] = Array.isArray(res.data) ? res.data : res.data?.results || [];
        enrollment = list.find((e) => e.course === Number(courseId));
      } catch { /* ignore */ }

      if (cancelled) return;

      if (enrollment) {
        setCurrentLessonId(enrollment.current_lesson);
        setProgressPct(Math.max(0, Math.min(100, parseFloat(enrollment.progress_percentage) || 0)));
        setPlacementScore(typeof enrollment.placement_score === "number" ? enrollment.placement_score : null);
        setEnrolledAt(enrollment.enrolled_at || "");
        setLastAccessed(enrollment.last_accessed || "");
      }

      // PROGRESS MODE — saved pathway already exists, don't regenerate
      if (enrollment && enrollment.is_pathway_ready && hasSessions(enrollment.current_pathway)) {
        setPlan(enrollment.current_pathway);
        setMode("progress");
        setPhase("ready");
        return;
      }

      // GENERATE MODE
      setMode("generate");
      setPhase("generating");
      try {
        const authUser = localStorage.getItem("auth_user");
        const studentId = authUser ? JSON.parse(authUser).id : "mvp_student_001";

        let ctx: StudentContextProfile | null = null;
        try {
          const ctxRes = await fetch(`${import.meta.env.VITE_AI_SERVICE_URL || "http://localhost:8001"}/student-context/${studentId}/${courseId}`);
          if (ctxRes.ok) ctx = (await ctxRes.json()).profile;
        } catch (e) { console.warn("Could not fetch student context, using defaults", e); }

        // Resolve the course title so the backend can map the Django course id
        // to its ChromaDB book name. Fetch fresh to avoid racing the title effect.
        let title = courseTitle;
        if (!title) {
          try { title = (await getCourseById(Number(courseId))).title; } catch { /* ignore */ }
        }

        const result = await generatePathway({
          student_id: ctx?.student_id || String(studentId),
          course_id: String(courseId),
          course_title: title,
          mastery_level: ctx?.mastery_level || "Novice",
          composition_mode: ctx?.composition_mode || "balanced",
          language_proficiency: ctx?.language_proficiency || "Intermediate",
          strengths: ctx?.strengths || [],
          weaknesses: ctx?.weaknesses || [],
          topic_performance: ctx?.topic_performance || {},
          incorrectly_answered: ctx?.incorrectly_answered || [],
          use_synthetic_context: false,
        });
        if (cancelled) return;

        if (enrollment) {
          try { await api.post(`/courses/enrollments/${enrollment.id}/save_pathway/`, { pathway: result }); }
          catch (e) { console.error("Failed to sync pathway to backend", e); }
        }
        setPlan(result);
        setPhase("ready");
      } catch (e) {
        if (!cancelled) { setError(e instanceof Error ? e.message : "Pathway generation failed"); setPhase("error"); }
      }
    }

    run();
    return () => { cancelled = true; };
  }, [courseId]);

  // ── init (brief) ──
  if (phase === "init") {
    return (
      <div className="codex" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-primary)" }}>
        <span className="t-mono steel">LOADING PATHWAY…</span>
      </div>
    );
  }

  // ── generating ──
  if (phase === "generating") {
    return (
      <div className="codex" style={{ flex: 1, overflowY: "auto", background: "var(--bg-primary)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 24, textAlign: "center", gap: 18 }}>
        <div className="t-label" style={{ color: "var(--accent-primary)" }}>BUILDING YOUR PATHWAY</div>
        <div className="t-display" style={{ fontSize: "clamp(30px,4vw,52px)", color: "var(--text-primary)", maxWidth: 640 }}>Designing your curriculum.</div>
        <div className="t-mono steel" style={{ minHeight: 18, maxWidth: 480 }}>{LOADING_MESSAGES[messageIndex]}</div>
        <div style={{ width: 200, height: 2, background: "var(--hairline)", overflow: "hidden", position: "relative", marginTop: 8 }}>
          <div style={{ position: "absolute", height: "100%", width: "40%", background: "var(--accent-primary)", animation: "paiIndeterminate 1.1s ease-in-out infinite" }} />
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
          {LOADING_MESSAGES.map((_, i) => <span key={i} style={{ height: 6, width: i === messageIndex ? 26 : 6, background: i <= messageIndex ? "var(--accent-primary)" : "var(--hairline)", transition: "all 300ms cubic-bezier(.16,1,.3,1)" }} />)}
        </div>
        <div className="t-body" style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 460, marginTop: 4 }}>This can take a few minutes as we read the book and design a curriculum just for you.</div>
        <style>{`@keyframes paiIndeterminate { 0%{left:-40%} 100%{left:100%} }`}</style>
      </div>
    );
  }

  // ── error ──
  if (phase === "error" || !plan) {
    return (
      <div className="codex" style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, padding: 24, background: "var(--bg-primary)", textAlign: "center" }}>
        <div className="t-heading" style={{ fontSize: 26, color: "var(--text-primary)" }}>Pathway generation failed</div>
        <p className="t-body" style={{ color: "var(--text-secondary)", fontSize: 14, maxWidth: 460 }}>{error || "Could not load your learning pathway. Please try again."}</p>
        <button onClick={() => window.location.reload()} className="btn btn-primary">RETRY →</button>
      </div>
    );
  }

  // ── ready ──
  const total = plan.total_sessions || plan.sessions.length;
  const uniqueTopics = new Set(plan.sessions.flatMap((s) => s.topics_covered)).size;
  const isProgress = mode === "progress";
  // sessions completed, derived from overall progress %
  const doneCount = isProgress ? Math.min(total, Math.floor((progressPct / 100) * total)) : 0;
  const pad = "clamp(20px,5vw,64px)";

  const statusFor = (i: number): SessionStatus => {
    if (!isProgress) return i === 0 ? "start" : "upcoming";
    if (i < doneCount) return "done";
    if (i === doneCount && doneCount < total) return "current";
    return "upcoming";
  };

  const resumeLessonId = currentLessonId ?? firstLessonId;
  const ctaLabel = !isProgress
    ? (firstLessonId === null ? "PREPARING COURSE…" : "BEGIN COURSE")
    : progressPct >= 100 ? "REVIEW COURSE" : "CONTINUE LEARNING";

  const goToCurrent = () => {
    sessionStorage.setItem("pathway_plan", JSON.stringify(plan));
    if (resumeLessonId) navigate(`/course/${courseId}/lesson/${resumeLessonId}`);
  };

  // ── PROGRESS MODE — the "where am I" view (dashboard re-entry) ──
  if (isProgress) {
    const isComplete = progressPct >= 100;
    const position = isComplete ? total : Math.min(doneCount + 1, total);
    const currentSession = plan.sessions[position - 1] ?? plan.sessions[plan.sessions.length - 1];

    // measured pace from real timestamps (sessions completed / weeks since enrolment)
    const now = Date.now();
    const enrolledMs = enrolledAt ? new Date(enrolledAt).getTime() : now;
    const weeksElapsed = Math.max((now - enrolledMs) / (7 * 86_400_000), 1 / 7);
    const pace = doneCount > 0 ? doneCount / weeksElapsed : 0;
    const remaining = total - doneCount;
    const estDate = pace > 0 && remaining > 0 ? new Date(now + (remaining / pace) * 7 * 86_400_000) : null;

    // activity status from real last_accessed (no invented deadline)
    const lastMs = lastAccessed ? new Date(lastAccessed).getTime() : 0;
    const daysIdle = lastMs ? (now - lastMs) / 86_400_000 : Infinity;
    const activity = isComplete ? "COMPLETE" : doneCount === 0 ? "NOT STARTED" : daysIdle <= 10 ? "ON TRACK" : "IDLE";
    const activityColor = activity === "ON TRACK" || activity === "COMPLETE" ? "var(--accent-success)"
      : activity === "IDLE" ? "var(--accent-warm)" : "var(--text-secondary)";

    const tier = tierFromScore(placementScore);
    const goal = tier ? nextTier(tier) : null;

    const statusForP = (i: number): SessionStatus =>
      i < doneCount ? "done" : i === doneCount && !isComplete ? "current" : "locked";

    const stats: Array<[string, string, string]> = [
      ["EST. COMPLETION", isComplete ? "DONE" : estDate ? fmtDate(estDate) : "—", "var(--text-primary)"],
      ["TOTAL SESSIONS", String(total), "var(--text-primary)"],
      ["CURRENT POSITION", `${pad2(position)} / ${pad2(total)}`, "var(--accent-primary)"],
      ["PACE", pace > 0 ? `${pace.toFixed(1)}/WK` : "—", activityColor],
    ];

    return (
      <div className="codex" style={{ flex: 1, overflowY: "auto", background: "var(--bg-primary)" }}>
        <style>{`
          .pai-pw-grid { display: grid; grid-template-columns: 1fr; gap: 28px; }
          @media (min-width: 920px) {
            .pai-pw-grid { grid-template-columns: minmax(280px, 320px) 1fr; gap: 40px; align-items: start; }
            .pai-pw-aside { position: sticky; top: 24px; }
          }
          @media print { .pai-pw-noprint { display: none !important; } }
        `}</style>
        <div style={{ padding: `clamp(24px,4vw,44px) ${pad} 80px`, maxWidth: 1180, marginInline: "auto" }}>
          <button onClick={() => navigate(-1)} className="t-label pai-pw-noprint" style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--text-secondary)", marginBottom: 26 }}>← BACK</button>

          <div className="pai-pw-grid">
            {/* ── sidebar: where you are ── */}
            <aside className="pai-pw-aside" style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 10, padding: 26 }}>
              <div className="t-label" style={{ color: "var(--accent-primary)" }}>{isComplete ? "COURSE COMPLETE" : "CURRENT SESSION"}</div>
              <div className="t-display" style={{ fontSize: "clamp(56px,9vw,88px)", color: "var(--accent-primary)", lineHeight: 0.9, marginTop: 8 }}>{pad2(position)}</div>
              <div className="t-heading" style={{ fontSize: 20, color: "var(--text-primary)", marginTop: 12 }}>{currentSession?.session_title}</div>
              <div className="t-mono steel" style={{ marginTop: 8 }}>SESSION {pad2(position)} OF {pad2(total)}</div>

              <div style={{ marginTop: 20 }}>
                <div className="progress"><i style={{ width: `${Math.max(2, progressPct)}%` }} /></div>
                <div className="t-mono" style={{ color: "var(--accent-primary)", marginTop: 8 }}>{Math.round(progressPct)}% COMPLETE</div>
              </div>

              {currentSession?.topics_covered?.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 18 }}>
                  {currentSession.topics_covered.slice(0, 6).map((t, i) => (
                    <span key={i} className="t-mono" style={{ color: "var(--steel-light)", border: "1px solid var(--hairline)", padding: "3px 7px", borderRadius: 4 }}>{t}</span>
                  ))}
                </div>
              )}

              <button onClick={goToCurrent} className="btn btn-red pai-pw-noprint" style={{ marginTop: 24, width: "100%", justifyContent: "space-between", padding: "18px 22px" }}>
                {isComplete ? "REVIEW COURSE" : "RESUME SESSION"} <span>→</span>
              </button>
            </aside>

            {/* ── main: the full plan ── */}
            <main style={{ minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 12 }}>YOUR PATHWAY · IN PROGRESS</div>
                  <div className="t-display" style={{ fontSize: "clamp(32px,5vw,56px)", color: "var(--text-primary)", lineHeight: 0.96 }}>
                    {courseTitle || "Your learning pathway"}<span style={{ color: "var(--accent-primary)" }}>.</span>
                  </div>
                  {tier && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
                      <span className="t-label" style={{ color: "var(--text-secondary)", border: "1px solid var(--hairline)", padding: "5px 10px", borderRadius: 6 }}>
                        {tier}{goal ? ` → ${goal}` : ""}
                      </span>
                    </div>
                  )}
                </div>
                <button onClick={() => window.print()} className="btn pai-pw-noprint" style={{ flexShrink: 0 }}>EXPORT PDF</button>
              </div>

              {/* stat strip */}
              <div style={{ marginTop: 28, background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px,1fr))" }}>
                {stats.map(([label, v, color], i) => (
                  <div key={label} style={{ padding: "20px 22px", borderRight: i < stats.length - 1 ? "1px solid var(--hairline)" : "none" }}>
                    <div className="t-label" style={{ color: "var(--text-secondary)" }}>{label}</div>
                    <div className="t-display" style={{ fontSize: "clamp(24px,3vw,34px)", marginTop: 10, color }}>{v}</div>
                    {label === "PACE" && <div className="t-mono" style={{ color: activityColor, marginTop: 4 }}>{activity}</div>}
                  </div>
                ))}
              </div>

              {/* sessions */}
              <div style={{ marginTop: 36 }}>
                <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 18 }}>THE PLAN · {total} SESSIONS</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {plan.sessions.map((s, i) => <SessionRow key={s.session_number} session={s} status={statusForP(i)} />)}
                </div>
              </div>
            </main>
          </div>
        </div>
      </div>
    );
  }

  // ── GENERATE MODE — first reveal after placement ──
  return (
    <div className="codex" style={{ flex: 1, overflowY: "auto", background: "var(--bg-primary)" }}>
      <div style={{ padding: `clamp(28px,4vw,48px) ${pad} 80px`, maxWidth: 1080, marginInline: "auto" }}>
        <button onClick={() => navigate(-1)} className="t-label" style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--text-secondary)", marginBottom: 26 }}>← BACK</button>

        <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 14 }}>{isProgress ? "YOUR PATHWAY · IN PROGRESS" : "YOUR PERSONALIZED PATHWAY"}</div>
        <div className="t-display" style={{ fontSize: "clamp(38px,6vw,72px)", color: "var(--text-primary)", lineHeight: 0.95 }}>
          {courseTitle || "Your learning pathway"}<span style={{ color: "var(--accent-primary)" }}>.</span>
        {resume && resume.completed > 0 && (
          <div className="mb-6 rounded-2xl border border-border bg-card p-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-semibold">Continue where you left off</p>
                <p className="text-sm text-muted-foreground">
                  {resume.completed} of {resume.total_sessions} sessions complete
                  {' · '}{resume.sessions_left} left
                </p>
              </div>
              {resume.current_lesson && (
                <button
                  onClick={() => navigate(`/course/${courseId}/lesson/${resume.current_lesson}`)}
                  className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-primary to-secondary text-white font-semibold flex items-center gap-2 shrink-0"
                >
                  Continue <ChevronRight size={18} />
                </button>
              )}
            </div>
            {resume.timeline.length > 0 && (
              <ul className="mt-4 space-y-1.5 border-t border-border pt-3">
                {resume.timeline.map((e, i) => {
                  // Remediation: a review step for a weak concept. Actionable —
                  // clicking fetches the concept's review chunks on demand.
                  if (e.type === 'remediation') {
                    const open = reviewOpenId === e.id;
                    return (
                      <li key={`rem-${e.id ?? i}`} className="text-sm">
                        <div
                          onClick={() => openReview(e)}
                          className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-amber-500/10 cursor-pointer"
                        >
                          <span className="text-amber-600 w-24 shrink-0">Review</span>
                          <span className="flex-1 truncate">Needs review (mastery dropped)</span>
                          <span className="text-xs text-amber-600">pending</span>
                        </div>
                        {open && (
                          <div className="ml-26 mt-1 mb-2 text-xs text-muted-foreground space-y-1">
                            {reviewLoading ? <p>Loading review…</p>
                              : reviewChunks.length === 0 ? <p>No review material found.</p>
                              : reviewChunks.map(c => (
                                <p key={c.chunk_id} className="line-clamp-2">• {c.raw_text}</p>
                              ))}
                          </div>
                        )}
                      </li>
                    );
                  }
                  const label = e.type === 'problem_set' ? 'Problem set'
                    : e.type === 'lab' ? 'Coding lab' : 'Slides';
                  const clickable = e.lesson != null;
                  return (
                    <li
                      key={`${e.type}-${e.id ?? e.ps_uid ?? i}`}
                      onClick={clickable ? () => navigate(`/course/${courseId}/lesson/${e.lesson}`) : undefined}
                      className={`flex items-center gap-2 text-sm px-2 py-1.5 rounded-lg ${clickable ? 'hover:bg-muted/50 cursor-pointer' : ''}`}
                    >
                      <span className="text-muted-foreground w-24 shrink-0">{label}</span>
                      <span className="flex-1 truncate">
                        {e.session_number != null ? `Session ${e.session_number}` : `Lesson ${e.lesson}`}
                      </span>
                      {e.type === 'problem_set' && e.best_score != null && (
                        <span className="font-semibold">{e.best_score}/100</span>
                      )}
                      <span className="text-xs text-muted-foreground capitalize">{e.status}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}

        </div>
        <p className="t-body" style={{ color: "var(--text-secondary)", fontSize: 16, marginTop: 18, maxWidth: 620 }}>
          {isProgress
            ? "Pick up where you left off. Your sessions, sequenced and paced around you."
            : "Built from your placement results — sequenced, paced, and grouped into focused sessions that are yours alone."}
        </p>

        {/* progress bar (progress mode) */}
        {isProgress && (
          <div style={{ maxWidth: 560, marginTop: 26 }}>
            <div className="progress"><i style={{ width: `${Math.max(2, progressPct)}%` }} /></div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10 }}>
              <span className="t-mono" style={{ color: "var(--accent-primary)" }}>{Math.round(progressPct)}% COMPLETE</span>
              <span className="t-mono steel">{doneCount} OF {total} SESSIONS</span>
            </div>
          </div>
        )}

        {/* stat strip */}
        <div style={{ marginTop: 32, background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px,1fr))" }}>
          {[
            ["SESSIONS", `${total}`],
            ["TOPICS", `${uniqueTopics}`],
            ["CONTENT CHUNKS", `${plan.total_chunks}`],
          ].map(([label, v], i) => (
            <div key={label} style={{ padding: "22px 24px", borderRight: i < 2 ? "1px solid var(--hairline)" : "none" }}>
              <div className="t-label" style={{ color: "var(--text-secondary)" }}>{label}</div>
              <div className="t-display" style={{ fontSize: "clamp(30px,3.6vw,44px)", marginTop: 10, color: "var(--text-primary)" }}>{v}</div>
            </div>
          ))}
        </div>

        {/* sessions */}
        <div style={{ marginTop: 44 }}>
          <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 20 }}>THE PLAN · {total} SESSIONS</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {plan.sessions.map((s, i) => <SessionRow key={s.session_number} session={s} status={statusFor(i)} />)}
          </div>
        </div>

        <button
          disabled={!isProgress && firstLessonId === null}
          onClick={() => {
            sessionStorage.setItem("pathway_plan", JSON.stringify(plan));
            const target = isProgress ? resumeLessonId : firstLessonId;
            if (target) navigate(`/course/${courseId}/lesson/${target}`);
          }}
          className="btn btn-red"
          style={{ marginTop: 44, width: "100%", justifyContent: "space-between", padding: "24px 32px", fontSize: 14, opacity: !isProgress && firstLessonId === null ? 0.6 : 1 }}
        >
          {ctaLabel} <span>→</span>
        </button>
      </div>
    </div>
  );
}

function SessionRow({ session, status }: { session: PathwaySession; status: SessionStatus }) {
  const extra = session.topics_covered.length - 5;
  const leftBorder = status === "done" ? "3px solid var(--accent-success)" : status === "current" || status === "start" ? "3px solid var(--accent-primary)" : "1px solid var(--hairline)";
  const numColor = status === "done" ? "var(--accent-success)" : status === "upcoming" || status === "locked" ? "var(--steel-light)" : "var(--accent-primary)";

  const tag =
    status === "done" ? { label: "✓ MASTERED", color: "var(--accent-success)" }
      : status === "current" ? { label: "CURRENT", color: "var(--accent-primary)" }
        : status === "start" ? { label: "START HERE", color: "var(--accent-primary)" }
          : status === "locked" ? { label: "🔒 LOCKED", color: "var(--steel-light)" }
            : null;

  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderLeft: leftBorder, borderRadius: 8, padding: 24, display: "flex", gap: 22, opacity: status === "upcoming" ? 0.92 : status === "locked" ? 0.7 : 1 }}>
      <div className="t-display" style={{ fontSize: "clamp(34px,5vw,52px)", color: numColor, lineHeight: 0.9, flexShrink: 0, minWidth: 52 }}>{String(session.session_number).padStart(2, "0")}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "baseline" }}>
          <div className="t-heading" style={{ fontSize: "clamp(18px,2.4vw,24px)", color: "var(--text-primary)" }}>{session.session_title}</div>
          {tag && <span className="t-label" style={{ color: tag.color, border: `1px solid ${tag.color}`, padding: "4px 8px", borderRadius: 6, flexShrink: 0 }}>{tag.label}</span>}
        </div>

        {session.topics_covered.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14 }}>
            {session.topics_covered.slice(0, 5).map((t, i) => (
              <span key={i} className="t-mono" style={{ color: "var(--steel-light)", border: "1px solid var(--hairline)", padding: "3px 7px", borderRadius: 4 }}>{t}</span>
            ))}
            {extra > 0 && <span className="t-mono steel" style={{ padding: "3px 7px" }}>+{extra} MORE</span>}
          </div>
        )}

        <div className="t-mono steel" style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--hairline)", display: "flex", gap: 18, flexWrap: "wrap" }}>
          <span>{session.chunk_count} CHUNKS</span>
          {session.book && session.page_range_end > 0 && <span>PP. {session.page_range_start}–{session.page_range_end}</span>}
          {session.book && <span style={{ textTransform: "none" }}>{session.book}</span>}
        </div>
      </div>
    </div>
  );
}
