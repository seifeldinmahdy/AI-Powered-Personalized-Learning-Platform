import { useParams, useNavigate, useLocation } from 'react-router';
import { useState, useEffect, useMemo } from 'react';
import {
    CheckCircle, ChevronRight, Loader2, Trophy, Sparkles, Target,
    TrendingUp, BookOpen, Layers,
} from 'lucide-react';
import {
    generateCategorizedQuestions,
    submitPlacementResults,
    updatePlacementScore,
    type AssessmentQuestion,
    type PlacementResult,
    type CategoryGroup,
} from '../services/assessments';
import { getCourseById } from '../services/courses';

// ── helpers ───────────────────────────────────────────────────────────────────

function getMasteryConfig(level: string) {
    switch (level) {
        case 'Expert':
            return {
                color: 'from-rose-500 to-pink-600',
                bg: 'bg-rose-500/10',
                text: 'text-rose-500',
                border: 'border-rose-500/30',
                message: 'Impressive knowledge! We\'ll focus on advanced concepts and help you master the toughest topics.',
                emoji: '🔥',
            };
        case 'Intermediate':
            return {
                color: 'from-amber-500 to-orange-500',
                bg: 'bg-amber-500/10',
                text: 'text-amber-500',
                border: 'border-amber-500/30',
                message: 'Great foundation! We\'ll build on what you know and fill in the gaps to push you further.',
                emoji: '⚡',
            };
        default:
            return {
                color: 'from-emerald-500 to-teal-500',
                bg: 'bg-emerald-500/10',
                text: 'text-emerald-500',
                border: 'border-emerald-500/30',
                message: 'Welcome aboard! We\'ll build your foundation step by step with clear, visual explanations.',
                emoji: '🌱',
            };
    }
}

// ── component ─────────────────────────────────────────────────────────────────

type Phase = 'preferences' | 'loading' | 'quiz' | 'submitting' | 'results';

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
    const [categories, setCategories] = useState<CategoryGroup[]>([]);
    const [answers, setAnswers] = useState<Record<number, number>>({}); // questionId → chosen option index
    const [phase, setPhase] = useState<Phase>('preferences');

    // Preferences
    const [compositionMode, setCompositionMode] = useState('balanced');
    const [languageProficiency, setLanguageProficiency] = useState('Intermediate');

    // Quiz navigation
    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
    const [showCategoryCard, setShowCategoryCard] = useState(true);

    // Results
    const [placementResult, setPlacementResult] = useState<PlacementResult | null>(null);

    // ── derived data ─────────────────────────────────────────────────────────
    const allQuestions = useMemo(() => categories.flatMap(c => c.questions), [categories]);

    const currentCategory = useMemo(() => {
        if (allQuestions.length === 0) return { name: '', description: '', groupIndex: 0, isFirstInGroup: false };
        let runningIdx = 0;
        for (let gi = 0; gi < categories.length; gi++) {
            const cat = categories[gi];
            for (let qi = 0; qi < cat.questions.length; qi++) {
                if (runningIdx === currentQuestionIndex) {
                    return { name: cat.name, description: cat.description, groupIndex: gi, isFirstInGroup: qi === 0 };
                }
                runningIdx++;
            }
        }
        return { name: '', description: '', groupIndex: 0, isFirstInGroup: false };
    }, [currentQuestionIndex, allQuestions, categories]);

    // ── resolve course title if not in state ─────────────────────────────────
    useEffect(() => {
        if (isNaN(id)) { navigate('/courses'); return; }
        if (!courseTitle) {
            getCourseById(id)
                .then((c) => setCourseTitle(c.title))
                .catch(() => setCourseTitle('Programming'));
        }
        // Resolve enrollment ID if missing
        if (!enrollmentId) {
            import('../services/api').then(async ({ getEnrollments }) => {
                try {
                    const res = await getEnrollments();
                    const list = Array.isArray(res.data) ? res.data : res.data?.results || [];
                    const e = list.find((e: any) => e.course === id);
                    if (e) setEnrollmentId(e.id);
                } catch { /* ignore */ }
            });
        }
    }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

    // Show category card when entering a new group
    useEffect(() => {
        if (phase === 'quiz' && currentCategory.isFirstInGroup) {
            setShowCategoryCard(true);
        }
    }, [currentQuestionIndex, phase, currentCategory.isFirstInGroup]);

    // ── generate questions after preferences ─────────────────────────────────
    const handleStartQuiz = async () => {
        setPhase('loading');

        // Mark assessment as started
        if (enrollmentId) {
            try {
                const { default: api } = await import('../services/api');
                await api.patch(`/courses/enrollments/${enrollmentId}/`, { is_assessment_started: true });
            } catch { /* ignore */ }
        }

        const cats = await generateCategorizedQuestions(courseTitle, String(id), 50);
        setCategories(cats);
        setCurrentQuestionIndex(0);
        setShowCategoryCard(true);
        setPhase('quiz');
    };

    // ── submit quiz ──────────────────────────────────────────────────────────
    const handleSubmit = async () => {
        setPhase('submitting');

        const authUser = localStorage.getItem('auth_user');
        const studentId = authUser ? JSON.parse(authUser).id : '0';

        const answerPayload = allQuestions.map((q) => {
            const chosenIdx = answers[q.id] ?? -1;
            const isCorrect = chosenIdx === q.correct;
            return {
                question_id: q.id,
                question: q.question,
                topic: q.topic || 'General',
                chosen_option: chosenIdx >= 0 ? q.options[chosenIdx] : '',
                correct_option: q.options[q.correct],
                is_correct: isCorrect,
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

            // Also save placement_score to Django enrollment
            if (enrollmentId) {
                try { await updatePlacementScore(enrollmentId, result.score_pct); } catch { /* non-critical */ }
            }

            setPlacementResult(result);
            setPhase('results');
        } catch (e) {
            console.error('Placement submission failed:', e);
            // Fallback to basic results
            const correct = allQuestions.filter((q) => answers[q.id] === q.correct).length;
            const pct = Math.round((correct / allQuestions.length) * 100);
            setPlacementResult({
                score_pct: pct,
                mastery_level: pct >= 70 ? 'Expert' : pct >= 40 ? 'Intermediate' : 'Novice',
                strengths: [],
                weaknesses: [],
                topic_performance: {},
                incorrectly_answered: [],
                context_saved: false,
            });
            setPhase('results');
        }
    };

    const isLastQuestion = currentQuestionIndex === allQuestions.length - 1;
    const currentQ = allQuestions[currentQuestionIndex];
    const selectedOption = currentQ ? (answers[currentQ.id] ?? -1) : -1;

    // ── PHASE: preferences ───────────────────────────────────────────────────

    if (phase === 'preferences') {
        return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-gradient-to-br from-[#0f0c29] via-[#302b63] to-[#24243e] overflow-y-auto">
                <div className="w-full max-w-lg px-6 py-12">
                    <div className="text-center mb-10">
                        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500 to-blue-500 mb-4">
                            <Target size={28} className="text-white" />
                        </div>
                        <h1 className="text-2xl font-bold text-white mb-2">Before we begin...</h1>
                        <p className="text-white/60 text-sm">
                            Help us personalize your experience with {courseTitle || 'this course'}.
                        </p>
                    </div>

                    <div className="space-y-6">
                        {/* Learning Mode */}
                        <div>
                            <label className="block text-sm font-semibold text-white/80 mb-3">
                                How do you prefer to learn?
                            </label>
                            <div className="grid grid-cols-3 gap-3">
                                {[
                                    { value: 'visual_heavy', label: 'Visual', icon: '🎨', desc: 'Diagrams & images' },
                                    { value: 'balanced', label: 'Balanced', icon: '⚖️', desc: 'Mix of both' },
                                    { value: 'text_heavy', label: 'Text', icon: '📝', desc: 'Detailed explanations' },
                                ].map((opt) => (
                                    <button
                                        key={opt.value}
                                        onClick={() => setCompositionMode(opt.value)}
                                        className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-all ${compositionMode === opt.value
                                                ? 'border-purple-400 bg-purple-400/10'
                                                : 'border-white/10 bg-white/5 hover:border-white/20'
                                            }`}
                                    >
                                        <span className="text-2xl">{opt.icon}</span>
                                        <span className="text-sm font-semibold text-white">{opt.label}</span>
                                        <span className="text-xs text-white/50">{opt.desc}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Language Proficiency */}
                        <div>
                            <label className="block text-sm font-semibold text-white/80 mb-3">
                                English proficiency level
                            </label>
                            <div className="grid grid-cols-2 gap-3">
                                {[
                                    { value: 'Elementary', label: 'Elementary', desc: 'Basic understanding' },
                                    { value: 'Intermediate', label: 'Intermediate', desc: 'Comfortable reading' },
                                    { value: 'Advanced', label: 'Advanced', desc: 'Fluent comprehension' },
                                    { value: 'Native', label: 'Native', desc: 'Native speaker' },
                                ].map((opt) => (
                                    <button
                                        key={opt.value}
                                        onClick={() => setLanguageProficiency(opt.value)}
                                        className={`flex flex-col items-start gap-1 p-3.5 rounded-xl border-2 transition-all ${languageProficiency === opt.value
                                                ? 'border-purple-400 bg-purple-400/10'
                                                : 'border-white/10 bg-white/5 hover:border-white/20'
                                            }`}
                                    >
                                        <span className="text-sm font-semibold text-white">{opt.label}</span>
                                        <span className="text-xs text-white/50">{opt.desc}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Continue */}
                        <button
                            onClick={handleStartQuiz}
                            className="w-full py-4 bg-gradient-to-r from-purple-500 to-blue-500 text-white rounded-xl font-bold text-base hover:shadow-xl hover:-translate-y-0.5 transition-all flex items-center justify-center gap-2"
                        >
                            Continue to Assessment
                            <ChevronRight size={18} />
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // ── PHASE: loading ───────────────────────────────────────────────────────

    if (phase === 'loading') {
        return (
            <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-gradient-to-br from-[#0f0c29] via-[#302b63] to-[#24243e]">
                <div className="relative">
                    <div className="w-24 h-24 rounded-full border-4 border-transparent border-t-purple-400 border-r-blue-400 animate-spin" />
                    <div className="absolute inset-0 flex items-center justify-center">
                        <BookOpen size={28} className="text-purple-300 animate-pulse" />
                    </div>
                </div>
                <div className="text-center mt-8">
                    <h1 className="text-xl font-bold text-white mb-2">Preparing your placement assessment...</h1>
                    <p className="text-white/50 text-sm">Generating questions tailored to {courseTitle}</p>
                </div>
            </div>
        );
    }

    // ── PHASE: submitting ────────────────────────────────────────────────────

    if (phase === 'submitting') {
        return (
            <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-gradient-to-br from-[#0f0c29] via-[#302b63] to-[#24243e]">
                <div className="relative">
                    <div className="w-24 h-24 rounded-full border-4 border-transparent border-t-emerald-400 border-r-teal-400 animate-spin" />
                    <div className="absolute inset-0 flex items-center justify-center">
                        <TrendingUp size={28} className="text-emerald-300 animate-pulse" />
                    </div>
                </div>
                <div className="text-center mt-8">
                    <h1 className="text-xl font-bold text-white mb-2">Analyzing your results...</h1>
                    <p className="text-white/50 text-sm">Building your personalized learning profile</p>
                </div>
            </div>
        );
    }

    // ── PHASE: results ───────────────────────────────────────────────────────

    if (phase === 'results' && placementResult) {
        const cfg = getMasteryConfig(placementResult.mastery_level);
        return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-gradient-to-br from-[#0f0c29] via-[#302b63] to-[#24243e] overflow-y-auto">
                <div className="w-full max-w-lg px-6 py-12">
                    <div className="bg-white/5 backdrop-blur-xl rounded-3xl border border-white/10 p-8 space-y-8">
                        {/* Mastery badge */}
                        <div className="text-center">
                            <div className="text-5xl mb-3">{cfg.emoji}</div>
                            <h1 className="text-2xl font-bold text-white mb-1">Assessment Complete!</h1>
                            <p className="text-white/50 text-sm">{courseTitle}</p>
                        </div>

                        {/* Score */}
                        <div className="text-center">
                            <div className="inline-flex items-baseline gap-1">
                                <span className="text-6xl font-bold text-white">{placementResult.score_pct}</span>
                                <span className="text-2xl text-white/40">%</span>
                            </div>
                            <div className="h-2 bg-white/10 rounded-full overflow-hidden mt-4 mx-8">
                                <div
                                    className={`h-full rounded-full bg-gradient-to-r ${cfg.color} transition-all duration-1000`}
                                    style={{ width: `${placementResult.score_pct}%` }}
                                />
                            </div>
                        </div>

                        {/* Mastery level */}
                        <div className={`text-center py-4 rounded-xl ${cfg.bg} border ${cfg.border}`}>
                            <p className="text-xs text-white/50 mb-1 uppercase tracking-wider">Your Mastery Level</p>
                            <p className={`text-3xl font-bold ${cfg.text}`}>{placementResult.mastery_level}</p>
                            <p className="text-sm text-white/60 mt-2 px-6 leading-relaxed">{cfg.message}</p>
                        </div>

                        {/* Strengths & Weaknesses */}
                        {(placementResult.strengths.length > 0 || placementResult.weaknesses.length > 0) && (
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <p className="text-xs font-semibold text-emerald-400 mb-2 uppercase tracking-wider">Strengths</p>
                                    <div className="flex flex-wrap gap-1.5">
                                        {placementResult.strengths.length > 0 ? placementResult.strengths.map((s) => (
                                            <span key={s} className="px-2.5 py-1 bg-emerald-500/15 text-emerald-400 rounded-lg text-xs font-medium">
                                                {s}
                                            </span>
                                        )) : (
                                            <span className="text-xs text-white/30">—</span>
                                        )}
                                    </div>
                                </div>
                                <div>
                                    <p className="text-xs font-semibold text-amber-400 mb-2 uppercase tracking-wider">Needs Work</p>
                                    <div className="flex flex-wrap gap-1.5">
                                        {placementResult.weaknesses.length > 0 ? placementResult.weaknesses.map((w) => (
                                            <span key={w} className="px-2.5 py-1 bg-amber-500/15 text-amber-400 rounded-lg text-xs font-medium">
                                                {w}
                                            </span>
                                        )) : (
                                            <span className="text-xs text-white/30">—</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Build My Learning Path CTA */}
                        <button
                            onClick={() => navigate(`/course/${id}/pathway`, { replace: true })}
                            className="w-full py-4 bg-gradient-to-r from-purple-500 to-blue-500 text-white rounded-xl font-bold text-base hover:shadow-xl hover:-translate-y-0.5 transition-all flex items-center justify-center gap-3"
                        >
                            <Sparkles size={20} />
                            Build My Learning Path
                            <ChevronRight size={18} />
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // ── PHASE: quiz (one question at a time with category transitions) ───────

    // Category transition card
    if (showCategoryCard && currentCategory.isFirstInGroup) {
        return (
            <div className="flex-1 flex flex-col bg-background">
                <div className="flex-1 flex items-center justify-center px-6">
                    <div className="w-full max-w-md text-center">
                        <div className="inline-flex items-center justify-center w-20 h-20 rounded-3xl bg-gradient-to-br from-secondary to-accent mb-6 shadow-lg">
                            <Layers size={36} className="text-white" />
                        </div>
                        <p className="text-xs font-semibold text-secondary uppercase tracking-widest mb-2">
                            Section {currentCategory.groupIndex + 1} of {categories.length}
                        </p>
                        <h1 className="text-3xl font-bold text-foreground mb-3">
                            {currentCategory.name}
                        </h1>
                        <p className="text-muted-foreground text-base mb-8 leading-relaxed">
                            {currentCategory.description}
                        </p>
                        <button
                            onClick={() => setShowCategoryCard(false)}
                            className="px-10 py-4 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-bold text-base hover:shadow-xl hover:-translate-y-0.5 transition-all inline-flex items-center gap-2"
                        >
                            Start Section
                            <ChevronRight size={18} />
                        </button>
                    </div>
                </div>

                {/* Bottom progress (always visible) */}
                <div className="shrink-0 border-t border-border bg-card px-6 py-4">
                    <div className="max-w-3xl mx-auto">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-medium text-muted-foreground">
                                Section {currentCategory.groupIndex + 1} of {categories.length} — {currentCategory.name}
                            </span>
                            <span className="text-xs text-muted-foreground">
                                Question {currentQuestionIndex + 1} of {allQuestions.length}
                            </span>
                        </div>
                        <div className="h-2 bg-muted rounded-full overflow-hidden">
                            <div
                                className="h-full rounded-full bg-gradient-to-r from-secondary to-accent transition-all duration-300"
                                style={{ width: `${(currentQuestionIndex / allQuestions.length) * 100}%` }}
                            />
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    // Single question display
    return (
        <div className="flex-1 flex flex-col bg-background">
            {/* Question content area */}
            <div className="flex-1 flex items-center justify-center px-6 py-8 overflow-y-auto">
                <div className="w-full max-w-2xl">
                    {/* Topic badge */}
                    <div className="flex items-center gap-2 mb-6">
                        <span className="px-3 py-1 bg-secondary/10 text-secondary rounded-full text-xs font-semibold">
                            {currentCategory.name}
                        </span>
                        <span className="text-xs text-muted-foreground">
                            Section {currentCategory.groupIndex + 1} of {categories.length}
                        </span>
                    </div>

                    {/* Question stem */}
                    <h2 className="text-xl md:text-2xl font-bold text-foreground leading-relaxed mb-8">
                        {currentQ?.question}
                    </h2>

                    {/* Answer options */}
                    <div className="space-y-3">
                        {currentQ?.options.map((opt, idx) => {
                            const isSelected = selectedOption === idx;
                            return (
                                <button
                                    key={idx}
                                    onClick={() => setAnswers((prev) => ({ ...prev, [currentQ.id]: idx }))}
                                    className={`w-full text-left flex items-center gap-4 px-5 py-4 rounded-xl border-2 transition-all text-base font-medium ${
                                        isSelected
                                            ? 'border-secondary bg-secondary/10 text-foreground shadow-md'
                                            : 'border-border bg-card hover:bg-muted/50 hover:border-muted-foreground/30 text-foreground'
                                    }`}
                                >
                                    <span
                                        className={`w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-colors ${
                                            isSelected
                                                ? 'bg-secondary border-secondary text-white'
                                                : 'border-border text-muted-foreground'
                                        }`}
                                    >
                                        {isSelected ? <CheckCircle size={16} /> : String.fromCharCode(65 + idx)}
                                    </span>
                                    {opt}
                                </button>
                            );
                        })}
                    </div>

                    {/* Next / Submit button */}
                    <div className="flex justify-end mt-8">
                        <button
                            onClick={() => {
                                if (isLastQuestion) {
                                    handleSubmit();
                                } else {
                                    setCurrentQuestionIndex((i) => i + 1);
                                }
                            }}
                            disabled={selectedOption < 0}
                            className="px-8 py-3.5 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-bold text-sm hover:shadow-xl hover:-translate-y-0.5 transition-all flex items-center gap-2 disabled:opacity-40 disabled:pointer-events-none disabled:hover:translate-y-0"
                        >
                            {isLastQuestion ? (
                                <>
                                    <Trophy size={18} />
                                    Submit
                                </>
                            ) : (
                                <>
                                    Next
                                    <ChevronRight size={18} />
                                </>
                            )}
                        </button>
                    </div>
                </div>
            </div>

            {/* Bottom progress bar */}
            <div className="shrink-0 border-t border-border bg-card px-6 py-4">
                <div className="max-w-3xl mx-auto">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-medium text-muted-foreground">
                            Section {currentCategory.groupIndex + 1} of {categories.length} — {currentCategory.name}
                        </span>
                        <span className="text-sm font-semibold text-foreground">
                            Question {currentQuestionIndex + 1} of {allQuestions.length}
                        </span>
                    </div>
                    <div className="h-2.5 bg-muted rounded-full overflow-hidden">
                        <div
                            className="h-full rounded-full bg-gradient-to-r from-secondary to-accent transition-all duration-300"
                            style={{ width: `${((currentQuestionIndex + 1) / allQuestions.length) * 100}%` }}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
}
