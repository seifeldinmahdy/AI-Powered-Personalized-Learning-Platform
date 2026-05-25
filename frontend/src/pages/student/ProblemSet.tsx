import { useState, useEffect, useMemo } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router';
import Editor from '@monaco-editor/react';
import { toast } from 'sonner';
import {
    generateProblemSet,
    getStudentProblemSets,
    submitAnswer,
    getDynamicHint,
    type ProblemSetData,
    type ProblemSetQuestion,
    type EvaluationResult,
    type RubricScore,
    type RubricCriterion,
    type RubricCheck,
} from '../../services/problemSet';
import {
    Loader2, Sparkles, Send, CheckCircle2, XCircle, BookOpen,
    Lightbulb, ChevronDown, ChevronUp, ArrowLeft, ArrowRight, Trophy,
    AlertTriangle, Eye, Code2, BarChart3, SkipForward,
} from 'lucide-react';

/* ── helpers ─────────────────────────────────────────────── */

function scoreColor(s: number) {
    if (s >= 90) return '#10b981';
    if (s >= 80) return '#3b82f6';
    if (s >= 70) return '#6366f1';
    if (s >= 60) return '#f59e0b';
    return '#ef4444';
}
function scoreBg(s: number) {
    if (s >= 90) return 'rgba(16,185,129,0.1)';
    if (s >= 80) return 'rgba(59,130,246,0.1)';
    if (s >= 70) return 'rgba(99,102,241,0.1)';
    if (s >= 60) return 'rgba(245,158,11,0.1)';
    return 'rgba(239,68,68,0.1)';
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
    studentProfileSummary?: string;
    nextLessonId?: number | string | null;
    slides?: { title: string; content: string; code?: string }[];
    labCells?: { id: string; cell_type: string; title: string; narrative?: string; code?: string; starter_code?: string; task_prompt?: string }[];
}

/* ── component ───────────────────────────────────────────── */

export default function ProblemSet() {
    const { courseId, lessonId } = useParams<{ courseId: string; lessonId: string }>();
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

    /* ── load / generate ───────────────────────────────────── */

    useEffect(() => {
        (async () => {
            if (!courseId || !lessonId) { setError('Missing route params'); setLoading(false); return; }
            try {
                const existing = await getStudentProblemSets(studentId, lessonId);
                // Only use problem sets that have questions (skip empty/failed ones)
                const validSets = existing.filter(ps => ps.questions && ps.questions.length > 0);
                if (validSets.length > 0) {
                    const ps = validSets[validSets.length - 1];
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
                        lessonId,
                        lessonTitle: locState.lessonTitle || '',
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
    }, [courseId, lessonId]);

    /* ── handlers ──────────────────────────────────────────── */

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
                lessonId: problemSet.lesson_id,
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
            <div className="flex flex-col items-center justify-center h-screen bg-background gap-4">
                <Loader2 size={40} className="animate-spin text-secondary" />
                <p className="text-lg font-medium text-muted-foreground">Dr. Nova is crafting your problem set…</p>
                <p className="text-sm text-muted-foreground/60">Analyzing your session and tailoring questions</p>
            </div>
        );
    }

    if (error || !problemSet || questions.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-screen bg-background gap-4">
                <AlertTriangle size={40} className="text-red-400" />
                <p className="text-lg font-semibold">{error || 'No questions generated'}</p>
                <button onClick={() => navigate(-1)} className="px-4 py-2 rounded-lg bg-muted hover:bg-muted/80 text-sm font-medium">Go Back</button>
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

        return (
            <div className="flex flex-col h-screen bg-background">
                <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-card">
                    <button onClick={() => navigate(-1)} className="p-2 rounded-lg hover:bg-muted"><ArrowLeft size={18} /></button>
                    <h1 className="text-lg font-bold">Problem Set Complete</h1>
                </div>
                <div className="flex-1 overflow-y-auto px-6 py-8 max-w-3xl mx-auto w-full">
                    {/* Overall score */}
                    <div className="text-center mb-8">
                        <div className="inline-flex items-center justify-center w-28 h-28 rounded-full border-4 mb-4" style={{ borderColor: scoreColor(avg) }}>
                            <div>
                                <div className="text-4xl font-black" style={{ color: scoreColor(avg) }}>{avg}</div>
                                <div className="text-xs font-medium opacity-60" style={{ color: scoreColor(avg) }}>/100</div>
                            </div>
                        </div>
                        <h2 className="text-2xl font-bold mb-1">Overall Score</h2>
                        <p className="text-muted-foreground text-sm">{questions.length} questions completed</p>
                    </div>

                    {/* Per-question summary */}
                    <div className="space-y-3">
                        {questions.map((q, idx) => {
                            const r = results[q.id] ?? problemSet.submissions?.[q.id]?.result;
                            const fs = r?.final_score ?? 0;
                            const passed = r?.passed ?? false;
                            const isOpen = expandedSummary === q.id;
                            const sub = problemSet.submissions?.[q.id];
                            const exSolution = r?.example_solution || q.example_solution;

                            return (
                                <div key={q.id} className="rounded-xl border border-border overflow-hidden bg-card">
                                    <button
                                        onClick={() => setExpandedSummary(isOpen ? null : q.id)}
                                        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-muted/30 transition-colors"
                                    >
                                        <span className="text-xs font-mono text-muted-foreground w-6">Q{idx + 1}</span>
                                        {passed ? <CheckCircle2 size={16} className="text-green-500" /> : <XCircle size={16} className="text-red-400" />}
                                        <span className="flex-1 text-left text-sm font-medium truncate">{q.title}</span>
                                        <span className="text-sm font-bold" style={{ color: scoreColor(fs) }}>{fs}/100</span>
                                        {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                    </button>
                                    {isOpen && (
                                        <div className="px-4 pb-4 space-y-3 border-t border-border pt-3">
                                            {r?.feedback && <p className="text-sm text-foreground/80">{r.feedback}</p>}
                                            {r?.rubric_scores && r.rubric_scores.length > 0 && (
                                                <div className="space-y-1.5">
                                                    <h4 className="text-xs font-semibold text-muted-foreground">Rubric Breakdown</h4>
                                                    {r.rubric_scores.map((rs: RubricScore, i: number) => {
                                                        const pct = rs.max > 0 ? Math.round((rs.earned / rs.max) * 100) : 0;
                                                        return (
                                                            <div key={`${rs.criterion}-${i}`} className="flex items-center gap-2 text-xs">
                                                                <span className="w-24 truncate font-medium">{rs.criterion}</span>
                                                                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                                                                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: scoreColor(pct) }} />
                                                                </div>
                                                                <span className="w-12 text-right font-bold" style={{ color: scoreColor(pct) }}>{rs.earned}/{rs.max}</span>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                            {/* Your Code vs Example Solution */}
                                            <div className="grid grid-cols-2 gap-3">
                                                {sub?.code && (
                                                    <div>
                                                        <h4 className="text-xs font-semibold text-muted-foreground mb-1">Your Code</h4>
                                                        <pre className="text-xs bg-[#1e1e1e] text-[#d4d4d4] p-3 rounded-lg overflow-auto max-h-48"><code>{sub.code}</code></pre>
                                                    </div>
                                                )}
                                                {exSolution && (
                                                    <div>
                                                        <h4 className="text-xs font-semibold text-amber-500 mb-1">Possible Answer</h4>
                                                        <pre className="text-xs bg-[#1a2332] text-[#7dd3fc] p-3 rounded-lg overflow-auto max-h-48 border border-amber-500/20"><code>{exSolution}</code></pre>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    {locState.nextLessonId ? (
                        <button
                            onClick={() => navigate(`/course/${courseId}/lesson/${locState.nextLessonId}`)}
                            className="mt-8 w-full py-3 bg-gradient-to-r from-primary to-secondary text-white rounded-xl font-semibold flex items-center justify-center gap-2 hover:shadow-lg transition-all"
                        >
                            <ArrowRight size={18} />
                            Continue to Next Session
                        </button>
                    ) : (
                        <button
                            onClick={() => navigate(`/courses/${courseId}`)}
                            className="mt-8 w-full py-3 bg-gradient-to-r from-primary to-secondary text-white rounded-xl font-semibold flex items-center justify-center gap-2 hover:shadow-lg transition-all"
                        >
                            <Trophy size={18} />
                            Back to Course
                        </button>
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

    return (
        <div className="flex flex-col h-screen bg-background overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-card shadow-sm">
                <div className="flex items-center gap-3">
                    <button onClick={() => navigate(-1)} className="p-2 rounded-lg hover:bg-muted transition-colors">
                        <ArrowLeft size={18} />
                    </button>
                    <div>
                        <h1 className="text-lg font-bold leading-none">Problem Set</h1>
                        <p className="text-sm text-muted-foreground mt-0.5">{locState.lessonTitle ?? 'Session Practice'}</p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Sparkles size={16} className="text-secondary" />
                    <span className="text-sm font-semibold">Question {currentIdx + 1} of {questions.length}</span>
                </div>
            </div>

            {/* Progress bar */}
            <div className="h-1 bg-muted">
                <div
                    className="h-full bg-gradient-to-r from-secondary to-accent transition-all duration-500"
                    style={{ width: `${((currentIdx + (isSubmitted ? 1 : 0)) / questions.length) * 100}%` }}
                />
            </div>

            <div className="flex flex-1 overflow-hidden min-h-0">
                {/* Left panel — question */}
                <div className="border-r-2 border-border flex flex-col overflow-y-auto bg-card pb-6" style={{ flex: '0 0 40%', maxWidth: '40%' }}>
                    {/* Scenario framing */}
                    <div className="px-6 py-5 border-b border-border">
                        <div className="flex items-center gap-2 mb-3">
                            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-secondary to-accent flex items-center justify-center">
                                <BookOpen size={14} className="text-white" />
                            </div>
                            <h4 className="mb-0 text-base font-semibold">{current!.title}</h4>
                            <span className="ml-auto px-2.5 py-1 bg-secondary/10 text-secondary rounded-lg text-xs font-semibold">
                                {current!.difficulty}
                            </span>
                        </div>

                        {/* Story card */}
                        <div className="p-4 bg-gradient-to-br from-indigo-50/60 to-purple-50/40 dark:from-indigo-950/20 dark:to-purple-950/10 rounded-xl border border-indigo-100 dark:border-indigo-800/30 mb-3">
                            <p className="text-sm italic leading-relaxed text-foreground/80">{current!.scenario_framing}</p>
                        </div>

                        {/* Problem statement */}
                        <div className="p-4 bg-muted/30 rounded-xl border border-border text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">
                            {current!.problem_statement}
                        </div>

                        {current!.target_weakness && (
                            <p className="mt-2 text-xs text-muted-foreground">
                                <span className="font-semibold">Targets:</span> {current!.target_weakness}
                            </p>
                        )}
                    </div>

                    {/* Hints */}
                    <div className="px-6 py-3">
                        {/* Static hint — always available, free */}
                        <button
                            onClick={() => toggleStaticHint(current!.id)}
                            className="w-full py-2 px-4 rounded-xl border border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300 text-sm font-medium flex items-center justify-between gap-2 hover:bg-emerald-100 dark:hover:bg-emerald-950/40 transition-colors mb-2"
                        >
                            <span className="flex items-center gap-2">
                                <Lightbulb size={14} />
                                Hint (free)
                            </span>
                            {staticHintExpanded[current!.id] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </button>
                        {staticHintExpanded[current!.id] && (
                            <div className="mb-3 p-3 bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800/40 rounded-xl text-sm text-emerald-800 dark:text-emerald-200">
                                {current!.static_hint}
                            </div>
                        )}

                        {/* Dynamic hints revealed */}
                        {qDynamicHints.map((dh, i) => (
                            <div key={i} className="mb-2 p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800/40 rounded-xl text-sm text-amber-800 dark:text-amber-200">
                                <span className="font-semibold">Smart Hint {dh.hint_number === 2 ? 1 : 2}:</span> {dh.content}
                                <p className="text-xs mt-1 opacity-70">&minus;{dh.penalty.toFixed(1)} pts deducted from the relevant rubric section</p>
                            </div>
                        ))}

                        {/* Smart hint button or confirm dialog */}
                        {confirmSmartHint ? (
                            <div className="p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-300 dark:border-amber-700 rounded-xl text-sm">
                                <p className="text-amber-800 dark:text-amber-200 mb-2 flex items-center gap-1.5">
                                    <AlertTriangle size={14} /> This hint is more direct and costs more points. Reveal?
                                </p>
                                <div className="flex gap-2">
                                    <button onClick={() => requestDynamicHint(3)} disabled={hintLoading} className="px-3 py-1.5 rounded-lg bg-amber-500 text-white text-xs font-semibold hover:bg-amber-600 disabled:opacity-50">
                                        {hintLoading ? 'Loading…' : 'Confirm'}
                                    </button>
                                    <button onClick={() => setConfirmSmartHint(false)} className="px-3 py-1.5 rounded-lg bg-muted text-xs font-medium hover:bg-muted/80">Cancel</button>
                                </div>
                            </div>
                        ) : !hasHint3 && (
                            <button
                                onClick={() => {
                                    if (!hasHint2) requestDynamicHint(2);
                                    else setConfirmSmartHint(true);
                                }}
                                disabled={!canRequestSmartHint || hintLoading || hasHint3}
                                className="w-full py-2 px-4 rounded-xl border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-300 text-sm font-medium flex items-center justify-center gap-2 hover:bg-amber-100 dark:hover:bg-amber-950/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Lightbulb size={14} />
                                {hintLoading ? 'Generating hint…' : hasHint2 ? 'Get a more direct hint' : 'Get a smarter hint'}
                            </button>
                        )}
                    </div>

                    {/* Result */}
                    {result && (
                        <div className="px-6 py-4">
                            <div className="rounded-xl border border-border overflow-hidden">
                                <div className="px-4 py-4 flex items-center gap-3" style={{ background: scoreBg(result.final_score), borderBottom: `1px solid ${scoreColor(result.final_score)}33` }}>
                                    <div className="flex flex-col items-center font-bold w-16">
                                        <span className="text-3xl font-extrabold" style={{ color: scoreColor(result.final_score) }}>{result.final_score}</span>
                                        <span className="text-xs opacity-60" style={{ color: scoreColor(result.final_score) }}>/100</span>
                                    </div>
                                    <div>
                                        <div className="flex items-center gap-1.5">
                                            {result.passed ? <><CheckCircle2 size={14} className="text-green-600" /><span className="text-xs font-semibold text-green-700">Passed</span></> : <><XCircle size={14} className="text-red-500" /><span className="text-xs font-semibold text-red-600">Needs Work</span></>}
                                        </div>
                                        {result.hint_penalty > 0 && (
                                            <p className="text-xs text-muted-foreground mt-0.5">Raw: {result.raw_score} &minus; {result.hint_penalty} hint penalty</p>
                                        )}
                                    </div>
                                </div>
                                <div className="p-4 bg-card text-sm leading-relaxed text-foreground/85">{result.feedback}</div>
                            </div>

                            {/* Analogy explanation */}
                            <div className="mt-3 p-4 bg-blue-50/60 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800/30 rounded-xl">
                                <h4 className="text-xs font-semibold text-blue-700 dark:text-blue-300 mb-1 flex items-center gap-1"><Eye size={12} /> Concept Explained</h4>
                                <p className="text-sm text-blue-800 dark:text-blue-200">{current!.analogy_explanation}</p>
                            </div>

                            {/* Rubric score breakdown — expandable criterion rows */}
                            {result.rubric_scores && result.rubric_scores.length > 0 && (
                                <div className="mt-3 bg-card border border-border rounded-xl overflow-hidden">
                                    <h4 className="text-xs font-semibold text-muted-foreground px-4 pt-3 pb-2 flex items-center gap-1"><BarChart3 size={12} /> Rubric Breakdown</h4>
                                    <div className="divide-y divide-border">
                                        {result.rubric_scores.map((rs, rsIdx) => {
                                            const pct = rs.max > 0 ? Math.round((rs.earned / rs.max) * 100) : 0;
                                            const passed = rs.earned >= rs.max;
                                            const isExpanded = expandedCriterion === `${rs.criterion}-${rsIdx}`;
                                            const matchingCrit = (result.evaluated_rubric ?? current!.rubric).find(c => c.name === rs.criterion);
                                            const categoryColors: Record<string, string> = {
                                                correctness: '#10b981',
                                                logic: '#6366f1',
                                                edge_cases: '#f59e0b',
                                                syntax_style: '#8b5cf6',
                                                requirements: '#3b82f6',
                                            };
                                            const catColor = categoryColors[rs.category] || '#6b7280';

                                            return (
                                                <div key={`${rs.criterion}-${rsIdx}`}>
                                                    <button
                                                        onClick={() => setExpandedCriterion(isExpanded ? null : `${rs.criterion}-${rsIdx}`)}
                                                        className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-muted/30 transition-colors text-left"
                                                    >
                                                        {passed
                                                            ? <CheckCircle2 size={14} className="text-green-500 flex-shrink-0" />
                                                            : <XCircle size={14} className="text-red-400 flex-shrink-0" />}
                                                        <span
                                                            className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide flex-shrink-0"
                                                            style={{ background: `${catColor}20`, color: catColor }}
                                                        >
                                                            {rs.category.replace('_', ' ')}
                                                        </span>
                                                        <span className="text-xs font-medium flex-1 truncate">{rs.criterion}</span>
                                                        <span className="text-xs font-bold flex-shrink-0" style={{ color: rs.earned >= rs.max ? '#4ade80' : rs.earned === 0 ? '#f87171' : '#facc15' }}>
                                                            {rs.earned}/{rs.max}
                                                        </span>
                                                        {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                                    </button>
                                                    {isExpanded && matchingCrit && (
                                                        <div className="px-4 pb-3 space-y-1.5 bg-muted/10">
                                                            {matchingCrit.checks.map((check) => {
                                                                const checkResult = check.result;
                                                                return (
                                                                    <div key={check.id} className="flex items-start gap-2 text-xs py-1">
                                                                        {checkResult
                                                                            ? <span className="text-green-500 mt-0.5 flex-shrink-0">✓</span>
                                                                            : <span className="text-red-400 mt-0.5 flex-shrink-0">✗</span>}
                                                                        <div className="flex-1 min-w-0">
                                                                            <p className="font-medium" style={{ color: checkResult ? '#4ade80' : '#f87171' }}>{check.question}</p>
                                                                            {check.evidence && (
                                                                                <p className="mt-0.5" style={{ color: 'rgba(255,255,255,0.8)' }}>
                                                                                    {check.evidence}
                                                                                </p>
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
                                <button onClick={goNext} className="mt-4 w-full py-3 bg-gradient-to-r from-primary to-secondary text-white rounded-xl font-semibold flex items-center justify-center gap-2 hover:shadow-lg transition-all">
                                    {currentIdx < questions.length - 1 ? <><ArrowRight size={18} /> Next Question</> : <><Trophy size={18} /> View Summary</>}
                                </button>
                            ) : (
                                <>
                                    {!solutionShown[current!.id] ? (
                                        <button
                                            onClick={() => showSolutionForQuestion(current!.id)}
                                            className="mt-4 w-full py-3 bg-amber-500/20 border border-amber-500/40 text-amber-400 rounded-xl font-semibold flex items-center justify-center gap-2 hover:bg-amber-500/30 transition-all"
                                        >
                                            <Eye size={18} /> Show Possible Answer
                                        </button>
                                    ) : (
                                        <button onClick={goNext} className="mt-4 w-full py-3 bg-gradient-to-r from-primary to-secondary text-white rounded-xl font-semibold flex items-center justify-center gap-2 hover:shadow-lg transition-all">
                                            {currentIdx < questions.length - 1 ? <><ArrowRight size={18} /> Next Question</> : <><Trophy size={18} /> View Summary</>}
                                        </button>
                                    )}
                                </>
                            )}
                        </div>
                    )}
                </div>

                {/* Right panel — Editor */}
                <div className="flex flex-col min-h-0 bg-[#1e1e1e]" style={{ flex: '1 1 0%', minWidth: 0 }}>

                    {solutionShown[current!.id] && result?.example_solution ? (
                        /* ── Split view: Your Code vs Possible Answer ── */
                        <>
                            <div className="flex-1 min-h-0 flex flex-col">
                                <div className="px-4 py-2 bg-[#252526] border-b border-[#3e3e42] flex items-center gap-2">
                                    <Code2 size={14} className="text-[#cccccc]" />
                                    <span className="text-xs font-mono text-[#cccccc]">Your Code</span>
                                </div>
                                <div className="flex-1 min-h-0">
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
                            <div className="flex-1 min-h-0 flex flex-col border-t-2 border-amber-500/40">
                                <div className="px-4 py-2 bg-[#1a2332] border-b border-amber-500/20 flex items-center gap-2">
                                    <Eye size={14} className="text-amber-400" />
                                    <span className="text-xs font-mono text-amber-400">Possible Answer</span>
                                </div>
                                <div className="flex-1 min-h-0">
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
                            <div className="px-4 py-2.5 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
                                    <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
                                    <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
                                    <span className="ml-2 text-xs font-mono text-[#cccccc]">solution.{current!.language === 'python' ? 'py' : current!.language}</span>
                                </div>
                                <span className="text-xs text-[#858585] font-mono">{current!.language}</span>
                            </div>

                            <div className="flex-1 min-h-0">
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
                    <div className="px-5 py-4 bg-[#252526] border-t border-[#3e3e42] flex items-center gap-3">
                        {currentIdx > 0 && (
                            <button
                                onClick={() => setCurrentIdx(i => i - 1)}
                                className="px-4 py-3 rounded-xl border border-[#3e3e42] text-[#cccccc] text-sm font-medium flex items-center gap-2 hover:bg-[#2d2d2d] transition-colors"
                            >
                                <ArrowLeft size={16} /> Previous
                            </button>
                        )}
                        {!isSubmitted && !solutionShown[current!.id] && (
                            <button
                                onClick={skipQuestion}
                                className="px-4 py-3 rounded-xl border border-[#3e3e42] text-[#858585] text-sm font-medium flex items-center gap-2 hover:bg-[#2d2d2d] hover:text-[#cccccc] transition-colors"
                            >
                                <SkipForward size={16} /> Skip
                            </button>
                        )}
                        {!solutionShown[current!.id] && (
                            <button
                                onClick={handleSubmit}
                                disabled={submitting}
                                className="flex-1 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-lg transition-all"
                            >
                                {submitting ? <><Loader2 size={18} className="animate-spin" /> Evaluating…</> :
                                    isSubmitted ? <><Send size={18} /> Resubmit</> :
                                        <><Send size={18} /> Submit Answer</>}
                            </button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
