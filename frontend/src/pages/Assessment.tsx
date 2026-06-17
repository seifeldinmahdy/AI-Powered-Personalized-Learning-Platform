import { useParams, useNavigate, useLocation } from "react-router";
import { useState, useEffect, useMemo, useCallback } from "react";
import { useAuth } from "../contexts/AuthContext";
import {
  generateCategorizedQuestions,
  submitPlacementResults,
  updatePlacementScore,
  type PlacementResult,
  type CategoryGroup,
} from "../services/assessments";
import { getCourseById } from "../services/courses";
import { TypewriterLoader } from "../components/personifai/TypewriterLoader";

/* Placement test + results — codex, full-screen focused experience.
   All logic preserved (preferences → generate-categorized → quiz →
   submit-placement → results → pathway). Everything rendered comes from the
   real PlacementResult; no fabricated percentile / week estimates / tiers. */

type Phase = "preferences" | "loading" | "quiz" | "submitting" | "results" | "error";

interface LocationState {
  enrollmentId?: number;
  courseTitle?: string;
}

const COMPOSITION = [
  { value: "visual_heavy", label: "VISUAL", desc: "Diagrams & images" },
  { value: "balanced", label: "BALANCED", desc: "A mix of both" },
  { value: "text_heavy", label: "TEXTUAL", desc: "Detailed prose" },
];
const PROFICIENCY = [
  { value: "Elementary", label: "ELEMENTARY", desc: "Basic understanding" },
  { value: "Intermediate", label: "INTERMEDIATE", desc: "Comfortable reading" },
  { value: "Advanced", label: "ADVANCED", desc: "Fluent comprehension" },
  { value: "Native", label: "NATIVE", desc: "Native speaker" },
];

const MASTERY_MESSAGE: Record<string, string> = {
  Expert: "Strong command. Your course will skip the basics and push into the hardest material.",
  Intermediate: "A solid foundation. We'll build on what you know and close the remaining gaps.",
  Novice: "A clean starting point. We'll build your foundation step by step, clearly and visually.",
};

function fmtDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m} min ${s} sec` : `${s} sec`;
}

const SHELL: React.CSSProperties = { position: "fixed", inset: 0, zIndex: 60, background: "var(--bg-primary)", color: "var(--ink-black)", overflowY: "auto" };

export default function Assessment() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const state = (location.state ?? {}) as LocationState;
  const id = Number(courseId);

  const [courseTitle, setCourseTitle] = useState(state.courseTitle ?? "");
  const [enrollmentId, setEnrollmentId] = useState<number | null>(state.enrollmentId ?? null);
  const [categories, setCategories] = useState<CategoryGroup[]>([]);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [phase, setPhase] = useState<Phase>("preferences");

  const [compositionMode, setCompositionMode] = useState("balanced");
  const [languageProficiency, setLanguageProficiency] = useState("Intermediate");

  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [showCategoryCard, setShowCategoryCard] = useState(true);

  const [placementResult, setPlacementResult] = useState<PlacementResult | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [durationSec, setDurationSec] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");

  const allQuestions = useMemo(() => categories.flatMap((c) => c.questions), [categories]);

  const currentCategory = useMemo(() => {
    if (allQuestions.length === 0) return { name: "", description: "", groupIndex: 0, isFirstInGroup: false };
    let running = 0;
    for (let gi = 0; gi < categories.length; gi++) {
      const cat = categories[gi];
      for (let qi = 0; qi < cat.questions.length; qi++) {
        if (running === currentQuestionIndex) return { name: cat.name, description: cat.description, groupIndex: gi, isFirstInGroup: qi === 0 };
        running++;
      }
    }
    return { name: "", description: "", groupIndex: 0, isFirstInGroup: false };
  }, [currentQuestionIndex, allQuestions, categories]);

  useEffect(() => {
    if (isNaN(id)) { navigate("/courses"); return; }
    if (!courseTitle) getCourseById(id).then((c) => setCourseTitle(c.title)).catch(() => setCourseTitle("Programming"));
    if (!enrollmentId) {
      import("../services/api").then(async ({ getEnrollments }) => {
        try {
          const res = await getEnrollments();
          const list = Array.isArray(res.data) ? res.data : res.data?.results || [];
          const e = list.find((e: { course: number; id: number }) => e.course === id);
          if (e) setEnrollmentId(e.id);
        } catch { /* ignore */ }
      });
    }
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (phase === "quiz" && currentCategory.isFirstInGroup) setShowCategoryCard(true);
  }, [currentQuestionIndex, phase, currentCategory.isFirstInGroup]);

  const handleStartQuiz = async () => {
    setPhase("loading");
    if (enrollmentId) {
      try {
        const { default: api } = await import("../services/api");
        await api.patch(`/courses/enrollments/${enrollmentId}/`, { is_assessment_started: true });
      } catch { /* ignore */ }
    }
    try {
      const cats = await generateCategorizedQuestions(courseTitle, String(id), 50);
      const total = cats.reduce((n, c) => n + c.questions.length, 0);
      if (total === 0) throw new Error("No questions were generated.");
      setCategories(cats);
      setCurrentQuestionIndex(0);
      setShowCategoryCard(true);
      setStartedAt(Date.now());
      setPhase("quiz");
    } catch (e) {
      console.error("Assessment generation failed:", e);
      setErrorMsg(e instanceof Error ? e.message : "Something went wrong generating your assessment.");
      setPhase("error");
    }
  };

  const handleSubmit = useCallback(async () => {
    setPhase("submitting");
    if (startedAt) setDurationSec(Math.round((Date.now() - startedAt) / 1000));
    const studentId = user?.id ?? (() => { const a = localStorage.getItem("auth_user"); return a ? JSON.parse(a).id : "0"; })();

    const answerPayload = allQuestions.map((q) => {
      const chosenIdx = answers[q.id] ?? -1;
      return {
        question_id: q.id,
        question: q.question,
        topic: q.topic || "General",
        concept_id: q.concept_id ?? null,
        chosen_option: chosenIdx >= 0 ? q.options[chosenIdx] : "",
        correct_option: q.options[q.correct],
        is_correct: chosenIdx === q.correct,
      };
    });

    try {
      const result = await submitPlacementResults({
        student_id: String(studentId),
        course_id: String(id),
        course_title: courseTitle,
        enrollment_id: enrollmentId ?? 0,
        composition_mode: compositionMode,
        language_proficiency: languageProficiency,
        answers: answerPayload,
      });
      if (enrollmentId) { try { await updatePlacementScore(enrollmentId, result.score_pct); } catch { /* non-critical */ } }
      setPlacementResult(result);
      setPhase("results");
    } catch (e) {
      console.error("Placement submission failed:", e);
      const correct = allQuestions.filter((q) => answers[q.id] === q.correct).length;
      const pct = allQuestions.length ? Math.round((correct / allQuestions.length) * 100) : 0;
      setPlacementResult({
        score_pct: pct,
        mastery_level: pct >= 70 ? "Expert" : pct >= 40 ? "Intermediate" : "Novice",
        strengths: [], weaknesses: [], topic_performance: {}, incorrectly_answered: [], context_saved: false,
      });
      setPhase("results");
    }
  }, [allQuestions, answers, compositionMode, courseTitle, enrollmentId, id, languageProficiency, startedAt, user]);

  const isLastQuestion = currentQuestionIndex === allQuestions.length - 1;
  const currentQ = allQuestions[currentQuestionIndex];
  const selectedOption = currentQ ? (answers[currentQ.id] ?? -1) : -1;

  const advance = useCallback(() => {
    if (selectedOption < 0) return;
    if (isLastQuestion) handleSubmit();
    else setCurrentQuestionIndex((i) => i + 1);
  }, [selectedOption, isLastQuestion, handleSubmit]);

  // Enter confirms the current question; A–D / 1–4 pick an option.
  useEffect(() => {
    if (phase !== "quiz" || showCategoryCard || !currentQ) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter") { e.preventDefault(); advance(); return; }
      const upper = e.key.toUpperCase();
      let idx = -1;
      if (upper >= "A" && upper <= "D") idx = upper.charCodeAt(0) - 65;
      else if (e.key >= "1" && e.key <= "9") idx = Number(e.key) - 1;
      if (idx >= 0 && idx < currentQ.options.length) setAnswers((prev) => ({ ...prev, [currentQ.id]: idx }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, showCategoryCard, currentQ, advance]);

  /* ── Top bar shared across focused phases ── */
  const TopBar = ({ right }: { right?: React.ReactNode }) => (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "26px clamp(20px,5vw,56px)" }}>
      <div style={{ display: "inline-flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 18, letterSpacing: "-0.02em", color: "#1A1611" }}>Personif<span style={{ color: "#2563EB" }}>AI</span><span style={{ color: "#2563EB" }}>.</span></span>
        <span className="t-label" style={{ color: "var(--text-secondary)" }}>· PLACEMENT</span>
      </div>
      {right}
    </div>
  );

  // ── PHASE: preferences ──
  if (phase === "preferences") {
    return (
      <div className="codex" style={SHELL}>
        <TopBar right={<button onClick={() => navigate(`/courses/${id}`)} className="t-label" style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--text-secondary)" }}>✕ EXIT</button>} />
        <div style={{ maxWidth: 720, margin: "0 auto", padding: "clamp(24px,5vh,56px) clamp(20px,5vw,40px) 64px" }}>
          <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 14 }}>BEFORE WE BEGIN</div>
          <div className="t-display" style={{ fontSize: "clamp(34px,5vw,60px)", color: "var(--text-primary)" }}>Set your preferences.</div>
          <p className="t-body" style={{ color: "var(--text-secondary)", fontSize: 16, marginTop: 16, maxWidth: 540 }}>
            These shape how {courseTitle || "this course"} is written for you. The placement test that follows maps where you are.
          </p>

          <div style={{ marginTop: 40 }}>
            <div className="t-label" style={{ color: "var(--text-primary)", marginBottom: 14 }}>HOW DO YOU PREFER TO LEARN?</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 0 }}>
              {COMPOSITION.map((opt, i) => {
                const active = compositionMode === opt.value;
                return (
                  <button key={opt.value} onClick={() => setCompositionMode(opt.value)} style={{ textAlign: "left", padding: "20px 22px", cursor: "pointer", background: active ? "var(--bg-surface)" : "transparent", border: "1px solid var(--hairline)", borderLeft: i > 0 ? "none" : "1px solid var(--hairline)", borderBottom: active ? "2px solid var(--accent-primary)" : "1px solid var(--hairline)" }}>
                    <div className="t-label" style={{ color: active ? "var(--accent-primary)" : "var(--text-primary)" }}>{opt.label}</div>
                    <div className="t-body" style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 6 }}>{opt.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div style={{ marginTop: 32 }}>
            <div className="t-label" style={{ color: "var(--text-primary)", marginBottom: 14 }}>ENGLISH PROFICIENCY</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 0 }}>
              {PROFICIENCY.map((opt, i) => {
                const active = languageProficiency === opt.value;
                return (
                  <button key={opt.value} onClick={() => setLanguageProficiency(opt.value)} style={{ textAlign: "left", padding: "16px 20px", cursor: "pointer", background: active ? "var(--bg-surface)" : "transparent", border: "1px solid var(--hairline)", borderLeft: i > 0 ? "none" : "1px solid var(--hairline)", borderBottom: active ? "2px solid var(--accent-primary)" : "1px solid var(--hairline)" }}>
                    <div className="t-label" style={{ color: active ? "var(--accent-primary)" : "var(--text-primary)" }}>{opt.label}</div>
                    <div className="t-body" style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 4 }}>{opt.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <button onClick={handleStartQuiz} className="btn btn-primary" style={{ marginTop: 40, width: "100%", justifyContent: "space-between", padding: "20px 28px" }}>
            CONTINUE TO SURVEY <span>→</span>
          </button>
        </div>
      </div>
    );
  }

  // ── PHASE: loading / submitting ──
  if (phase === "loading" || phase === "submitting") {
    const submitting = phase === "submitting";
    const messages = submitting
      ? [
          "Scoring every answer you gave…",
          "Mapping what you already know…",
          "Finding the gaps to focus on…",
          "Building your learning profile…",
        ]
      : [
          "Reading the course outcomes…",
          "Choosing questions that fit you…",
          `Tailoring the test to ${courseTitle}…`,
          "Setting up your placement test…",
        ];
    return (
      <div className="codex" style={{ ...SHELL, display: "flex" }}>
        <TypewriterLoader
          label={submitting ? "ANALYZING" : "PREPARING"}
          messages={messages}
          caption={submitting ? "This only takes a moment" : `Tailored to ${courseTitle}`}
        />
      </div>
    );
  }

  // ── PHASE: error ──
  if (phase === "error") {
    return (
      <div className="codex" style={{ ...SHELL, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 18, textAlign: "center", padding: 24 }}>
        <div className="t-label" style={{ color: "var(--error-red)" }}>GENERATION FAILED</div>
        <div className="t-display" style={{ fontSize: "clamp(28px,4vw,48px)", color: "var(--text-primary)", maxWidth: 620 }}>
          We couldn't build your assessment.
        </div>
        <p className="t-body" style={{ color: "var(--text-secondary)", fontSize: 15, maxWidth: 520 }}>
          {errorMsg ? `${errorMsg} ` : ""}The AI service may be temporarily unavailable or rate-limited. Please try again in a moment.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 8, flexWrap: "wrap", justifyContent: "center" }}>
          <button onClick={handleStartQuiz} className="btn btn-primary" style={{ padding: "16px 28px" }}>TRY AGAIN →</button>
          <button onClick={() => navigate(`/courses/${id}`)} className="btn" style={{ background: "transparent", color: "var(--steel-light)", padding: "16px 20px" }}>EXIT</button>
        </div>
      </div>
    );
  }

  // ── PHASE: results ──
  if (phase === "results" && placementResult) {
    const r = placementResult;
    const topics = Object.entries(r.topic_performance).map(([name, pct]) => ({ name, pct: Math.round(pct) })).sort((a, b) => b.pct - a.pct);
    const strengths = topics.filter((t) => t.pct >= 70);
    const develop = topics.filter((t) => t.pct < 70);
    const tiers = [
      { label: "Novice", range: "0–40" },
      { label: "Intermediate", range: "40–70" },
      { label: "Expert", range: "70–100" },
    ];
    const studentName = user?.full_name || user?.username || "";

    return (
      <div className="codex" style={SHELL}>
        <div style={{ maxWidth: 1080, margin: "0 auto", padding: "clamp(28px,4vw,48px) clamp(20px,5vw,64px) 80px" }}>
          {/* top */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <span style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 20, letterSpacing: "-0.02em", color: "#1A1611" }}>Personif<span style={{ color: "#2563EB" }}>AI</span><span style={{ color: "#2563EB" }}>.</span></span>
            <span className="t-mono steel">COMPLETED {new Date().toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" }).toUpperCase()}{durationSec > 0 ? ` · ${fmtDuration(durationSec)}` : ""}</span>
          </div>

          {/* heading + score */}
          <div style={{ marginTop: 44, display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 32, alignItems: "flex-end" }} className="as-results-head">
            <div>
              <div className="t-label" style={{ color: "var(--accent-primary)" }}>{studentName ? `${studentName.toUpperCase()} · ` : ""}YOUR PLACEMENT REPORT</div>
              <div className="t-heading" style={{ fontSize: "clamp(40px,6vw,76px)", marginTop: 16, lineHeight: 0.95, color: "var(--text-primary)", whiteSpace: "pre-line" }}>
                {r.score_pct >= 70 ? "Strong start." : r.score_pct >= 40 ? "You're closer than\nyou think." : "A clean place\nto begin."}
              </div>
              <p className="t-body" style={{ color: "var(--text-secondary)", maxWidth: 620, marginTop: 18, fontSize: 16 }}>
                {allQuestions.length} questions across {categories.length} {categories.length === 1 ? "domain" : "domains"}. Below is the picture we have of where you are today — your course is built around it.
              </p>
            </div>
            <div style={{ background: "var(--accent-soft)", color: "#fff", padding: "30px 34px", minWidth: 260, borderRadius: 8 }}>
              <div className="t-label" style={{ color: "rgba(255,255,255,0.7)" }}>OVERALL MASTERY</div>
              <div className="t-display" style={{ fontSize: "clamp(40px,6vw,64px)", marginTop: 10, lineHeight: 1, textTransform: "uppercase" }}>{r.mastery_level}</div>
              <div className="t-mono" style={{ marginTop: 14, color: "rgba(255,255,255,0.85)" }}>SCORE · {r.score_pct} / 100</div>
            </div>
          </div>

          {/* tier histogram */}
          <div style={{ marginTop: 44, display: "grid", gridTemplateColumns: "repeat(3, 1fr)", border: "1px solid var(--hairline)" }}>
            {tiers.map((tier, i) => {
              const active = tier.label.toLowerCase() === r.mastery_level.toLowerCase();
              return (
                <div key={i} style={{ padding: "20px 22px", background: active ? "var(--accent-soft)" : "transparent", color: active ? "#fff" : "var(--text-secondary)", borderRight: i < 2 ? "1px solid var(--hairline)" : "none" }}>
                  <div className="t-label" style={{ color: active ? "rgba(255,255,255,0.7)" : "var(--steel-light)" }}>{tier.range}</div>
                  <div className="t-heading" style={{ fontSize: 22, marginTop: 8, color: active ? "#fff" : "var(--text-primary)" }}>{tier.label}</div>
                </div>
              );
            })}
          </div>

          {/* per-topic breakdown (real topic_performance) */}
          {topics.length > 0 ? (
            <div style={{ marginTop: 56, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 48 }}>
              {strengths.length > 0 && <TopicGroup title="YOUR STRENGTHS" items={strengths} accent="var(--accent-warm)" />}
              {develop.length > 0 && <TopicGroup title="AREAS TO DEVELOP" items={develop} accent="var(--accent-primary)" />}
            </div>
          ) : (
            (r.strengths.length > 0 || r.weaknesses.length > 0) && (
              <div style={{ marginTop: 48, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px,1fr))", gap: 40 }}>
                <ChipGroup title="STRENGTHS" items={r.strengths} accent="var(--accent-warm)" />
                <ChipGroup title="NEEDS WORK" items={r.weaknesses} accent="var(--accent-primary)" />
              </div>
            )
          )}

          {/* methodology — real measured numbers only */}
          <div style={{ marginTop: 56, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px,1fr))", gap: 0, border: "1px solid var(--hairline)" }}>
            {[
              ["QUESTIONS ANSWERED", `${allQuestions.length}`],
              ["DOMAINS ASSESSED", `${categories.length}`],
              ["TIME TAKEN", durationSec > 0 ? fmtDuration(durationSec) : "—"],
            ].map(([label, v], i) => (
              <div key={i} style={{ padding: "22px 24px", borderRight: i < 2 ? "1px solid var(--hairline)" : "none" }}>
                <div className="t-label" style={{ color: "var(--text-secondary)" }}>{label}</div>
                <div className="t-heading" style={{ fontSize: 30, marginTop: 10, color: "var(--text-primary)" }}>{v}</div>
              </div>
            ))}
          </div>

          {/* review missed questions (real incorrectly_answered) */}
          {r.incorrectly_answered.length > 0 && (
            <details style={{ marginTop: 40 }}>
              <summary className="t-label" style={{ color: "var(--accent-primary)", cursor: "pointer" }}>WHAT TO REVIEW · {r.incorrectly_answered.length} MISSED</summary>
              <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 0, border: "1px solid var(--hairline)" }}>
                {r.incorrectly_answered.map((m, i) => (
                  <div key={i} style={{ padding: "18px 20px", borderBottom: i < r.incorrectly_answered.length - 1 ? "1px solid var(--hairline)" : "none" }}>
                    <div className="t-body" style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>{m.question}</div>
                    <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 8 }}>
                      <span className="t-mono" style={{ color: "var(--error-red)" }}>YOU · {m.chosen_option || "—"}</span>
                      <span className="t-mono" style={{ color: "var(--accent-success)" }}>CORRECT · {m.correct_option}</span>
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* mastery guidance + CTA */}
          <p className="t-body" style={{ marginTop: 40, fontSize: 15, color: "var(--text-secondary)", maxWidth: 620 }}>{MASTERY_MESSAGE[r.mastery_level] ?? ""}</p>
          <button onClick={() => navigate(`/course/${id}/pathway`, { replace: true })} className="btn btn-red" style={{ marginTop: 20, width: "100%", justifyContent: "space-between", padding: "24px 32px", fontSize: 14 }}>
            SEE YOUR PERSONALIZED PATHWAY <span>→</span>
          </button>
        </div>
        <style>{`@media (max-width: 720px){ .as-results-head { grid-template-columns: 1fr !important; } }`}</style>
      </div>
    );
  }

  // ── PHASE: quiz — category transition card ──
  if (showCategoryCard && currentCategory.isFirstInGroup) {
    return (
      <div className="codex" style={{ ...SHELL, display: "flex", flexDirection: "column" }}>
        <TopBar />
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "24px" }}>
          <div style={{ maxWidth: 620, textAlign: "center" }}>
            <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 14 }}>SECTION {currentCategory.groupIndex + 1} OF {categories.length}</div>
            <div className="t-display" style={{ fontSize: "clamp(34px,5vw,60px)", color: "var(--text-primary)" }}>{currentCategory.name}</div>
            {currentCategory.description && <p className="t-body" style={{ color: "var(--text-secondary)", fontSize: 16, marginTop: 18 }}>{currentCategory.description}</p>}
            <button onClick={() => setShowCategoryCard(false)} className="btn btn-primary" style={{ marginTop: 32, padding: "18px 32px" }}>START SECTION →</button>
          </div>
        </div>
        <QuizProgress index={currentQuestionIndex} total={allQuestions.length} category={currentCategory.name} groupIndex={currentCategory.groupIndex} groups={categories.length} />
      </div>
    );
  }

  // ── PHASE: quiz — single question ──
  const progress = allQuestions.length ? currentQuestionIndex / allQuestions.length : 0;
  return (
    <div className="codex" style={{ ...SHELL, display: "flex", flexDirection: "column" }}>
      {/* top progress line */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "rgba(15,17,23,0.08)" }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${progress * 100}%`, background: "var(--accent-primary)", transition: "width 300ms cubic-bezier(.7,0,.2,1)" }} />
      </div>

      <TopBar right={<span className="t-label" style={{ color: "var(--accent-primary)" }}>QUESTION {String(currentQuestionIndex + 1).padStart(2, "0")} OF {allQuestions.length}</span>} />

      <div style={{ flex: 1, display: "flex", justifyContent: "center", overflowY: "auto", padding: "8px 24px 24px" }}>
        <div style={{ position: "relative", width: "100%", maxWidth: 760 }}>
          {/* faded number */}
          <div className="t-display" style={{ position: "absolute", top: -40, left: -10, fontSize: "clamp(140px,22vw,300px)", color: "rgba(15,17,23,0.05)", lineHeight: 0.85, pointerEvents: "none", letterSpacing: "-0.06em", userSelect: "none" }}>{String(currentQuestionIndex + 1).padStart(2, "0")}</div>

          <div style={{ position: "relative", paddingTop: 40 }}>
            <div className="t-label" style={{ color: "var(--steel-light)", marginBottom: 14 }}>SECTION {currentCategory.groupIndex + 1} — {currentCategory.name}</div>
            <div className="t-heading" style={{ fontSize: "clamp(20px,3vw,26px)", lineHeight: 1.3, maxWidth: 640, fontWeight: 600, color: "var(--ink-black)" }}>{currentQ?.question}</div>

            <div style={{ marginTop: 32, borderTop: "1px solid var(--bg-paper-line)" }}>
              {currentQ?.options.map((opt, i) => {
                const active = selectedOption === i;
                return (
                  <div key={i} className={`opt-row${active ? " is-active" : ""}`} onClick={() => setAnswers((prev) => ({ ...prev, [currentQ.id]: i }))}>
                    <div className="opt-letter t-mono" style={{ width: 22, color: active ? "var(--accent-primary)" : "var(--steel-light)" }}>{String.fromCharCode(65 + i)}</div>
                    <div style={{ fontSize: 15, color: "var(--ink-black)", flex: 1 }}>{opt}</div>
                    {active && <span style={{ width: 8, height: 8, background: "var(--accent-primary)", marginLeft: "auto", flexShrink: 0 }} />}
                  </div>
                );
              })}
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 32, gap: 12 }}>
              <button onClick={() => { setShowCategoryCard(false); setCurrentQuestionIndex((i) => Math.max(0, i - 1)); }} disabled={currentQuestionIndex === 0} className="btn" style={{ background: "transparent", color: "var(--steel-light)", padding: "14px 0", opacity: currentQuestionIndex === 0 ? 0.4 : 1 }}>← PREVIOUS</button>
              <button onClick={advance} disabled={selectedOption < 0} className="btn btn-primary">{isLastQuestion ? "SUBMIT SURVEY →" : "NEXT QUESTION →"}</button>
            </div>
          </div>
        </div>
      </div>

      <div style={{ padding: "18px clamp(20px,5vw,56px)", display: "flex", justifyContent: "space-between", borderTop: "1px solid var(--bg-paper-line)" }}>
        <span className="t-mono steel">{allQuestions.length} questions · section {currentCategory.groupIndex + 1} of {categories.length}</span>
        <span className="t-mono steel">A–D TO SELECT · ↵ TO CONTINUE</span>
      </div>
    </div>
  );
}

function QuizProgress({ index, total, category, groupIndex, groups }: { index: number; total: number; category: string; groupIndex: number; groups: number }) {
  return (
    <div style={{ borderTop: "1px solid var(--hairline)", background: "var(--bg-surface)", padding: "16px clamp(20px,5vw,56px)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <span className="t-mono steel">SECTION {groupIndex + 1} OF {groups} — {category}</span>
        <span className="t-mono steel">QUESTION {index + 1} OF {total}</span>
      </div>
      <div className="progress"><i style={{ width: `${total ? (index / total) * 100 : 0}%` }} /></div>
    </div>
  );
}

function TopicGroup({ title, items, accent }: { title: string; items: { name: string; pct: number }[]; accent: string }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, paddingBottom: 14, borderBottom: `1px solid ${accent}`, marginBottom: 4 }}>
        <span style={{ width: 8, height: 8, background: accent }} />
        <span className="t-label" style={{ color: accent }}>{title}</span>
        <span style={{ flex: 1 }} />
        <span className="t-mono steel">{items.length} TOPIC{items.length === 1 ? "" : "S"}</span>
      </div>
      {items.map((t, i) => {
        const status = t.pct >= 75 ? "STRONG" : t.pct >= 45 ? "DEVELOPING" : "NEEDS WORK";
        const barColor = t.pct >= 75 ? "var(--accent-warm)" : "var(--accent-primary)";
        return (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "minmax(120px,1fr) 1.4fr 48px 92px", gap: 14, alignItems: "center", padding: "14px 0", borderBottom: "1px solid var(--hairline)" }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>{t.name}</div>
            <div style={{ height: 6, background: "var(--hairline)", position: "relative", borderRadius: 4 }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${t.pct}%`, background: barColor, borderRadius: 4 }} />
            </div>
            <div className="t-mono" style={{ fontSize: 13, textAlign: "right", color: "var(--text-primary)" }}>{t.pct}%</div>
            <div className="t-label" style={{ textAlign: "right", color: t.pct >= 75 ? "var(--accent-warm)" : "var(--accent-primary)" }}>{status}</div>
          </div>
        );
      })}
    </div>
  );
}

function ChipGroup({ title, items, accent }: { title: string; items: string[]; accent: string }) {
  return (
    <div>
      <div className="t-label" style={{ color: accent, marginBottom: 12 }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {items.length ? items.map((s) => (
          <span key={s} className="t-mono" style={{ color: accent, border: `1px solid ${accent}`, padding: "5px 9px", borderRadius: 4 }}>{s}</span>
        )) : <span className="t-mono steel">—</span>}
      </div>
    </div>
  );
}
