import { useParams, useNavigate, useLocation } from 'react-router';
import { useState, useEffect } from 'react';
import { CheckCircle, ChevronRight, ChevronLeft, Loader2, Trophy, SkipForward } from 'lucide-react';
import {
    generateAssessmentQuestions,
    updatePlacementScore,
    type AssessmentQuestion,
} from '../services/assessments';
import { getCourseById } from '../services/courses';

// ── helpers ───────────────────────────────────────────────────────────────────

function getTier(pct: number): { label: string; color: string; description: string } {
    if (pct >= 75) return { label: 'Advanced', color: 'text-rose-600', description: "You have strong prior knowledge. We'll skip the basics and focus on advanced topics." };
    if (pct >= 40) return { label: 'Intermediate', color: 'text-amber-600', description: "You have a solid foundation. We'll build on what you know and fill in the gaps." };
    return { label: 'Beginner', color: 'text-emerald-600', description: "We'll start from the fundamentals and guide you step by step." };
}

// ── component ─────────────────────────────────────────────────────────────────

interface LocationState {
    enrollmentId?: number;
    courseTitle?: string;
}

export default function Assessment() {
    const { courseId } = useParams<{ courseId: string }>();
    const navigate = useNavigate();
    const location = useLocation();
    const state = (location.state ?? {}) as LocationState;

    const id = Number(courseId);

    const [courseTitle, setCourseTitle] = useState(state.courseTitle ?? '');
    const [enrollmentId, setEnrollmentId] = useState<number | null>(state.enrollmentId ?? null);
    const [questions, setQuestions] = useState<AssessmentQuestion[]>([]);
    const [answers, setAnswers] = useState<Record<number, number>>({}); // questionId → chosen option index
    const [current, setCurrent] = useState(0);
    const [phase, setPhase] = useState<'loading' | 'quiz' | 'results'>('loading');
    const [saving, setSaving] = useState(false);

    // ── load questions ────────────────────────────────────────────────────────

    useEffect(() => {
        if (isNaN(id)) { navigate('/courses'); return; }

        async function load() {
            // Resolve title if not passed via state
            let topic = courseTitle;
            if (!topic) {
                try {
                    const course = await getCourseById(id);
                    topic = course.title;
                    setCourseTitle(topic);
                } catch {
                    topic = 'Programming';
                    setCourseTitle(topic);
                }
            }
            
            // Mark assessment as started
            if (enrollmentId) {
                try {
                    const { default: api } = await import('../services/api');
                    await api.patch(`/courses/enrollments/${enrollmentId}/`, { is_assessment_started: true });
                } catch { /* ignore */ }
            }

            const qs = await generateAssessmentQuestions(topic, 6);
            setQuestions(qs);
            setPhase('quiz');
        }
        load();
    }, [id, enrollmentId]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── derived ───────────────────────────────────────────────────────────────

    const totalQuestions = questions.length;
    const progressPct = totalQuestions > 0 ? Math.round(((current + 1) / totalQuestions) * 100) : 0;
    const currentQ = questions[current];
    const selectedOption = currentQ !== undefined ? (answers[currentQ.id] ?? -1) : -1;

    // ── polling state ────────────────────────────────────────────────────────
    const [pathwayReady, setPathwayReady] = useState(false);
    const [firstLessonId, setFirstLessonId] = useState<number | null>(null);

    useEffect(() => {
        if (phase !== 'results' || pathwayReady || !enrollmentId) return;

        let interval = setInterval(async () => {
            try {
                const { getEnrollments } = await import('../services/api');
                const res = await getEnrollments();
                const list = Array.isArray(res.data) ? res.data : res.data?.results || [];
                const enroll = list.find((e: any) => e.id === enrollmentId);
                
                if (enroll && enroll.is_pathway_ready) {
                    setPathwayReady(true);
                    if (enroll.current_lesson) {
                        setFirstLessonId(enroll.current_lesson);
                    }
                    clearInterval(interval);
                }
            } catch {
                // ignore
            }
        }, 3000); // pool every 3s

        return () => clearInterval(interval);
    }, [phase, pathwayReady, enrollmentId]);

    // ── handlers ──────────────────────────────────────────────────────────────

    const handleSelect = (optIdx: number) => {
        if (!currentQ) return;
        setAnswers((prev) => ({ ...prev, [currentQ.id]: optIdx }));
    };

    const handleNext = () => {
        if (current < totalQuestions - 1) {
            setCurrent((c) => c + 1);
        } else {
            finishQuiz();
        }
    };

    const handlePrev = () => {
        if (current > 0) setCurrent((c) => c - 1);
    };

    const finishQuiz = async () => {
        const correct = questions.filter((q) => answers[q.id] === q.correct).length;
        const pct = Math.round((correct / totalQuestions) * 100);

        setSaving(true);
        if (enrollmentId) {
            try {
                await updatePlacementScore(enrollmentId, pct);
            } catch { /* non-critical */ }
        }
        setSaving(false);
        setPhase('results');
    };

    const handleSkip = async () => {
        setSaving(true);
        if (enrollmentId) {
            try { await updatePlacementScore(enrollmentId, 0); } catch { /* ignore */ }
        }
        setSaving(false);
        // Go to pathway generation
        navigate(`/course/${id}/pathway`, { replace: true });
    };

    const handleBeginLearning = () => {
        if (firstLessonId) {
            navigate(`/course/${id}/lesson/${firstLessonId}`);
        } else {
            navigate(`/course/${id}/pathway`); 
        }
    };

    // ── score calculation for results ─────────────────────────────────────────

    const correctCount = questions.filter((q) => answers[q.id] === q.correct).length;
    const scorePct = totalQuestions > 0 ? Math.round((correctCount / totalQuestions) * 100) : 0;
    const tier = getTier(scorePct);

    // ── phases ────────────────────────────────────────────────────────────────

    if (phase === 'loading') {
        return (
            <div className="flex-1 flex flex-col items-center justify-center gap-4">
                <Loader2 size={40} className="animate-spin text-secondary" />
                <p className="text-muted-foreground text-sm">Preparing your assessment…</p>
            </div>
        );
    }

    if (phase === 'results') {
        return (
            <div className="flex-1 flex items-center justify-center p-6 bg-background overflow-y-auto">
                <div className="w-full max-w-md">
                    <div className="bg-card rounded-2xl border border-border shadow-lg p-8 text-center space-y-6">
                        {/* Trophy icon */}
                        <div className="flex justify-center">
                            <div className="w-20 h-20 rounded-full bg-gradient-to-br from-secondary to-accent flex items-center justify-center">
                                <Trophy size={36} className="text-white" />
                            </div>
                        </div>

                        <div>
                            <h1 className="text-2xl font-bold mb-1">Assessment Complete!</h1>
                            <p className="text-muted-foreground text-sm">{courseTitle}</p>
                        </div>

                        {/* Score */}
                        <div className="bg-muted rounded-xl p-5 space-y-2">
                            <div className="text-5xl font-bold text-foreground">{scorePct}%</div>
                            <div className="text-sm text-muted-foreground">{correctCount} / {totalQuestions} correct</div>

                            {/* Score bar */}
                            <div className="h-2 bg-border rounded-full overflow-hidden mt-3">
                                <div
                                    className="h-full rounded-full bg-gradient-to-r from-secondary to-accent transition-all duration-700"
                                    style={{ width: `${scorePct}%` }}
                                />
                            </div>
                        </div>

                        {/* Tier */}
                        <div className="space-y-1">
                            <p className="text-sm text-muted-foreground">Your knowledge level</p>
                            <p className={`text-2xl font-bold ${tier.color}`}>{tier.label}</p>
                            <p className="text-sm text-muted-foreground leading-relaxed">{tier.description}</p>
                        </div>

                        {/* CTA */}
                        {pathwayReady ? (
                            <button
                                onClick={handleBeginLearning}
                                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold text-sm hover:shadow-lg transition-all"
                            >
                                Begin Learning <ChevronRight size={16} />
                            </button>
                        ) : (
                            <button
                                disabled
                                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold text-sm opacity-60"
                            >
                                <Loader2 size={16} className="animate-spin" /> Preparing your pathway...
                            </button>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    // ── quiz phase ────────────────────────────────────────────────────────────

    return (
        <div className="flex-1 flex flex-col bg-background overflow-y-auto">
            {/* Progress header */}
            <div className="bg-card border-b border-border px-6 py-4">
                <div className="max-w-2xl mx-auto">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-medium text-foreground">
                            Question {current + 1} <span className="text-muted-foreground">of {totalQuestions}</span>
                        </span>
                        <span className="text-sm text-muted-foreground">{progressPct}% complete</span>
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                        <div
                            className="h-full rounded-full bg-gradient-to-r from-secondary to-accent transition-all duration-300"
                            style={{ width: `${progressPct}%` }}
                        />
                    </div>
                    {courseTitle && (
                        <p className="text-xs text-muted-foreground mt-1.5">Placement Assessment · {courseTitle}</p>
                    )}
                </div>
            </div>

            {/* Question area */}
            <div className="flex-1 flex items-center justify-center p-6">
                <div className="w-full max-w-2xl space-y-6">
                    {/* Question card */}
                    <div className="bg-card rounded-2xl border border-border shadow-sm p-6 md:p-8">
                        <p className="text-base md:text-lg font-semibold text-foreground leading-relaxed mb-6">
                            {currentQ?.question}
                        </p>

                        {/* Options */}
                        <div className="space-y-3">
                            {currentQ?.options.map((opt, idx) => {
                                const isSelected = selectedOption === idx;
                                return (
                                    <button
                                        key={idx}
                                        onClick={() => handleSelect(idx)}
                                        className={`w-full text-left flex items-center gap-3 px-4 py-3.5 rounded-xl border transition-all text-sm font-medium ${
                                            isSelected
                                                ? 'border-secondary bg-secondary/10 text-secondary'
                                                : 'border-border bg-background hover:bg-muted/50 text-foreground'
                                        }`}
                                    >
                                        <span
                                            className={`w-6 h-6 shrink-0 rounded-full flex items-center justify-center text-xs font-bold border transition-colors ${
                                                isSelected
                                                    ? 'bg-secondary border-secondary text-white'
                                                    : 'border-border text-muted-foreground'
                                            }`}
                                        >
                                            {isSelected ? <CheckCircle size={14} /> : String.fromCharCode(65 + idx)}
                                        </span>
                                        {opt}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Navigation */}
                    <div className="flex items-center justify-between">
                        <button
                            onClick={handlePrev}
                            disabled={current === 0}
                            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border bg-card text-sm font-medium text-foreground hover:bg-muted transition-colors disabled:opacity-40 disabled:pointer-events-none"
                        >
                            <ChevronLeft size={16} /> Previous
                        </button>

                        <button
                            onClick={handleNext}
                            disabled={selectedOption === -1 || saving}
                            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-secondary to-accent text-white text-sm font-semibold hover:shadow-lg transition-all disabled:opacity-40 disabled:pointer-events-none"
                        >
                            {saving ? (
                                <><Loader2 size={14} className="animate-spin" /> Saving…</>
                            ) : current === totalQuestions - 1 ? (
                                <>Finish <CheckCircle size={16} /></>
                            ) : (
                                <>Next <ChevronRight size={16} /></>
                            )}
                        </button>
                    </div>

                    {/* Skip link */}
                    <div className="text-center">
                        <button
                            onClick={handleSkip}
                            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                            <SkipForward size={13} />
                            Skip assessment and start from the beginning
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
