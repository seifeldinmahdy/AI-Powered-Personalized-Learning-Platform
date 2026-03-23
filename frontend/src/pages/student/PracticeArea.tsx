import { useState } from "react";
import { Header } from "../../components/Header";
import Editor from "@monaco-editor/react";
import {
    generateQuestion,
    evaluateCode,
    type GenerateQuestionResponse,
    type EvaluateCodeResponse,
} from "../../services/coding";
import {
    Loader2,
    Sparkles,
    Send,
    CheckCircle2,
    XCircle,
    BookOpen,
    Code2,
    Trophy,
} from "lucide-react";

const TOPIC_CATEGORIES = [
    {
        category: "Standard Coding Topics",
        topics: ["Basic Syntax", "Control Flow", "Loops", "Functions"],
    },
    {
        category: "Data Structures",
        topics: ["Arrays/Lists", "Strings", "Dictionaries/Maps"],
    },
    {
        category: "Advanced Algorithmic Topics",
        topics: ["Math", "Sorting & Searching", "Recursion", "Dynamic Programming (DP)"],
    },
];

export default function PracticeArea() {
    // --- state ---
    const [topic, setTopic] = useState(TOPIC_CATEGORIES[0].topics[0]);
    const [generating, setGenerating] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [question, setQuestion] = useState<GenerateQuestionResponse | null>(null);
    const [code, setCode] = useState("");
    const [feedback, setFeedback] = useState<EvaluateCodeResponse | null>(null);
    const [error, setError] = useState<string | null>(null);

    // --- handlers ---
    const handleGenerate = async () => {
        setGenerating(true);
        setError(null);
        setFeedback(null);
        try {
            const data = await generateQuestion(topic);
            setQuestion(data);
            setCode(data.starter_code ?? "");
        } catch (err: unknown) {
            const msg =
                err instanceof Error ? err.message : "Failed to generate question";
            setError(msg);
        } finally {
            setGenerating(false);
        }
    };

    const handleSubmit = async () => {
        if (!question) return;
        setSubmitting(true);
        setError(null);
        try {
            const data = await evaluateCode(question.question, code);
            setFeedback(data);
        } catch (err: unknown) {
            const msg =
                err instanceof Error ? err.message : "Failed to evaluate code";
            setError(msg);
        } finally {
            setSubmitting(false);
        }
    };

    // --- render ---
    return (
        <>
            <Header
                title="Practice & Challenge"
                subtitle="Sharpen your Python skills with AI-generated problems"
            />

            <div className="flex-1 flex overflow-hidden min-h-0">
                {/* ====== LEFT PANEL — Controls, Question, Feedback (35%) ====== */}
                <div className="border-r-2 border-border flex flex-col overflow-y-auto overflow-x-hidden bg-card" style={{ flex: '0 0 35%', maxWidth: '35%' }}>
                    {/* Topic Selector — Categorized Pills */}
                    <div className="px-6 py-5 border-b border-border" style={{ background: 'linear-gradient(to right, var(--primary, #6366f1) 0%, var(--accent, #8b5cf6) 100%)', backgroundSize: '100%', opacity: 1 }}>
                        <div style={{ background: 'var(--card, #fff)', borderRadius: '12px', padding: '16px' }}>
                            {TOPIC_CATEGORIES.map((cat, ci) => (
                                <div key={cat.category} style={{ marginTop: ci === 0 ? 0 : 16 }}>
                                    <p style={{ fontSize: '0.75rem', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                                        {cat.category}
                                    </p>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                        {cat.topics.map((t) => (
                                            <button
                                                key={t}
                                                onClick={() => setTopic(t)}
                                                style={{
                                                    padding: '6px 16px',
                                                    borderRadius: 9999,
                                                    fontSize: '0.8125rem',
                                                    fontWeight: 500,
                                                    cursor: 'pointer',
                                                    border: 'none',
                                                    transition: 'all 0.2s',
                                                    ...(topic === t
                                                        ? { background: 'linear-gradient(to right, var(--secondary, #6366f1), var(--accent, #8b5cf6))', color: '#fff', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }
                                                        : { background: '#f3f4f6', color: '#374151' }),
                                                }}
                                                onMouseEnter={(e) => { if (topic !== t) (e.target as HTMLElement).style.background = '#e5e7eb'; }}
                                                onMouseLeave={(e) => { if (topic !== t) (e.target as HTMLElement).style.background = '#f3f4f6'; }}
                                            >
                                                {t}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <button
                            id="generate-btn"
                            onClick={handleGenerate}
                            disabled={generating}
                            style={{ marginTop: 16, width: '100%', padding: '12px 0', background: 'linear-gradient(to right, var(--secondary, #6366f1), var(--accent, #8b5cf6))', color: '#fff', borderRadius: 12, fontWeight: 600, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, opacity: generating ? 0.6 : 1, transition: 'all 0.2s' }}
                        >
                            {generating ? (
                                <>
                                    <Loader2 size={18} className="animate-spin" />
                                    <span>Generating…</span>
                                </>
                            ) : (
                                <>
                                    <Sparkles size={18} />
                                    <span>Generate Question</span>
                                </>
                            )}
                        </button>
                    </div>

                    {/* Error banner */}
                    {error && (
                        <div className="mx-6 mt-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded-xl text-sm">
                            {error}
                        </div>
                    )}

                    {/* Question Display */}
                    {question && (
                        <div className="px-6 py-5 border-b border-border">
                            <div className="flex items-center gap-2 mb-3">
                                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-secondary to-accent flex items-center justify-center">
                                    <BookOpen size={14} className="text-white" />
                                </div>
                                <h4 className="mb-0 text-base font-semibold">Problem</h4>
                                <span className="ml-auto px-2.5 py-1 bg-secondary/10 text-secondary rounded-lg text-xs font-semibold">
                                    {topic}
                                </span>
                            </div>
                            <div className="p-4 bg-muted/30 rounded-xl border border-border text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">
                                {question.question}
                            </div>
                        </div>
                    )}

                    {/* No question placeholder */}
                    {!question && !generating && (
                        <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
                            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-primary/10 to-accent/10 flex items-center justify-center mb-5">
                                <Code2 size={36} className="text-secondary" />
                            </div>
                            <h4 className="mb-2">Ready to Practice?</h4>
                            <p className="text-sm text-muted-foreground max-w-xs">
                                Select a topic above and click <strong>Generate Question</strong>{" "}
                                to receive an AI-crafted coding challenge.
                            </p>
                        </div>
                    )}

                    {/* Feedback Display */}
                    {feedback && (
                        <div className="px-6 py-5">
                            <div className="flex items-center gap-2 mb-3">
                                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center">
                                    <Trophy size={14} className="text-white" />
                                </div>
                                <h4 className="mb-0 text-base font-semibold">AI Feedback</h4>
                            </div>

                            <div className="rounded-xl border border-border overflow-hidden">
                                {/* Status bar */}
                                <div
                                    className={`px-4 py-3 flex items-center gap-2 ${feedback.status === "Pass"
                                        ? "bg-green-50 border-b border-green-200"
                                        : "bg-red-50 border-b border-red-200"
                                        }`}
                                >
                                    {feedback.status === "Pass" ? (
                                        <CheckCircle2 size={20} className="text-green-600" />
                                    ) : (
                                        <XCircle size={20} className="text-red-600" />
                                    )}
                                    <span
                                        className={`font-semibold text-sm ${feedback.status === "Pass" ? "text-green-700" : "text-red-700"}`}
                                    >
                                        {feedback.status === "Pass" ? "Passed" : "Needs Work"}
                                    </span>
                                </div>

                                {/* Feedback text */}
                                <div className="p-4 bg-card text-sm leading-relaxed whitespace-pre-wrap text-foreground/85">
                                    {feedback.feedback}
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* ====== RIGHT PANEL — Monaco Editor (fills remaining space) ====== */}
                <div className="flex flex-col bg-[#1e1e1e]" style={{ flex: '1 1 0%', minWidth: 0 }}>
                    {/* Editor header */}
                    <div className="px-4 py-2.5 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
                            <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
                            <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
                            <span className="ml-2 text-xs font-mono text-[#cccccc]">
                                solution.py
                            </span>
                        </div>
                        <span className="text-xs text-[#858585] font-mono">Python</span>
                    </div>

                    {/* Monaco Editor */}
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

                    {/* Submit bar */}
                    <div className="px-5 py-4 bg-[#252526] border-t border-[#3e3e42] flex items-center gap-3">
                        <button
                            id="submit-btn"
                            onClick={handleSubmit}
                            disabled={submitting || !question}
                            className="flex-1 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {submitting ? (
                                <>
                                    <Loader2 size={18} className="animate-spin" />
                                    <span>Evaluating…</span>
                                </>
                            ) : (
                                <>
                                    <Send size={18} />
                                    <span>Submit Code</span>
                                </>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        </>
    );
}
