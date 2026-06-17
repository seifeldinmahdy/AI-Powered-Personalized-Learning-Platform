import { useParams, useNavigate } from "react-router";
import { useState, useEffect } from "react";
import { getCurrentPathway, type PathwayPlan, type PathwaySession } from "../../services/pathway";
import {
  getCourseResume, getRemediationReview, getProblemSetHistory, getArtifactContent,
  type CourseResume, type ResumeTimelineEntry, type RemediationReview, type ProblemSetHistory,
} from "../../services/resume";
import { getCourseById } from "../../services/courses";
import { getEnrollments } from "../../services/api";
import { CapstoneStartCTA } from "../../components/CapstoneStartCTA";
import { useMemo } from "react";

/* Course Pathway — read-only progress/resume view (codex / pai design system).
   The pathway is generated ONCE, server-side, after placement; this page never
   generates it. It reads the authoritative plan (getCurrentPathway) plus the
   real enrollment progress and the resume timeline, and shows the student where
   they are. Everything shown is real — no fabricated estimates, no hardcoded
   course name. */

type Phase = "loading" | "ready" | "empty" | "error";
type SessionStatus = "done" | "current" | "locked";

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
  placement_score: number | null;
  enrolled_at: string;
  last_accessed: string;
}

export default function CoursePathway() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();

  const [phase, setPhase] = useState<Phase>("loading");
  const [plan, setPlan] = useState<PathwayPlan | null>(null);
  const [courseTitle, setCourseTitle] = useState("");
  const [error] = useState("");

  // real enrollment progress signals
  const [currentSessionNumber, setCurrentSessionNumber] = useState<number | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [placementScore, setPlacementScore] = useState<number | null>(null);
  const [enrolledAt, setEnrolledAt] = useState("");
  const [lastAccessed, setLastAccessed] = useState("");

  // resume timeline (past slides / lab / problem-sets / remediation), each row
  // expands inline to its content, fetched on demand by type.
  const [resume, setResume] = useState<CourseResume | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [entryLoading, setEntryLoading] = useState(false);
  const [reviewChunks, setReviewChunks] = useState<RemediationReview["chunks"]>([]);
  const [psHistory, setPsHistory] = useState<ProblemSetHistory | null>(null);
  const [artifact, setArtifact] = useState<Record<string, unknown> | null>(null);

  // ── READ the authoritative plan + progress (never generate) ──
  useEffect(() => {
    if (!courseId) return;
    let cancelled = false;

    (async () => {
      const authUser = localStorage.getItem("auth_user");
      const studentId = authUser ? JSON.parse(authUser).id : "mvp_student_001";

      // course title (non-critical)
      getCourseById(Number(courseId)).then((c) => !cancelled && setCourseTitle(c.title)).catch(() => {});

      // enrollment progress signals (non-critical — view still renders without them)
      try {
        const res = await getEnrollments();
        const list: EnrollmentRow[] = Array.isArray(res.data) ? res.data : res.data?.results || [];
        const e = list.find((r) => r.course === Number(courseId));
        if (e && !cancelled) {
          setCurrentSessionNumber(e.current_session_number);
          setProgressPct(Math.max(0, Math.min(100, parseFloat(e.progress_percentage) || 0)));
          setPlacementScore(typeof e.placement_score === "number" ? e.placement_score : null);
          setEnrolledAt(e.enrolled_at || "");
          setLastAccessed(e.last_accessed || "");
        }
      } catch { /* ignore — non-critical */ }

      // the authoritative plan (server-generated). Throws if not ready yet.
      try {
        const p = await getCurrentPathway(String(studentId), String(courseId));
        if (cancelled) return;
        if (p && Array.isArray(p.sessions) && p.sessions.length > 0) {
          setPlan(p);
          setPhase("ready");
        } else {
          setPhase("empty");
        }
      } catch {
        if (!cancelled) setPhase("empty");
      }
    })();

    return () => { cancelled = true; };
  }, [courseId]);

  // resume summary (index + current plan; no content scan)
  useEffect(() => {
    if (!courseId) return;
    getCourseResume(courseId).then(setResume).catch(() => setResume(null));
  }, [courseId]);

  const timelineBySession = useMemo(() => {
    const map = new Map<number, ResumeTimelineEntry[]>();
    if (resume?.timeline) {
      for (const e of resume.timeline) {
        if (e.session_number != null) {
          const list = map.get(e.session_number) || [];
          list.push(e);
          map.set(e.session_number, list);
        }
      }
    }
    return map;
  }, [resume]);

  // a stable key per timeline entry (drives the open/expand state)
  const keyFor = (e: ResumeTimelineEntry, i: number) =>
    e.type === "problem_set" ? `ps-${e.ps_uid ?? i}`
      : e.type === "remediation" ? `rem-${e.id ?? i}`
        : `art-${e.id ?? i}`;

  // expand/collapse a timeline entry, fetching its content on demand by type
  async function toggleEntry(e: ResumeTimelineEntry, key: string) {
    if (openKey === key) { setOpenKey(null); return; }
    setOpenKey(key);
    setReviewChunks([]); setPsHistory(null); setArtifact(null);
    setEntryLoading(true);
    try {
      if (e.type === "remediation" && e.concept != null && courseId) {
        const r = await getRemediationReview(e.concept, courseId);
        setReviewChunks(r.chunks);
      } else if (e.type === "problem_set" && e.ps_uid) {
        setPsHistory(await getProblemSetHistory(e.ps_uid));
      } else if ((e.type === "slides" || e.type === "lab") && e.id != null) {
        setArtifact(await getArtifactContent(e.id));
      }
    } catch {
      /* leave content empty — the expanded row shows a "couldn't load" note */
    } finally {
      setEntryLoading(false);
    }
  }

  const pad = "clamp(20px,5vw,64px)";

  // ── loading ──
  if (phase === "loading") {
    return (
      <div className="codex" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-primary)" }}>
        <span className="t-mono steel">LOADING PATHWAY…</span>
      </div>
    );
  }

  // ── no pathway yet (placement not finished, or still being built server-side) ──
  if (phase === "empty" || phase === "error" || !plan) {
    return (
      <div className="codex" style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, padding: 24, background: "var(--bg-primary)", textAlign: "center" }}>
        <div className="t-label" style={{ color: "var(--accent-primary)" }}>PATHWAY NOT READY</div>
        <div className="t-heading" style={{ fontSize: 26, color: "var(--text-primary)" }}>Your pathway isn't ready yet.</div>
        <p className="t-body" style={{ color: "var(--text-secondary)", fontSize: 14, maxWidth: 460 }}>
          {error || "Once you complete the placement assessment, your personalized pathway is built and appears here."}
        </p>
        <button onClick={() => navigate(`/courses/${courseId}`)} className="btn btn-primary">GO TO COURSE →</button>
      </div>
    );
  }

  // ── ready: read-only progress view ──
  const total = plan.total_sessions || plan.sessions.length;
  const doneCount = Math.min(total, Math.floor((progressPct / 100) * total));
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

  const resumeSessionNumber = currentSessionNumber ?? resume?.current_session_number ?? null;
  // "Started" = real progress, or any produced session artifact (slides/lab/
  // problem-set/remediation). Until then the CTA reads START COURSE and drops
  // the student into the first session; afterwards it becomes RESUME SESSION.
  const hasStarted = progressPct > 0 || (resume?.timeline?.length ?? 0) > 0;
  const goToCurrent = () => {
    if (resumeSessionNumber) navigate(`/course/${courseId}/session/${resumeSessionNumber}`);
  };

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

            <button onClick={goToCurrent} disabled={!resumeSessionNumber} className="btn btn-red pai-pw-noprint" style={{ marginTop: 24, width: "100%", justifyContent: "space-between", padding: "18px 22px", opacity: resumeSessionNumber ? 1 : 0.6 }}>
              {isComplete ? "REVIEW COURSE" : hasStarted ? "RESUME SESSION" : "START COURSE"} <span>→</span>
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
                {plan.sessions.map((s, i) => (
                  <SessionRow 
                    key={s.session_number} 
                    session={s} 
                    status={statusForP(i)} 
                    timeline={timelineBySession.get(s.session_number) || []}
                    courseId={courseId!}
                    navigate={navigate}
                    openKey={openKey}
                    entryLoading={entryLoading}
                    reviewChunks={reviewChunks}
                    psHistory={psHistory}
                    artifact={artifact}
                    onToggleEntry={toggleEntry}
                    keyFor={keyFor}
                  />
                ))}
              </div>
            </div>

            <div style={{ marginTop: 24 }} className="pai-pw-noprint">
              <CapstoneStartCTA courseId={Number(courseId)} variant="banner" locked={!isComplete} />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

function TimelineRow({ e, courseId, navigate, open, loading, reviewChunks, psHistory, artifact, onToggle }: {
  e: ResumeTimelineEntry;
  courseId: string;
  navigate: ReturnType<typeof useNavigate>;
  open: boolean;
  loading: boolean;
  reviewChunks: RemediationReview["chunks"];
  psHistory: ProblemSetHistory | null;
  artifact: Record<string, unknown> | null;
  onToggle: () => void;
}) {
  const isRem = e.type === "remediation";
  const label = e.type === "problem_set" ? "PROBLEM SET" : e.type === "lab" ? "CODING LAB" : isRem ? "REVIEW" : "SLIDES";
  const title = isRem ? "Needs review — mastery dropped"
    : e.session_number != null ? `Session ${e.session_number}` : `Lesson ${e.lesson}`;

  return (
    <div>
      <div onClick={onToggle} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderLeft: `3px solid ${isRem ? "var(--accent-warm)" : "var(--hairline)"}`, borderRadius: 8, cursor: "pointer" }}>
        <span className="t-label" style={{ color: isRem ? "var(--accent-warm)" : "var(--text-secondary)", width: 92, flexShrink: 0 }}>{label}</span>
        <span className="t-body" style={{ flex: 1, fontSize: 14, color: "var(--text-primary)" }}>{title}</span>
        {e.type === "problem_set" && e.best_score != null && (
          <span className="t-mono" style={{ color: "var(--text-primary)" }}>{e.best_score}/100</span>
        )}
        <span className="t-mono steel" style={{ textTransform: "uppercase" }}>{e.status}</span>
        <span className="t-mono steel">{open ? "▲" : "▼"}</span>
      </div>

      {open && (
        <div style={{ padding: "14px 16px", marginLeft: 16, borderLeft: "2px solid var(--hairline)" }}>
          {loading ? <span className="t-mono steel">LOADING…</span> : (
            <>
              {isRem && (reviewChunks.length === 0
                ? <span className="t-mono steel">NO REVIEW MATERIAL FOUND.</span>
                : reviewChunks.map((c) => <p key={c.chunk_id} className="t-body" style={{ fontSize: 13, color: "var(--text-secondary)", margin: "4px 0" }}>• {c.raw_text.slice(0, 220)}</p>))}

              {e.type === "problem_set" && (psHistory == null
                ? <span className="t-mono steel">COULD NOT LOAD HISTORY.</span>
                : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div className="t-mono" style={{ color: "var(--accent-primary)" }}>
                      BEST {psHistory.best_score ?? "—"}/100 · {psHistory.attempts.length} ATTEMPT{psHistory.attempts.length === 1 ? "" : "S"}
                    </div>
                    {psHistory.attempts.length === 0 ? <span className="t-mono steel">NO ATTEMPTS YET.</span>
                      : psHistory.attempts.map((a) => (
                        <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 14, paddingTop: 8, borderTop: "1px solid var(--hairline)" }}>
                          <span className="t-mono" style={{ color: a.score >= 70 ? "var(--accent-success)" : "var(--text-primary)", minWidth: 56 }}>{a.score}/100</span>
                          <span className="t-mono steel" style={{ flex: 1 }}>{a.hints_used} HINT{a.hints_used === 1 ? "" : "S"} · {a.source}</span>
                          <span className="t-mono steel">{new Date(a.created_at).toLocaleDateString()}</span>
                        </div>
                      ))}
                    {e.session_number != null && (
                      <button onClick={() => navigate(`/course/${courseId}/session/${e.session_number}/problem-set`)} className="btn btn-ghost-dark" style={{ alignSelf: "flex-start", marginTop: 4 }}>OPEN PROBLEM SET →</button>
                    )}
                  </div>
                ))}

              {(e.type === "slides" || e.type === "lab") && (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <ArtifactSummary type={e.type} content={artifact} />
                  {e.session_number != null && (
                    <button onClick={() => navigate(`/course/${courseId}/session/${e.session_number}${e.type === "lab" ? "/lab" : ""}`)} className="btn btn-ghost-dark" style={{ alignSelf: "flex-start", marginTop: 4 }}>OPEN IN SESSION →</button>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ArtifactSummary({ type, content }: { type: string; content: Record<string, unknown> | null }) {
  if (content == null) return <span className="t-mono steel">COULD NOT LOAD CONTENT.</span>;
  // content may be the artifact wrapper ({content_json: {...}}) or the body itself.
  const cj = (content.content_json ?? content) as Record<string, unknown>;
  if (type === "slides") {
    const slides = Array.isArray(cj.slides) ? (cj.slides as Array<Record<string, unknown>>) : [];
    if (slides.length === 0) return <span className="t-mono steel">NO SLIDE CONTENT.</span>;
    return (
      <div>
        <div className="t-mono steel" style={{ marginBottom: 6 }}>{slides.length} SLIDES</div>
        <ol style={{ margin: 0, paddingLeft: 18 }}>
          {slides.slice(0, 12).map((s, i) => (
            <li key={i} className="t-body" style={{ fontSize: 13, color: "var(--text-secondary)", margin: "2px 0" }}>{String(s.title ?? s.slide_title ?? `Slide ${i + 1}`)}</li>
          ))}
        </ol>
      </div>
    );
  }
  let problem = "";
  if (cj.lab && typeof cj.lab === "object") {
    const labObj = cj.lab as Record<string, unknown>;
    problem = String(labObj.title ?? labObj.intro ?? "");
  } else {
    problem = String(cj.problem_text ?? cj.problem ?? cj.title ?? "");
  }

  return problem
    ? <p className="t-body" style={{ fontSize: 13, color: "var(--text-secondary)", margin: 0, whiteSpace: "pre-wrap" }}>{problem.slice(0, 320)}</p>
    : <span className="t-mono steel">NO LAB CONTENT.</span>;
}

function SessionRow({ 
  session, 
  status,
  timeline,
  courseId,
  navigate,
  openKey,
  entryLoading,
  reviewChunks,
  psHistory,
  artifact,
  onToggleEntry,
  keyFor
}: { 
  session: PathwaySession; 
  status: SessionStatus;
  timeline: ResumeTimelineEntry[];
  courseId: string;
  navigate: ReturnType<typeof useNavigate>;
  openKey: string | null;
  entryLoading: boolean;
  reviewChunks: RemediationReview["chunks"];
  psHistory: ProblemSetHistory | null;
  artifact: Record<string, unknown> | null;
  onToggleEntry: (e: ResumeTimelineEntry, k: string) => void;
  keyFor: (e: ResumeTimelineEntry, i: number) => string;
}) {
  const [expanded, setExpanded] = useState(false);
  const isClickable = (status === "done" || status === "current") && timeline.length > 0;

  const extra = session.topics_covered.length - 5;
  const leftBorder = status === "done" ? "3px solid var(--accent-success)" : status === "current" ? "3px solid var(--accent-primary)" : "1px solid var(--hairline)";
  const numColor = status === "done" ? "var(--accent-success)" : status === "locked" ? "var(--steel-light)" : "var(--accent-primary)";

  const tag =
    status === "done" ? { label: "✓ MASTERED", color: "var(--accent-success)" }
      : status === "current" ? { label: "CURRENT", color: "var(--accent-primary)" }
        : { label: "🔒 LOCKED", color: "var(--steel-light)" };

  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderLeft: leftBorder, borderRadius: 8, display: "flex", flexDirection: "column", opacity: status === "locked" ? 0.7 : 1 }}>
      <div 
        onClick={() => isClickable && setExpanded(!expanded)}
        style={{ padding: 24, display: "flex", gap: 22, cursor: isClickable ? "pointer" : "default" }}
      >
        <div className="t-display" style={{ fontSize: "clamp(34px,5vw,52px)", color: numColor, lineHeight: 0.9, flexShrink: 0, minWidth: 52 }}>{String(session.session_number).padStart(2, "0")}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "baseline" }}>
            <div className="t-heading" style={{ fontSize: "clamp(18px,2.4vw,24px)", color: "var(--text-primary)" }}>{session.session_title}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span className="t-label" style={{ color: tag.color, border: `1px solid ${tag.color}`, padding: "4px 8px", borderRadius: 6, flexShrink: 0 }}>{tag.label}</span>
              {isClickable && (
                <span className="t-mono steel" style={{ fontSize: 16 }}>{expanded ? "▲" : "▼"}</span>
              )}
            </div>
          </div>

        {session.topics_covered.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12 }}>
            {session.topics_covered.slice(0, 5).map((t, i) => (
              <span key={i} className="t-mono steel" style={{ fontSize: 12, border: "1px solid var(--hairline)", padding: "2px 6px", borderRadius: 4 }}>{t}</span>
            ))}
            {extra > 0 && <span className="t-mono steel" style={{ fontSize: 12, border: "1px solid var(--hairline)", padding: "2px 6px", borderRadius: 4 }}>+{extra} MORE</span>}
          </div>
        )}
      </div>
      </div>
      {expanded && timeline.length > 0 && (
        <div style={{ borderTop: "1px solid var(--hairline)", padding: "16px 24px", background: "var(--bg-primary)", borderBottomRightRadius: 8 }}>
          <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 12 }}>SESSION HISTORY</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {timeline.map((e, i) => {
              const k = keyFor(e, i);
              return (
                <TimelineRow
                  key={k} e={e} courseId={courseId} navigate={navigate}
                  open={openKey === k} loading={entryLoading}
                  reviewChunks={reviewChunks} psHistory={psHistory} artifact={artifact}
                  onToggle={() => onToggleEntry(e, k)}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
