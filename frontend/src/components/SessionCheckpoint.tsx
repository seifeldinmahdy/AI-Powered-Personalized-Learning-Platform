// SessionCheckpoint — an in-session MCQ "knowledge check" that pops up at a
// topic checkpoint, blurs the lesson behind it, and blocks until the student
// either answers (then sees a score + per-topic analysis) or skips.
//
// It owns the full answer → submit → results flow so LiveSession only has to
// decide WHEN to show it and provide the generated questions.

import { useCallback, useMemo, useState } from 'react';
import { CheckCircle2, XCircle, X, Loader2 } from 'lucide-react';
import {
    submitCheckpoint,
    type MCQQuestionData,
    type CheckpointResultData,
} from '../services/assessments';

type Phase = 'quiz' | 'submitting' | 'results';

interface SessionCheckpointProps {
    questions: MCQQuestionData[];
    kind: 'mid' | 'end';
    checkpointIndex: number;
    courseId: string;
    studentId: string;
    sessionNumber: number;
    /** Live-session id, threaded to submit so the server can feed the result to
     *  the tutor + session profiler. */
    sessionId?: string;
    /** Called when the student finishes (after viewing results) or skips. */
    onClose: () => void;
    /** Called once a checkpoint has been scored (so the parent can record it). */
    onScored?: (result: CheckpointResultData) => void;
}

const ACCENT = 'var(--accent-primary)';
const GREEN = 'var(--accent-success)';
const RED = 'var(--error-red)';
const AMBER = 'var(--accent-warm)';

function scoreColor(pct: number): string {
    if (pct >= 0.7) return GREEN;
    if (pct >= 0.5) return AMBER;
    return RED;
}

export function SessionCheckpoint({
    questions,
    kind,
    checkpointIndex,
    courseId,
    studentId,
    sessionNumber,
    sessionId,
    onClose,
    onScored,
}: SessionCheckpointProps) {
    const [phase, setPhase] = useState<Phase>('quiz');
    const [answers, setAnswers] = useState<Record<number, string>>({});
    const [result, setResult] = useState<CheckpointResultData | null>(null);
    const [error, setError] = useState<string>('');

    const total = questions.length;
    const answeredCount = Object.keys(answers).length;
    const allAnswered = answeredCount === total;

    const heading = kind === 'mid' ? 'Knowledge Check' : 'Practice';
    const subtitle =
        kind === 'mid'
            ? 'A quick check on what you’ve covered so far.'
            : 'Wrap up the session by testing every topic you learned.';

    const handleSubmit = useCallback(async () => {
        setError('');
        setPhase('submitting');
        try {
            const res = await submitCheckpoint({
                questions,
                answers,
                course_id: courseId,
                student_id: studentId,
                session_number: sessionNumber,
                checkpoint_index: checkpointIndex,
                session_id: sessionId,
            });
            setResult(res);
            setPhase('results');
            onScored?.(res);
        } catch (e) {
            setError(
                e instanceof Error ? e.message : 'Could not score your answers. Please try again.',
            );
            setPhase('quiz');
        }
    }, [questions, answers, courseId, studentId, sessionNumber, checkpointIndex, sessionId, onScored]);

    // Per-topic breakdown for the results analysis, derived from the server's
    // authoritative per_topic_scores (falls back to deriving from per-question).
    const topicBreakdown = useMemo(() => {
        if (!result) return [] as Array<{ topic: string; pct: number }>;
        const fromServer = Object.entries(result.per_topic_scores || {});
        if (fromServer.length > 0) {
            return fromServer
                .map(([topic, pct]) => ({ topic, pct }))
                .sort((a, b) => a.pct - b.pct);
        }
        // Fallback: aggregate per-question results by topic.
        const agg: Record<string, { c: number; t: number }> = {};
        for (const qr of result.question_results || []) {
            const key = qr.topic || 'General';
            const a = (agg[key] ||= { c: 0, t: 0 });
            a.t += 1;
            if (qr.correct) a.c += 1;
        }
        return Object.entries(agg)
            .map(([topic, { c, t }]) => ({ topic, pct: t ? c / t : 0 }))
            .sort((a, b) => a.pct - b.pct);
    }, [result]);

    // ── Overlay: blurred, dimmed, blocking (no backdrop-click close) ──
    return (
        <div
            className="codex"
            style={{
                position: 'fixed',
                inset: 0,
                zIndex: 10000,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 20,
                background: 'rgba(19,16,13,0.55)',
                backdropFilter: 'blur(10px)',
                WebkitBackdropFilter: 'blur(10px)',
            }}
            role="dialog"
            aria-modal="true"
            aria-label={`${heading} checkpoint`}
        >
            <div
                style={{
                    width: '100%',
                    maxWidth: 720,
                    maxHeight: '88vh',
                    display: 'flex',
                    flexDirection: 'column',
                    background: 'var(--bg-primary)',
                    border: '1px solid var(--hairline)',
                    borderRadius: 16,
                    boxShadow: '0 24px 80px rgba(0,0,0,0.35)',
                    overflow: 'hidden',
                }}
            >
                {/* ── Header ───────────────────────────────────────────── */}
                <div
                    style={{
                        padding: '22px 28px',
                        borderBottom: '1px solid var(--hairline)',
                        display: 'flex',
                        alignItems: 'flex-start',
                        justifyContent: 'space-between',
                        gap: 16,
                    }}
                >
                    <div>
                        <div className="t-label" style={{ color: ACCENT, marginBottom: 6 }}>
                            {kind === 'mid' ? 'MIDPOINT · KNOWLEDGE CHECK' : 'SESSION REVIEW · PRACTICE'}
                        </div>
                        <h2 className="t-heading" style={{ fontSize: 24, color: 'var(--text-primary)' }}>
                            {heading}
                        </h2>
                        {phase !== 'results' && (
                            <p className="t-body" style={{ fontSize: 13.5, color: 'var(--text-secondary)', marginTop: 6 }}>
                                {subtitle}
                            </p>
                        )}
                    </div>
                    {phase !== 'submitting' && (
                        <button
                            onClick={onClose}
                            className="t-label"
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 6,
                                background: 'transparent',
                                border: '1px solid var(--hairline)',
                                borderRadius: 999,
                                padding: '8px 12px',
                                cursor: 'pointer',
                                color: 'var(--text-secondary)',
                                whiteSpace: 'nowrap',
                            }}
                            title={phase === 'results' ? 'Continue the session' : 'Skip this knowledge check'}
                        >
                            <X size={13} />
                            {phase === 'results' ? 'CONTINUE' : 'SKIP'}
                        </button>
                    )}
                </div>

                {/* ── Body (scrollable) ────────────────────────────────── */}
                <div style={{ overflowY: 'auto', padding: '24px 28px', flex: 1 }}>
                    {phase === 'submitting' && (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14, padding: '48px 0' }}>
                            <Loader2 size={30} className="animate-spin" style={{ color: ACCENT }} />
                            <div className="t-label" style={{ color: 'var(--text-secondary)' }}>SCORING YOUR ANSWERS…</div>
                        </div>
                    )}

                    {phase === 'quiz' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
                            {questions.map((q, qi) => (
                                <div key={qi}>
                                    <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
                                        <span className="t-mono" style={{ color: ACCENT }}>{String(qi + 1).padStart(2, '0')}</span>
                                        <span className="t-body" style={{ fontSize: 15.5, color: 'var(--text-primary)', fontWeight: 600 }}>{q.question}</span>
                                    </div>
                                    <div style={{ borderTop: '1px solid var(--hairline)' }}>
                                        {q.options.map((opt, oi) => {
                                            const active = answers[qi] === opt.text;
                                            return (
                                                <div
                                                    key={oi}
                                                    className={`opt-row${active ? ' is-active' : ''}`}
                                                    onClick={() => setAnswers((prev) => ({ ...prev, [qi]: opt.text }))}
                                                >
                                                    <div className="opt-letter t-mono" style={{ width: 22, color: active ? ACCENT : 'var(--steel)' }}>
                                                        {String.fromCharCode(65 + oi)}
                                                    </div>
                                                    <span className="t-body" style={{ fontSize: 14 }}>{opt.text}</span>
                                                    {active && <span style={{ width: 8, height: 8, background: ACCENT, marginLeft: 'auto' }} />}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {phase === 'results' && result && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
                            {/* Score */}
                            <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
                                <span className="t-display" style={{ fontSize: 56, color: scoreColor(result.score) }}>
                                    {Math.round(result.score * 100)}%
                                </span>
                                <span className="t-label" style={{ color: 'var(--text-secondary)' }}>
                                    {result.correct_count} / {result.total_count} CORRECT
                                </span>
                            </div>

                            {/* Per-topic analysis */}
                            {topicBreakdown.length > 0 && (
                                <div>
                                    <div className="t-label" style={{ color: 'var(--text-secondary)', marginBottom: 10 }}>BY TOPIC</div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                        {topicBreakdown.map(({ topic, pct }) => (
                                            <div key={topic} style={{ display: 'grid', gridTemplateColumns: '1fr 90px 44px', gap: 12, alignItems: 'center' }}>
                                                <span className="t-body" style={{ fontSize: 13.5, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{topic}</span>
                                                <div style={{ height: 6, background: 'rgba(0,0,0,0.08)', borderRadius: 4, position: 'relative' }}>
                                                    <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.max(3, pct * 100)}%`, background: scoreColor(pct), borderRadius: 4 }} />
                                                </div>
                                                <span className="t-mono" style={{ color: scoreColor(pct), textAlign: 'right' }}>{Math.round(pct * 100)}%</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Per-question review */}
                            <div>
                                <div className="t-label" style={{ color: 'var(--text-secondary)', marginBottom: 10 }}>REVIEW</div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                                    {result.question_results.map((qr, qi) => (
                                        <div key={qi} style={{ border: '1px solid var(--hairline)', borderRadius: 10, padding: '14px 16px', background: 'var(--bg-surface)' }}>
                                            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                                                {qr.correct
                                                    ? <CheckCircle2 size={18} style={{ color: GREEN, flexShrink: 0, marginTop: 2 }} />
                                                    : <XCircle size={18} style={{ color: RED, flexShrink: 0, marginTop: 2 }} />}
                                                <div style={{ flex: 1 }}>
                                                    <div className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)', fontWeight: 600, marginBottom: 6 }}>
                                                        {questions[qi]?.question ?? `Question ${qi + 1}`}
                                                    </div>
                                                    {!qr.correct && (
                                                        <div className="t-mono" style={{ color: RED, marginBottom: 2 }}>
                                                            YOU · {qr.chosen_answer || '—'}
                                                        </div>
                                                    )}
                                                    <div className="t-mono" style={{ color: GREEN, marginBottom: 8 }}>
                                                        CORRECT · {qr.correct_answer}
                                                    </div>
                                                    {qr.explanation && (
                                                        <p className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                                                            {qr.explanation}
                                                        </p>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* ── Footer ───────────────────────────────────────────── */}
                <div
                    style={{
                        padding: '18px 28px',
                        borderTop: '1px solid var(--hairline)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 16,
                    }}
                >
                    {phase === 'quiz' && (
                        <>
                            <div className="t-mono" style={{ color: 'var(--steel-light)' }}>
                                {answeredCount} OF {total} ANSWERED
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                {error && <span className="t-mono" style={{ color: RED }}>{error}</span>}
                                <button
                                    onClick={handleSubmit}
                                    disabled={!allAnswered}
                                    className="btn btn-primary"
                                    style={{ padding: '12px 22px', opacity: allAnswered ? 1 : 0.5 }}
                                >
                                    SUBMIT →
                                </button>
                            </div>
                        </>
                    )}
                    {phase === 'submitting' && (
                        <div className="t-mono" style={{ color: 'var(--steel-light)' }}>GENERATING RESULTS…</div>
                    )}
                    {phase === 'results' && (
                        <button
                            onClick={onClose}
                            className="btn btn-red"
                            style={{ marginLeft: 'auto', padding: '14px 26px' }}
                        >
                            CONTINUE SESSION →
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}
