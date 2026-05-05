import { useState, useEffect, useRef } from "react";
import { useParams, useLocation, useNavigate } from "react-router";
import Editor from "@monaco-editor/react";
import { toast } from "sonner";
import {
    generateQuestion,
    evaluateCodeGraded,
    getRubric,
    getHint,
    type GenerateQuestionResponse,
    type GradedResult,
    type Rubric,
} from "../../services/coding";
import { reportPracticeCompletion } from "../../services/progress";
import {
    Loader2,
    Sparkles,
    Send,
    CheckCircle2,
    XCircle,
    BookOpen,
    Lightbulb,
    ChevronDown,
    ChevronUp,
    ArrowLeft,
    SkipForward,
    Star,
} from "lucide-react";

function scoreColor(score: number): string {
    if (score >= 90) return "#10b981";
    if (score >= 80) return "#3b82f6";
    if (score >= 70) return "#6366f1";
    if (score >= 60) return "#f59e0b";
    return "#ef4444";
}

function scoreBg(score: number): string {
    if (score >= 90) return "rgba(16,185,129,0.1)";
    if (score >= 80) return "rgba(59,130,246,0.1)";
    if (score >= 70) return "rgba(99,102,241,0.1)";
    if (score >= 60) return "rgba(245,158,11,0.1)";
    return "rgba(239,68,68,0.1)";
}

interface LocationState {
    nextLessonId?: number | string;
    courseId?: string;
    lessonTitle?: string;
}

export default function LessonPractice() {
    const { courseId, lessonId } = useParams<{ courseId: string; lessonId: string }>();
    const location = useLocation();
    const navigate = useNavigate();
    const state = (location.state as LocationState) ?? {};
    const nextLessonId = state.nextLessonId;
    const lessonTitle = state.lessonTitle ?? "this lesson";
    const resolvedCourseId = courseId ?? state.courseId;

    const [generating, setGenerating] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [question, setQuestion] = useState<GenerateQuestionResponse | null>(null);
    const [code, setCode] = useState("");
    const [result, setResult] = useState<GradedResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [breakdownOpen, setBreakdownOpen] = useState(false);

    // Hint state
    const [hintLevel, setHintLevel] = useState(1);
    const [hintText, setHintText] = useState<string | null>(null);
    const [loadingHint, setLoadingHint] = useState(false);

    const rubricRef = useRef<Rubric | null>(null);

    // Auto-generate on mount using lesson title as topic
    useEffect(() => {
        const topic = lessonTitle !== "this lesson" ? lessonTitle : "Programming";
        generateQuestion(topic)
            .then((data) => {
                setQuestion(data);
                setCode(data.starter_code ?? "");
                // Load rubric in background
                getRubric(data.question)
                    .then((r) => { rubricRef.current = r; })
                    .catch(() => {});
            })
            .catch((err) => {
                setError(err instanceof Error ? err.message : "Failed to generate question");
            })
            .finally(() => setGenerating(false));
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const navigateNext = () => {
        if (nextLessonId && resolvedCourseId) {
            navigate(`/course/${resolvedCourseId}/lesson/${nextLessonId}`);
        } else if (resolvedCourseId) {
            navigate(`/courses/${resolvedCourseId}`);
        } else {
            navigate("/dashboard");
        }
    };

    const handleSkip = () => {
        navigateNext();
    };

    const handleHint = async () => {
        if (!question || hintLevel > 3) return;
        setLoadingHint(true);
        try {
            const data = await getHint(question.question, code, hintLevel);
            setHintText(data.hint);
            setHintLevel((prev) => Math.min(prev + 1, 4));
        } catch {
            toast.error("Failed to get hint.");
        } finally {
            setLoadingHint(false);
        }
    };

    const handleSubmit = async () => {
        if (!question) return;

        const trimmedCode = code.trim();
        if (!trimmedCode) {
            toast.error("Write some code before submitting.");
            return;
        }

        const trimmedStarter = (question.starter_code ?? "").trim();
        if (trimmedCode === trimmedStarter) {
            toast.error("Add your implementation before submitting.");
            return;
        }

        setSubmitting(true);
        setResult(null);
        setBreakdownOpen(false);
        try {
            const data = await evaluateCodeGraded(
                question.question,
                code,
                rubricRef.current ?? undefined
            );
            setResult(data);

            if (data.score >= 60) {
                // Award XP on backend
                let xpAwarded = 0;
                try {
                    const xpResult = await reportPracticeCompletion(
                        Number(lessonId),
                        data.score
                    );
                    xpAwarded = xpResult.xp_awarded ?? 0;
                } catch {
                    // XP award is best-effort
                }

                if (xpAwarded > 0) {
                    toast.success(`+${xpAwarded} XP earned! Keep it up!`);
                } else {
                    toast.success(`Passed with ${data.score}/100 (${data.letter_grade})!`);
                }
            }
        } catch (err: unknown) {
            toast.error(err instanceof Error ? err.message : "Evaluation failed.");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="flex flex-col h-screen bg-background">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-card shadow-sm">
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => navigate(`/courses/${resolvedCourseId}`)}
                        className="p-2 rounded-lg hover:bg-muted transition-colors"
                    >
                        <ArrowLeft size={18} />
                    </button>
                    <div>
                        <h1 className="text-lg font-bold leading-none">Lesson Practice</h1>
                        <p className="text-sm text-muted-foreground mt-0.5">{lessonTitle}</p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Star size={16} className="text-amber-400" />
                    <span className="text-sm text-muted-foreground">Complete for bonus XP</span>
                </div>
            </div>

            <div className="flex flex-1 overflow-hidden min-h-0">
                {/* Left panel */}
                <div
                    className="border-r-2 border-border flex flex-col overflow-y-auto bg-card"
                    style={{ flex: "0 0 38%", maxWidth: "38%" }}
                >
                    {generating && (
                        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
                            <Loader2 size={32} className="animate-spin text-secondary" />
                            <span className="text-sm">Generating your practice problem…</span>
                        </div>
                    )}

                    {error && (
                        <div className="m-6 p-4 bg-red-100 border border-red-400 text-red-700 rounded-xl text-sm">
                            {error}
                            <button
                                onClick={() => navigate("/dashboard")}
                                className="ml-2 underline font-medium"
                            >
                                Go to dashboard
                            </button>
                        </div>
                    )}

                    {question && !generating && (
                        <div className="px-6 py-5 border-b border-border">
                            <div className="flex items-center gap-2 mb-3">
                                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-secondary to-accent flex items-center justify-center">
                                    <BookOpen size={14} className="text-white" />
                                </div>
                                <h4 className="mb-0 text-base font-semibold">Problem</h4>
                                <span className="ml-auto flex items-center gap-1 px-2.5 py-1 bg-secondary/10 text-secondary rounded-lg text-xs font-semibold">
                                    <Sparkles size={10} />
                                    {lessonTitle}
                                </span>
                            </div>
                            <div className="p-4 bg-muted/30 rounded-xl border border-border text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">
                                {question.question}
                            </div>

                            {/* Hint */}
                            <div className="mt-3">
                                {hintText && (
                                    <div className="mb-2 p-3 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-800">
                                        <span className="font-semibold">Hint {hintLevel - 1}:</span> {hintText}
                                    </div>
                                )}
                                <button
                                    onClick={handleHint}
                                    disabled={loadingHint || hintLevel > 3}
                                    className="w-full py-2 px-4 rounded-xl border border-amber-300 bg-amber-50 text-amber-700 text-sm font-medium flex items-center justify-center gap-2 hover:bg-amber-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {loadingHint ? (
                                        <><Loader2 size={14} className="animate-spin" /><span>Getting hint…</span></>
                                    ) : hintLevel > 3 ? (
                                        <><Lightbulb size={14} /><span>All hints used</span></>
                                    ) : (
                                        <><Lightbulb size={14} /><span>Get Hint (Level {hintLevel})</span></>
                                    )}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Graded result */}
                    {result && (
                        <div className="px-6 py-5">
                            <div className="rounded-xl border border-border overflow-hidden">
                                <div
                                    className="px-4 py-4 flex items-center gap-3"
                                    style={{ background: scoreBg(result.score), borderBottom: `1px solid ${scoreColor(result.score)}33` }}
                                >
                                    <div className="flex flex-col items-center justify-center font-bold w-16">
                                        <span className="text-4xl leading-none font-extrabold" style={{ color: scoreColor(result.score) }}>{result.score}</span>
                                        <span className="text-xs font-medium" style={{ color: scoreColor(result.score), opacity: 0.6 }}>/100</span>
                                    </div>
                                    <div>
                                        <div className="text-2xl font-bold" style={{ color: scoreColor(result.score) }}>
                                            {result.letter_grade}
                                        </div>
                                        <div className="flex items-center gap-1 mt-0.5">
                                            {result.status === "Pass" ? (
                                                <><CheckCircle2 size={14} className="text-green-600" /><span className="text-xs font-semibold text-green-700">Passed</span></>
                                            ) : (
                                                <><XCircle size={14} className="text-red-500" /><span className="text-xs font-semibold text-red-600">Needs Work</span></>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="p-4 bg-card text-sm leading-relaxed text-foreground/85">
                                    {result.feedback}
                                </div>

                                {result.breakdown.length > 0 && (
                                    <div className="border-t border-border">
                                        <button
                                            onClick={() => setBreakdownOpen((o) => !o)}
                                            className="w-full px-4 py-2.5 flex items-center justify-between text-sm font-medium text-muted-foreground hover:bg-muted/30 transition-colors"
                                        >
                                            <span>Score Breakdown</span>
                                            {breakdownOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                        </button>
                                        {breakdownOpen && (
                                            <div className="px-4 pb-4 space-y-2">
                                                {result.breakdown.map((item) => (
                                                    <div key={item.criterion} className="p-3 bg-muted/20 rounded-lg text-xs">
                                                        <div className="flex items-center justify-between mb-1">
                                                            <span className="font-semibold">{item.criterion}</span>
                                                            <span className="font-bold" style={{ color: scoreColor(Math.round((item.earned / item.max) * 100)) }}>
                                                                {item.earned}/{item.max}
                                                            </span>
                                                        </div>
                                                        <div className="h-1.5 bg-muted rounded-full overflow-hidden mb-1">
                                                            <div
                                                                className="h-full rounded-full"
                                                                style={{ width: `${Math.round((item.earned / item.max) * 100)}%`, background: scoreColor(Math.round((item.earned / item.max) * 100)) }}
                                                            />
                                                        </div>
                                                        <span className="text-muted-foreground">{item.comment}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}

                                {result.hint && (
                                    <div className="px-4 pb-4">
                                        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                                            <span className="font-semibold">Try: </span>{result.hint}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Continue button after result */}
                            <button
                                onClick={navigateNext}
                                className="mt-4 w-full py-3 bg-gradient-to-r from-primary to-secondary text-white rounded-xl font-semibold flex items-center justify-center gap-2 hover:shadow-lg transition-all"
                            >
                                Continue to Next Lesson
                            </button>
                        </div>
                    )}
                </div>

                {/* Right panel — Editor */}
                <div className="flex flex-col bg-[#1e1e1e]" style={{ flex: "1 1 0%", minWidth: 0 }}>
                    <div className="px-4 py-2.5 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
                            <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
                            <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
                            <span className="ml-2 text-xs font-mono text-[#cccccc]">solution.py</span>
                        </div>
                        <span className="text-xs text-[#858585] font-mono">Python</span>
                    </div>

                    <div className="flex-1 min-h-0">
                        <Editor
                            height="100%"
                            language="python"
                            theme="vs-dark"
                            value={code}
                            onChange={(v) => setCode(v ?? "")}
                            options={{
                                minimap: { enabled: false },
                                scrollBeyondLastLine: false,
                                fontSize: 14,
                                lineNumbersMinChars: 3,
                                padding: { top: 12, bottom: 12 },
                                wordWrap: "on",
                                automaticLayout: true,
                            }}
                        />
                    </div>

                    {/* Action bar */}
                    <div className="px-5 py-4 bg-[#252526] border-t border-[#3e3e42] flex items-center gap-3">
                        <button
                            onClick={handleSkip}
                            className="px-5 py-3 rounded-xl border border-[#3e3e42] text-[#cccccc] text-sm font-medium flex items-center gap-2 hover:bg-[#2d2d2d] transition-colors"
                        >
                            <SkipForward size={16} />
                            Skip & Continue
                        </button>
                        <button
                            onClick={handleSubmit}
                            disabled={submitting || !question}
                            className="flex-1 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-lg transition-all"
                        >
                            {submitting ? (
                                <><Loader2 size={18} className="animate-spin" /><span>Evaluating…</span></>
                            ) : (
                                <><Send size={18} /><span>Submit & Earn XP</span></>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
