import { useState, useEffect, useMemo } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router';
import Editor from '@monaco-editor/react';
import { toast } from 'sonner';
import {
    generateProblemSet,
    regenerateProblemSet,
    getStudentProblemSets,
    getRegenerationCount,
    getProblemSetBestScore,
    getProblemSet,
    submitAnswer,
    getDynamicHint,
    notifySummaryViewed,
    type ProblemSetData,
    type ProblemSetQuestion,
    type EvaluationResult,
    type RubricScore,
    type RubricCriterion,
    type RubricCheck,
} from '../../services/problemSet';
import { getCurrentPathway } from '../../services/pathway';
import {
    Loader2, Sparkles, Send, CheckCircle2, XCircle, BookOpen,
    Lightbulb, ChevronDown, ChevronUp, ArrowLeft, ArrowRight, Trophy,
    AlertTriangle, Eye, Code2, BarChart3, SkipForward,
} from 'lucide-react';
import { CapstoneStartCTA } from '../../components/CapstoneStartCTA';

/* ── design tokens (personifai / codex) ──────────────────────
   The system is deliberately two-tone for outcomes: pass = green
   (--accent-success), needs-work = red (--error-red); blue
   (--accent-primary) marks the active/current element. */

const PASS = 70;

function scoreColor(s: number) {
    return s >= PASS ? 'var(--accent-success)' : 'var(--error-red)';
}
function scoreTint(s: number) {
    return s >= PASS ? 'rgba(22,163,74,0.08)' : 'rgba(220,38,38,0.07)';
}
/* earned vs max → full green, zero red, partial neutral. */
function rubricColor(earned: number, max: number) {
    if (max > 0 && earned >= max) return 'var(--accent-success)';
    if (earned <= 0) return 'var(--error-red)';
    return 'var(--text-secondary)';
}

function getStudentId(): string {
    try {
        const u = localStorage.getItem('auth_user');
        if (!u) return 'anonymous';
        return String(JSON.parse(u).id ?? 'anonymous');
    } catch { return 'anonymous'; }
}

interface LocationState {
    sessionId?: string;
    courseId?: string;
    lessonTitle?: string;
    sessionTitle?: string;
    studentProfileSummary?: string;
    nextLessonId?: number | string | null;
    nextSessionId?: number | string | null;
    slides?: { title: string; content: string; code?: string }[];
    labCells?: { id: string; cell_type: string; title: string; narrative?: string; code?: string; starter_code?: string; task_prompt?: string }[];
}

/* ── component ───────────────────────────────────────────── */

export default function ProblemSet() {
    const { courseId, sessionNumber } = useParams<{ courseId: string; sessionNumber: string }>();
    const location = useLocation();
    const navigate = useNavigate();
    const locState = (location.state as LocationState) ?? {};
    const studentId = getStudentId();

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [problemSet, setProblemSet] = useState<ProblemSetData | null>(null);
    const [currentIdx, setCurrentIdx] = useState(0);

    // Per-question local state
    const [codeMap, setCodeMap] = useState<Record<string, string>>({});
    const [results, setResults] = useState<Record<string, EvaluationResult>>({});
    const [solutionShown, setSolutionShown] = useState<Record<string, boolean>>({});
    const [submitting, setSubmitting] = useState(false);
    const [expandedSummary, setExpandedSummary] = useState<string | null>(null);
    const [regenerating, setRegenerating] = useState(false);

    // Plan version pins the regenerate cap + best-score scope (server-tracked).
    const [planVersion, setPlanVersion] = useState<number | null>(null);
    const [regenInfo, setRegenInfo] = useState<{ remaining: number; max: number } | null>(null);
    const [bestScore, setBestScore] = useState<number | null>(null);

    // New hint system state
    const [staticHintExpanded, setStaticHintExpanded] = useState<Record<string, boolean>>({});
    const [dynamicHints, setDynamicHints] = useState<Record<string, { hint_number: number; content: string; penalty: number }[]>>({});
    const [hintLoading, setHintLoading] = useState(false);
    const [confirmSmartHint, setConfirmSmartHint] = useState(false);
    const [expandedCriterion, setExpandedCriterion] = useState<string | null>(null);

    const questions = useMemo(() => problemSet?.questions ?? [], [problemSet]);
    const current = questions[currentIdx] as ProblemSetQuestion | undefined;
    const allDone = questions.length > 0 && questions.every(q => !!results[q.id] || !!problemSet?.submissions?.[q.id]);
    const showSummary = allDone && currentIdx >= questions.length;

    /* ── server-tracked best score + remaining regenerations ──
       Both endpoints already exist; the page reads them so the
       regenerate button shows the live cap and the summary shows
       the best-ever score (a weaker retry never lowers it). */
    async function refreshMeta(pv: number | null) {
        if (!courseId || !sessionNumber) return;
        try {
            const best = await getProblemSetBestScore(courseId, sessionNumber, pv ?? undefined);
            setBestScore(best);
        } catch { /* best score is optional UI sugar */ }
        if (pv != null) {
            try {
                const r = await getRegenerationCount(courseId, sessionNumber, pv);
                setRegenInfo({ remaining: r.remaining, max: r.max });
            } catch { /* regen cap falls back to static copy */ }
        }
    }

    // Resolve the authoritative plan version, then pull regen cap + best score.
    useEffect(() => {
        if (!courseId || !sessionNumber) return;
        (async () => {
            try {
                const plan = await getCurrentPathway(courseId);
                setPlanVersion(plan.plan_version);
                await refreshMeta(plan.plan_version);
            } catch {
                // No pathway yet (rare on this route) — best score still works unscoped.
                await refreshMeta(null);
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [courseId, sessionNumber, studentId]);

    // Fire once when summary screen mounts. This is the genuine end of the
    // session: the server completes the session (XP/streak/progress) and runs the
    // concept-mastery profiler. Achievement toasts surface from the response.
    useEffect(() => {
        if (showSummary && problemSet?.problem_set_id && studentId && sessionNumber) {
            notifySummaryViewed({
                problemSetId: problemSet.problem_set_id,
                studentId,
                sessionNumber,
            })
                .then(res => {
                    for (const ach of res.newly_earned_achievements ?? []) {
                        toast.success(`${ach.icon_url} Achievement unlocked: ${ach.name} (+${ach.xp_reward} XP)`);
                    }
                })
                .catch(err =>
                    console.warn('Summary viewed notification failed:', err)
                );
            // Best score may have just advanced with this attempt.
            refreshMeta(planVersion);
        }
    }, [showSummary]);  // eslint-disable-line react-hooks/exhaustive-deps

    /* ── load / generate ───────────────────────────────────── */

    useEffect(() => {
        (async () => {
            if (!courseId || !sessionNumber) { setError('Missing route params'); setLoading(false); return; }
            try {
                const existing = await getStudentProblemSets(studentId, sessionNumber);
                // Only use problem sets that have questions (skip empty/failed ones)
                const validSets = existing.filter(ps => ps.questions && ps.questions.length > 0);
                if (validSets.length > 0) {
                    const ps_meta = validSets[validSets.length - 1];
                    const ps = await getProblemSet(ps_meta.problem_set_id || (ps_meta as any).ps_uid, studentId);
                    setProblemSet(ps);
                    // Restore results from submissions
                    const restoredResults: Record<string, EvaluationResult> = {};
                    for (const [qid, sub] of Object.entries(ps.submissions || {})) {
                        restoredResults[qid] = sub.result;
                    }
                    setResults(restoredResults);
                    // Find first unanswered
                    const firstUnanswered = ps.questions.findIndex(q => !ps.submissions?.[q.id]);
                    setCurrentIdx(firstUnanswered >= 0 ? firstUnanswered : ps.questions.length);
                    // Restore starter code
                    const codes: Record<string, string> = {};
                    for (const q of ps.questions) {
                        codes[q.id] = ps.submissions?.[q.id]?.code ?? q.starter_code;
                    }
                    setCodeMap(codes);
                } else {
                    const ps = await generateProblemSet({
                        sessionId: locState.sessionId || '',
                        studentId,
                        courseId,
                        sessionNumber,
                        sessionTitle: locState.sessionTitle || '',
                        studentProfileSummary: locState.studentProfileSummary || '',
                        slides: locState.slides || [],
                        labCells: locState.labCells || [],
                    });
                    setProblemSet(ps);
                    const codes: Record<string, string> = {};
                    for (const q of ps.questions) codes[q.id] = q.starter_code;
                    setCodeMap(codes);
                }
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to load problem set');
            } finally {
                setLoading(false);
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [courseId, sessionNumber]);

    /* ── handlers ──────────────────────────────────────────── */

    async function handleRegenerate() {
        if (!courseId || !sessionNumber || regenerating) return;
        if (regenInfo && regenInfo.remaining <= 0) {
            toast.error('No regenerations left for this session.');
            return;
        }
        setRegenerating(true);
        try {
            // The cap (MAX 3 / plan_version) is enforced server-side; a 409
            // surfaces as the thrown message below.
            const fresh = await regenerateProblemSet({
                sessionId: locState.sessionId || '',
                studentId, courseId, sessionNumber,
                sessionTitle: locState.sessionTitle || '',
                studentProfileSummary: locState.studentProfileSummary || '',
                slides: locState.slides || [],
                labCells: locState.labCells || [],
            });
            // Swap in the new generation and restart the set.
            setProblemSet(fresh);
            setResults({});
            setSolutionShown({});
            setExpandedSummary(null);
            const codes: Record<string, string> = {};
            for (const q of fresh.questions) codes[q.id] = q.starter_code;
            setCodeMap(codes);
            setCurrentIdx(0);
            toast.success('Fresh problem set generated.');
            // Reflect the consumed regeneration in the live counter.
            refreshMeta(planVersion);
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Could not regenerate.');
        } finally {
            setRegenerating(false);
        }
    }

    function toggleStaticHint(qid: string) {
        setStaticHintExpanded(p => ({ ...p, [qid]: !p[qid] }));
    }

    async function requestDynamicHint(hintNum: 2 | 3) {
        if (!current || !problemSet) return;
        setHintLoading(true);
        setConfirmSmartHint(false);
        try {
            const existingResult = results[current.id];
            const res = await getDynamicHint({
                problemSetId: problemSet.problem_set_id,
                questionId: current.id,
                studentId: studentId,
                sessionNumber: sessionNumber as string,
                currentCode: codeMap[current.id] || '',
                hintNumber: hintNum,
                evaluatedRubric: existingResult && !existingResult.passed
                    ? (current.rubric as any[]) // pass rubric if failed submission exists
                    : null,
            });
            setDynamicHints(p => ({
                ...p,
                [current.id]: [
                    ...(p[current.id] || []),
                    { hint_number: hintNum, content: res.hint_content, penalty: res.penalty_applied },
                ],
            }));
            toast.info(`−${res.penalty_applied.toFixed(1)} pts deducted from the relevant rubric section`);
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to get hint');
        } finally {
            setHintLoading(false);
        }
    }

    async function handleSubmit() {
        if (!current || !problemSet) return;
        const code = codeMap[current.id] || '';
        if (!code.trim()) { toast.error('Write code before submitting.'); return; }
        if (code.trim() === (current.starter_code || '').trim()) { toast.error('Modify the starter code first.'); return; }

        setSubmitting(true);
        try {
            const result = await submitAnswer(
                problemSet.problem_set_id,
                current.id,
                studentId,
                code,
                current.language || 'python',
                0, // hints_used legacy field
            );
            setResults(p => ({ ...p, [current.id]: result }));
            if (result.passed) toast.success(`Passed with ${result.final_score}/100!`);
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Submission failed');
        } finally {
            setSubmitting(false);
        }
    }

    function goNext() {
        if (currentIdx < questions.length - 1) setCurrentIdx(i => i + 1);
        else setCurrentIdx(questions.length); // summary
    }

    function skipQuestion() {
        // Move to next unanswered question, wrapping around; if all answered, go to summary
        for (let offset = 1; offset <= questions.length; offset++) {
            const idx = (currentIdx + offset) % questions.length;
            const q = questions[idx];
            if (!results[q.id] && !problemSet?.submissions?.[q.id]) {
                setCurrentIdx(idx);
                return;
            }
        }
        // All answered — go to summary
        setCurrentIdx(questions.length);
    }

    function showSolutionForQuestion(qid: string) {
        setSolutionShown(p => ({ ...p, [qid]: true }));
    }

    /* ── loading / error states ────────────────────────────── */

    if (loading) {
        return (
            <div className="codex" style={{ flex: 1, minHeight: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 18, background: 'var(--bg-primary)', textAlign: 'center', padding: 24 }}>
                <Loader2 size={34} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
                <div className="t-heading" style={{ fontSize: 24, color: 'var(--text-primary)' }}>Crafting your problem set…</div>
                <div className="t-mono steel">Analyzing your session and tailoring questions</div>
            </div>
        );
    }

    if (error || !problemSet || questions.length === 0) {
        return (
            <div className="codex" style={{ flex: 1, minHeight: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, background: 'var(--bg-primary)', textAlign: 'center', padding: 24 }}>
                <div className="t-label" style={{ color: 'var(--error-red)', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <AlertTriangle size={15} /> PROBLEM SET UNAVAILABLE
                </div>
                <div className="t-heading" style={{ fontSize: 22, color: 'var(--text-primary)', maxWidth: 460 }}>{error || 'No questions generated'}</div>
                <button onClick={() => navigate(-1)} className="btn btn-ghost-dark">← GO BACK</button>
            </div>
        );
    }

    /* ── summary screen ────────────────────────────────────── */

    if (showSummary) {
        const scores = questions.map(q => {
            const r = results[q.id] ?? problemSet.submissions?.[q.id]?.result;
            return r?.final_score ?? 0;
        });
        const avg = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
        const best = bestScore != null ? Math.max(bestScore, avg) : avg;
        const regenOut = regenInfo ? regenInfo.remaining <= 0 : false;

        return (
            <div className="codex" style={{ flex: 1, minHeight: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '0 24px', height: 56, borderBottom: '1px solid var(--hairline)', background: 'var(--bg-primary)' }}>
                    <button onClick={() => navigate(-1)} className="t-label" style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <ArrowLeft size={15} /> BACK
                    </button>
                    <span style={{ flex: 1 }} />
                    <span className="t-label" style={{ color: 'var(--accent-primary)' }}>PROBLEM SET · COMPLETE</span>
                </div>

                <div style={{ flex: 1, overflowY: 'auto', padding: 'clamp(24px,4vw,48px)', maxWidth: 820, marginInline: 'auto', width: '100%' }}>
                    {/* Overall score */}
                    <div className="t-label" style={{ color: 'var(--steel-light)' }}>YOUR SCORE</div>
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 28, flexWrap: 'wrap', marginTop: 10 }}>
                        <div className="t-display" style={{ fontSize: 'clamp(88px,16vw,150px)', lineHeight: 0.9, color: scoreColor(avg) }}>
                            {avg}<span className="steel" style={{ fontSize: '0.32em' }}>/100</span>
                        </div>
                        <div style={{ paddingBottom: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <div>
                                <div className="t-label" style={{ color: 'var(--text-secondary)' }}>BEST EVER</div>
                                <div className="t-heading" style={{ fontSize: 30, color: scoreColor(best), marginTop: 4 }}>{best}<span className="steel" style={{ fontSize: 15 }}>/100</span></div>
                            </div>
                            <div className="t-mono steel">{questions.length} QUESTIONS COMPLETED</div>
                        </div>
                    </div>

                    {/* Per-question summary */}
                    <div style={{ marginTop: 36, display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {questions.map((q, idx) => {
                            const r = results[q.id] ?? problemSet.submissions?.[q.id]?.result;
                            const fs = r?.final_score ?? 0;
                            const passed = r?.passed ?? false;
                            const isOpen = expandedSummary === q.id;
                            const sub = problemSet.submissions?.[q.id];
                            const exSolution = r?.example_solution || q.example_solution;

                            return (
                                <div key={q.id} style={{ background: 'var(--bg-surface)', border: '1px solid var(--hairline)', borderLeft: `3px solid ${scoreColor(fs)}`, borderRadius: 8, overflow: 'hidden' }}>
                                    <button
                                        onClick={() => setExpandedSummary(isOpen ? null : q.id)}
                                        style={{ width: '100%', padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 14, background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' }}
                                    >
                                        <span style={{ width: 20, height: 20, borderRadius: 6, flexShrink: 0, background: scoreColor(fs), color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>
                                            {passed ? '✓' : '✕'}
                                        </span>
                                        <span className="t-mono steel" style={{ width: 28 }}>Q{idx + 1}</span>
                                        <span style={{ flex: 1, fontSize: 14, fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{q.title}</span>
                                        <span className="t-mono" style={{ fontWeight: 700, color: scoreColor(fs) }}>{fs}/100</span>
                                        {isOpen ? <ChevronUp size={14} style={{ color: 'var(--steel-light)' }} /> : <ChevronDown size={14} style={{ color: 'var(--steel-light)' }} />}
                                    </button>
                                    {isOpen && (
                                        <div style={{ padding: '16px 18px', borderTop: '1px solid var(--hairline)', display: 'flex', flexDirection: 'column', gap: 14 }}>
                                            {r?.feedback && <p className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)' }}>{r.feedback}</p>}
                                            {r?.rubric_scores && r.rubric_scores.length > 0 && (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                    <div className="t-label" style={{ color: 'var(--text-secondary)' }}>RUBRIC BREAKDOWN</div>
                                                    {r.rubric_scores.map((rs: RubricScore, i: number) => {
                                                        const pct = rs.max > 0 ? Math.round((rs.earned / rs.max) * 100) : 0;
                                                        const c = rubricColor(rs.earned, rs.max);
                                                        return (
                                                            <div key={`${rs.criterion}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
                                                                <span style={{ width: 110, color: 'var(--text-primary)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{rs.criterion}</span>
                                                                <div style={{ flex: 1, height: 6, background: 'var(--bg-paper-line)', borderRadius: 4, overflow: 'hidden' }}>
                                                                    <div style={{ height: '100%', width: `${pct}%`, background: c }} />
                                                                </div>
                                                                <span className="t-mono" style={{ width: 52, textAlign: 'right', fontWeight: 700, color: c }}>{rs.earned}/{rs.max}</span>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                            {/* Your Code vs Possible Answer */}
                                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                                                {sub?.code && (
                                                    <div>
                                                        <div className="t-label" style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>YOUR CODE</div>
                                                        <pre className="codeblock" style={{ maxHeight: 192, overflow: 'auto', margin: 0 }}><code>{sub.code}</code></pre>
                                                    </div>
                                                )}
                                                {exSolution && (
                                                    <div>
                                                        <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 6 }}>POSSIBLE ANSWER</div>
                                                        <pre className="codeblock" style={{ maxHeight: 192, overflow: 'auto', margin: 0, border: '1px solid rgba(37,99,235,0.3)' }}><code>{exSolution}</code></pre>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    {/* Retry with a fresh variant. Best score is the max across
                        all attempts/generations, so a weaker retry never lowers it;
                        regenerated attempts contribute to mastery with reduced weight. */}
                    <button
                        onClick={handleRegenerate}
                        disabled={regenerating || regenOut}
                        className="btn btn-ghost-dark"
                        style={{ marginTop: 32, width: '100%', justifyContent: 'center' }}
                    >
                        {regenerating
                            ? 'GENERATING A FRESH SET…'
                            : regenInfo
                                ? regenOut
                                    ? 'NO REGENERATIONS LEFT'
                                    : `REGENERATE · ${regenInfo.remaining} OF ${regenInfo.max} LEFT`
                                : 'REGENERATE PROBLEM SET (UP TO 3)'}
                    </button>

                    {locState.nextSessionId ? (
                        <button
                            onClick={() => navigate(`/course/${courseId}/session/${locState.nextSessionId}`)}
                            className="btn btn-paper"
                            style={{ marginTop: 16, width: '100%', justifyContent: 'center' }}
                        >
                            CONTINUE TO NEXT SESSION <ArrowRight size={16} />
                        </button>
                    ) : (
                        <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
                            {/* Course finished — terminal gate is the capstone */}
                            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--hairline)', borderLeft: '4px solid var(--accent-warm)', borderRadius: 8, padding: '24px 26px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
                                <Trophy size={26} style={{ color: 'var(--accent-warm)' }} />
                                <div>
                                    <div className="t-heading" style={{ fontSize: 19, color: 'var(--text-primary)' }}>You've finished the coursework.</div>
                                    <div className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>One final step: complete your capstone project.</div>
                                </div>
                                <CapstoneStartCTA courseId={Number(courseId)} variant="inline" />
                            </div>
                            <button
                                onClick={() => navigate(`/courses/${courseId}`)}
                                className="btn btn-ghost-dark"
                                style={{ width: '100%', justifyContent: 'center' }}
                            >
                                ← BACK TO COURSE
                            </button>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    /* ── question view ─────────────────────────────────────── */

    const isSubmitted = !!results[current!.id];
    const result = results[current!.id];
    const qDynamicHints = dynamicHints[current!.id] || [];
    const hasHint2 = qDynamicHints.some(h => h.hint_number === 2);
    const hasHint3 = qDynamicHints.some(h => h.hint_number === 3);
    const currentCode = codeMap[current!.id] || '';
    const hasTypedCode = currentCode.trim().length > 0 && currentCode.trim() !== (current!.starter_code || '').trim();
    const canRequestSmartHint = hasTypedCode || (isSubmitted && !result?.passed);
    const progressPct = ((currentIdx + (isSubmitted ? 1 : 0)) / questions.length) * 100;

    return (
        <div className="codex" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)', overflow: 'hidden' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', height: 56, borderBottom: '1px solid var(--hairline)', background: 'var(--bg-primary)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                    <button onClick={() => navigate(-1)} className="t-label" style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <ArrowLeft size={15} /> BACK
                    </button>
                    <div>
                        <div className="t-label" style={{ color: 'var(--accent-primary)' }}>PROBLEM SET</div>
                        <div className="t-mono steel" style={{ marginTop: 2 }}>{locState.sessionTitle || locState.lessonTitle || 'Session practice'}</div>
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {bestScore != null && (
                        <span className="t-mono steel">BEST {bestScore}/100</span>
                    )}
                    <span style={{ width: 1, height: 18, background: 'var(--hairline)' }} />
                    <Sparkles size={15} style={{ color: 'var(--accent-primary)' }} />
                    <span className="t-label" style={{ color: 'var(--text-primary)' }}>{currentIdx + 1} / {questions.length}</span>
                </div>
            </div>

            {/* Progress bar */}
            <div className="progress" style={{ borderRadius: 0 }}>
                <i style={{ width: `${progressPct}%` }} />
            </div>

            <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
                {/* Left panel — question */}
                <div style={{ flex: '0 0 40%', maxWidth: '40%', display: 'flex', flexDirection: 'column', overflowY: 'auto', background: 'var(--bg-surface)', borderRight: '1px solid var(--hairline)', paddingBottom: 24 }}>
                    {/* Scenario framing */}
                    <div style={{ padding: '22px 24px', borderBottom: '1px solid var(--hairline)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                            <BookOpen size={15} style={{ color: 'var(--accent-primary)' }} />
                            <h4 className="t-heading" style={{ margin: 0, fontSize: 17, color: 'var(--text-primary)' }}>{current!.title}</h4>
                            <span className="tag-steel" style={{ marginLeft: 'auto' }}>{current!.difficulty}</span>
                        </div>

                        {/* Story card */}
                        <div className="paper-card" style={{ padding: 16, borderRadius: 8, borderLeft: '2px solid var(--accent-primary)', marginBottom: 12 }}>
                            <p className="t-body" style={{ margin: 0, fontSize: 14, fontStyle: 'italic', fontFamily: 'var(--ff-editorial)', color: 'var(--text-primary)', lineHeight: 1.55 }}>{current!.scenario_framing}</p>
                        </div>

                        {/* Problem statement */}
                        <div style={{ padding: 16, background: 'var(--bg-paper)', border: '1px solid var(--bg-paper-line)', borderRadius: 8, fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap', color: 'var(--text-primary)' }}>
                            {current!.problem_statement}
                        </div>

                        {current!.target_weakness && (
                            <p className="t-mono steel" style={{ marginTop: 10 }}>
                                <span style={{ color: 'var(--text-secondary)' }}>TARGETS:</span> {current!.target_weakness}
                            </p>
                        )}
                    </div>

                    {/* Hints */}
                    <div style={{ padding: '16px 24px' }}>
                        {/* Static hint — always available, free */}
                        <button
                            onClick={() => toggleStaticHint(current!.id)}
                            style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1px solid var(--accent-primary)', background: 'rgba(37,99,235,0.05)', color: 'var(--accent-primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}
                        >
                            <span className="t-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                                <Lightbulb size={14} /> HINT · FREE
                            </span>
                            {staticHintExpanded[current!.id] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </button>
                        {staticHintExpanded[current!.id] && (
                            <div style={{ marginBottom: 12, padding: 14, background: 'rgba(37,99,235,0.05)', border: '1px solid rgba(37,99,235,0.25)', borderRadius: 8, fontSize: 14, color: 'var(--text-primary)' }}>
                                {current!.static_hint}
                            </div>
                        )}

                        {/* Dynamic hints revealed */}
                        {qDynamicHints.map((dh, i) => (
                            <div key={i} style={{ marginBottom: 10, padding: 14, background: 'var(--bg-paper)', border: '1px solid var(--bg-paper-line)', borderLeft: '3px solid var(--accent-warm)', borderRadius: 8, fontSize: 14, color: 'var(--text-primary)' }}>
                                <span style={{ fontWeight: 700 }}>Smart hint {dh.hint_number === 2 ? 1 : 2}:</span> {dh.content}
                                <p className="t-mono" style={{ marginTop: 6, color: 'var(--error-red)' }}>&minus;{dh.penalty.toFixed(1)} pts from the relevant rubric section</p>
                            </div>
                        ))}

                        {/* Smart hint button or confirm dialog */}
                        {confirmSmartHint ? (
                            <div style={{ padding: 14, background: 'var(--bg-paper)', border: '1px solid var(--accent-warm)', borderRadius: 8, fontSize: 13 }}>
                                <p style={{ margin: 0, marginBottom: 10, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <AlertTriangle size={14} style={{ color: 'var(--error-red)' }} /> This hint is more direct and costs more points. Reveal?
                                </p>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <button onClick={() => requestDynamicHint(3)} disabled={hintLoading} className="btn" style={{ padding: '8px 16px', fontSize: 11, background: 'var(--accent-warm)', color: '#fff' }}>
                                        {hintLoading ? 'LOADING…' : 'CONFIRM'}
                                    </button>
                                    <button onClick={() => setConfirmSmartHint(false)} className="btn btn-ghost-dark" style={{ padding: '8px 16px', fontSize: 11 }}>CANCEL</button>
                                </div>
                            </div>
                        ) : !hasHint3 && (
                            <button
                                onClick={() => {
                                    if (!hasHint2) requestDynamicHint(2);
                                    else setConfirmSmartHint(true);
                                }}
                                disabled={!canRequestSmartHint || hintLoading || hasHint3}
                                className="btn btn-ghost-dark"
                                style={{ width: '100%', justifyContent: 'center', padding: '10px 14px', fontSize: 11 }}
                            >
                                <Lightbulb size={14} />
                                {hintLoading ? 'GENERATING HINT…' : hasHint2 ? 'GET A MORE DIRECT HINT' : 'GET A SMARTER HINT'}
                            </button>
                        )}
                    </div>

                    {/* Result */}
                    {result && (
                        <div style={{ padding: '8px 24px' }}>
                            <div style={{ border: '1px solid var(--hairline)', borderRadius: 8, overflow: 'hidden' }}>
                                <div style={{ padding: '16px 18px', display: 'flex', alignItems: 'center', gap: 14, background: scoreTint(result.final_score), borderBottom: `1px solid var(--hairline)` }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 64 }}>
                                        <span className="t-display" style={{ fontSize: 36, lineHeight: 1, color: scoreColor(result.final_score) }}>{result.final_score}</span>
                                        <span className="t-mono steel">/100</span>
                                    </div>
                                    <div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                            {result.passed
                                                ? <><CheckCircle2 size={14} style={{ color: 'var(--accent-success)' }} /><span className="t-label" style={{ color: 'var(--accent-success)' }}>PASSED</span></>
                                                : <><XCircle size={14} style={{ color: 'var(--error-red)' }} /><span className="t-label" style={{ color: 'var(--error-red)' }}>NEEDS WORK</span></>}
                                        </div>
                                        {result.hint_penalty > 0 && (
                                            <p className="t-mono steel" style={{ marginTop: 4 }}>Raw {result.raw_score} &minus; {result.hint_penalty} hint penalty</p>
                                        )}
                                    </div>
                                </div>
                                <div className="t-body" style={{ padding: '14px 18px', background: 'var(--bg-paper)', fontSize: 14, color: 'var(--text-primary)' }}>{result.feedback}</div>
                            </div>

                            {/* Analogy explanation */}
                            <div style={{ marginTop: 12, padding: 16, background: 'var(--bg-paper)', border: '1px solid var(--bg-paper-line)', borderLeft: '2px solid var(--accent-primary)', borderRadius: 8 }}>
                                <div className="t-label" style={{ color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}><Eye size={12} /> CONCEPT EXPLAINED</div>
                                <p className="t-body" style={{ margin: 0, fontSize: 14, color: 'var(--text-primary)' }}>{current!.analogy_explanation}</p>
                            </div>

                            {/* Rubric score breakdown — expandable criterion rows */}
                            {result.rubric_scores && result.rubric_scores.length > 0 && (
                                <div style={{ marginTop: 12, background: 'var(--bg-paper)', border: '1px solid var(--bg-paper-line)', borderRadius: 8, overflow: 'hidden' }}>
                                    <div className="t-label" style={{ color: 'var(--text-secondary)', padding: '12px 16px 8px', display: 'flex', alignItems: 'center', gap: 6 }}><BarChart3 size={12} /> RUBRIC BREAKDOWN</div>
                                    <div>
                                        {result.rubric_scores.map((rs, rsIdx) => {
                                            const passed = rs.earned >= rs.max;
                                            const isExpanded = expandedCriterion === `${rs.criterion}-${rsIdx}`;
                                            const matchingCrit: RubricCriterion | undefined = (result.evaluated_rubric ?? current!.rubric).find(c => c.name === rs.criterion);
                                            const c = rubricColor(rs.earned, rs.max);

                                            return (
                                                <div key={`${rs.criterion}-${rsIdx}`} style={{ borderTop: '1px solid var(--bg-paper-line)' }}>
                                                    <button
                                                        onClick={() => setExpandedCriterion(isExpanded ? null : `${rs.criterion}-${rsIdx}`)}
                                                        style={{ width: '100%', padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 10, background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' }}
                                                    >
                                                        {passed
                                                            ? <CheckCircle2 size={14} style={{ color: 'var(--accent-success)', flexShrink: 0 }} />
                                                            : <XCircle size={14} style={{ color: 'var(--error-red)', flexShrink: 0 }} />}
                                                        <span className="t-label" style={{ color: 'var(--steel-light)', flexShrink: 0 }}>{rs.category.replace('_', ' ')}</span>
                                                        <span style={{ fontSize: 12, fontWeight: 500, flex: 1, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{rs.criterion}</span>
                                                        <span className="t-mono" style={{ fontWeight: 700, flexShrink: 0, color: c }}>{rs.earned}/{rs.max}</span>
                                                        {isExpanded ? <ChevronUp size={12} style={{ color: 'var(--steel-light)' }} /> : <ChevronDown size={12} style={{ color: 'var(--steel-light)' }} />}
                                                    </button>
                                                    {isExpanded && matchingCrit && (
                                                        <div style={{ padding: '0 16px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                            {matchingCrit.checks.map((check: RubricCheck) => {
                                                                const checkResult = check.result;
                                                                return (
                                                                    <div key={check.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12 }}>
                                                                        <span style={{ marginTop: 1, flexShrink: 0, color: checkResult ? 'var(--accent-success)' : 'var(--error-red)' }}>{checkResult ? '✓' : '✗'}</span>
                                                                        <div style={{ flex: 1, minWidth: 0 }}>
                                                                            <p style={{ margin: 0, fontWeight: 500, color: checkResult ? 'var(--accent-success)' : 'var(--error-red)' }}>{check.question}</p>
                                                                            {check.evidence && (
                                                                                <p style={{ margin: 0, marginTop: 2, color: 'var(--text-secondary)' }}>{check.evidence}</p>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                );
                                                            })}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* Flow: Passed → Next Question | Failed → Show Solution or Resubmit */}
                            {result.passed ? (
                                <button onClick={goNext} className="btn btn-paper" style={{ marginTop: 16, width: '100%', justifyContent: 'center' }}>
                                    {currentIdx < questions.length - 1 ? <>NEXT QUESTION <ArrowRight size={16} /></> : <>VIEW SUMMARY <Trophy size={16} /></>}
                                </button>
                            ) : (
                                <>
                                    {!solutionShown[current!.id] ? (
                                        <button
                                            onClick={() => showSolutionForQuestion(current!.id)}
                                            className="btn btn-ghost-dark"
                                            style={{ marginTop: 16, width: '100%', justifyContent: 'center' }}
                                        >
                                            <Eye size={16} /> SHOW POSSIBLE ANSWER
                                        </button>
                                    ) : (
                                        <button onClick={goNext} className="btn btn-paper" style={{ marginTop: 16, width: '100%', justifyContent: 'center' }}>
                                            {currentIdx < questions.length - 1 ? <>NEXT QUESTION <ArrowRight size={16} /></> : <>VIEW SUMMARY <Trophy size={16} /></>}
                                        </button>
                                    )}
                                </>
                            )}
                        </div>
                    )}
                </div>

                {/* Right panel — Editor (stays dark; it's a code surface) */}
                <div style={{ flex: '1 1 0%', minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--code-bg)' }}>

                    {solutionShown[current!.id] && result?.example_solution ? (
                        /* ── Split view: Your Code vs Possible Answer ── */
                        <>
                            <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                                <div style={{ padding: '8px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <Code2 size={14} style={{ color: 'var(--text-secondary)' }} />
                                    <span className="t-mono" style={{ color: 'var(--text-secondary)' }}>YOUR CODE</span>
                                </div>
                                <div style={{ flex: 1, minHeight: 0 }}>
                                    <Editor
                                        height="100%"
                                        language={current!.language || 'python'}
                                        theme="vs-dark"
                                        value={codeMap[current!.id] ?? current!.starter_code}
                                        options={{
                                            minimap: { enabled: false },
                                            scrollBeyondLastLine: false,
                                            fontSize: 13,
                                            lineNumbersMinChars: 3,
                                            padding: { top: 8, bottom: 8 },
                                            wordWrap: 'on',
                                            automaticLayout: true,
                                            readOnly: true,
                                        }}
                                    />
                                </div>
                            </div>
                            <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', borderTop: '2px solid var(--accent-primary)' }}>
                                <div style={{ padding: '8px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <Eye size={14} style={{ color: 'var(--accent-primary)' }} />
                                    <span className="t-mono" style={{ color: 'var(--accent-primary)' }}>POSSIBLE ANSWER</span>
                                </div>
                                <div style={{ flex: 1, minHeight: 0 }}>
                                    <Editor
                                        height="100%"
                                        language={current!.language || 'python'}
                                        theme="vs-dark"
                                        value={result.example_solution}
                                        options={{
                                            minimap: { enabled: false },
                                            scrollBeyondLastLine: false,
                                            fontSize: 13,
                                            lineNumbersMinChars: 3,
                                            padding: { top: 8, bottom: 8 },
                                            wordWrap: 'on',
                                            automaticLayout: true,
                                            readOnly: true,
                                        }}
                                    />
                                </div>
                            </div>
                        </>
                    ) : (
                        /* ── Normal editor ── */
                        <>
                            <div style={{ padding: '10px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <Code2 size={14} style={{ color: 'var(--accent-primary)' }} />
                                    <span className="t-mono" style={{ color: 'var(--text-primary)' }}>solution.{current!.language === 'python' ? 'py' : current!.language}</span>
                                </div>
                                <span className="t-mono steel">{current!.language}</span>
                            </div>

                            <div style={{ flex: 1, minHeight: 0 }}>
                                <Editor
                                    height="100%"
                                    language={current!.language || 'python'}
                                    theme="vs-dark"
                                    value={codeMap[current!.id] ?? current!.starter_code}
                                    onChange={(v) => setCodeMap(p => ({ ...p, [current!.id]: v ?? '' }))}
                                    options={{
                                        minimap: { enabled: false },
                                        scrollBeyondLastLine: false,
                                        fontSize: 14,
                                        lineNumbersMinChars: 3,
                                        padding: { top: 12, bottom: 12 },
                                        wordWrap: 'on',
                                        automaticLayout: true,
                                        readOnly: false,
                                    }}
                                />
                            </div>
                        </>
                    )}

                    {/* Action bar */}
                    <div style={{ padding: '12px 18px', background: 'var(--bg-surface)', borderTop: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', gap: 10 }}>
                        {currentIdx > 0 && (
                            <button
                                onClick={() => setCurrentIdx(i => i - 1)}
                                className="btn btn-ghost-dark"
                                style={{ padding: '12px 16px' }}
                            >
                                <ArrowLeft size={16} /> PREVIOUS
                            </button>
                        )}
                        {!isSubmitted && !solutionShown[current!.id] && (
                            <button
                                onClick={skipQuestion}
                                className="btn btn-ghost-dark"
                                style={{ padding: '12px 16px', color: 'var(--steel-light)' }}
                            >
                                <SkipForward size={16} /> SKIP
                            </button>
                        )}
                        {!solutionShown[current!.id] && (
                            <button
                                onClick={handleSubmit}
                                disabled={submitting}
                                className="btn btn-red"
                                style={{ flex: 1, justifyContent: 'center' }}
                            >
                                {submitting ? <><Loader2 size={16} className="animate-spin" /> EVALUATING…</> :
                                    isSubmitted ? <><Send size={16} /> RESUBMIT</> :
                                        <><Send size={16} /> SUBMIT ANSWER</>}
                            </button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
