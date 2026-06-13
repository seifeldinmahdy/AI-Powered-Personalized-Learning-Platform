import { useParams, useNavigate, Link } from 'react-router';
import { useState, useEffect } from 'react';
import {
    BookOpen, Star, Users, Clock, ChevronDown, ChevronRight,
    Lock, CheckCircle, GraduationCap, Loader2, ArrowLeft, Tag,
} from 'lucide-react';
import { toast } from 'sonner';
import { getCourseById, submitCourseRating, type Course } from '../services/courses';
import { getModules, getLessons, type Module, type Lesson } from '../services/lessons';
import { getEnrollments } from '../services/api';
import { getLessonCompletions } from '../services/progress';
import { CapstoneStartCTA } from '../components/CapstoneStartCTA';

// ── helpers ──────────────────────────────────────────────────────────────────

function difficultyColor(d: string) {
    switch (d) {
        case 'Beginner': return 'bg-emerald-100 text-emerald-700';
        case 'Intermediate': return 'bg-amber-100 text-amber-700';
        case 'Advanced': return 'bg-rose-100 text-rose-700';
        default: return 'bg-muted text-muted-foreground';
    }
}

function estimateDuration(lessonCount: number) {
    const hours = Math.round((lessonCount * 30) / 60);
    return hours < 1 ? `${lessonCount * 30}m` : `~${hours}h`;
}

function parseSyllabus(raw: Course['syllabus']): string[] {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw as string[];
    if (typeof raw === 'string') {
        try {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) return parsed;
            return [raw];
        } catch {
            return raw.split('\n').filter(Boolean);
        }
    }
    if (typeof raw === 'object') {
        const obj = raw as Record<string, unknown>;
        return Object.values(obj).map(String);
    }
    return [];
}

// ── component ─────────────────────────────────────────────────────────────────

interface EnrollmentInfo {
    id: number;
    course: number;
    current_lesson: number | null;
    placement_score: number | null;
    is_pathway_ready: boolean;
    is_assessment_started: boolean;
    progress_percentage?: string;
}

export default function CourseDetail() {
    const { courseId } = useParams<{ courseId: string }>();
    const navigate = useNavigate();

    const [course, setCourse] = useState<Course | null>(null);
    const [modules, setModules] = useState<Module[]>([]);
    const [lessonMap, setLessonMap] = useState<Record<number, Lesson[]>>({});
    const [expandedModules, setExpandedModules] = useState<Set<number>>(new Set());
    const [enrollment, setEnrollment] = useState<EnrollmentInfo | null>(null);
    const [completedLessonIds, setCompletedLessonIds] = useState<Set<number>>(new Set());
    const [loading, setLoading] = useState(true);
    const [enrolling, setEnrolling] = useState(false);
    const [error, setError] = useState('');

    const id = Number(courseId);

    useEffect(() => {
        if (isNaN(id)) { setError('Invalid course ID'); setLoading(false); return; }
        let cancelled = false;

        async function load() {
            try {
                const [courseData, mods, enrollRes] = await Promise.all([
                    getCourseById(id),
                    getModules(id),
                    getEnrollments().catch(() => ({ data: [] })),
                ]);
                if (cancelled) return;
                setCourse(courseData);
                setModules(mods.sort((a, b) => a.module_order - b.module_order));

                const list: EnrollmentInfo[] = Array.isArray(enrollRes.data)
                    ? enrollRes.data
                    : (enrollRes.data as { results?: EnrollmentInfo[] }).results ?? [];
                const found = list.find((e) => e.course === id) ?? null;
                setEnrollment(found);

                // Load completed lessons if enrolled
                if (found) {
                    try {
                        const completions = await getLessonCompletions(found.id);
                        const ids = new Set(
                            completions
                                .filter((c) => c.status === 'Completed')
                                .map((c) => c.lesson)
                        );
                        if (!cancelled) setCompletedLessonIds(ids);
                    } catch { /* non-critical */ }
                }

                // Expand first module by default
                if (mods.length > 0) setExpandedModules(new Set([mods[0].id]));

                // Load lessons for the first module eagerly
                if (mods.length > 0) {
                    try {
                        const lessons = await getLessons(mods[0].id);
                        if (!cancelled) setLessonMap({ [mods[0].id]: lessons.sort((a, b) => a.lesson_order - b.lesson_order) });
                    } catch { /* non-critical */ }
                }
            } catch {
                if (!cancelled) setError('Failed to load course details.');
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        load();
        return () => { cancelled = true; };
    }, [id]);

    const toggleModule = async (modId: number) => {
        setExpandedModules((prev) => {
            const next = new Set(prev);
            if (next.has(modId)) { next.delete(modId); return next; }
            next.add(modId);
            return next;
        });
        if (!lessonMap[modId]) {
            try {
                const lessons = await getLessons(modId);
                setLessonMap((prev) => ({ ...prev, [modId]: lessons.sort((a, b) => a.lesson_order - b.lesson_order) }));
            } catch { /* ignore */ }
        }
    };

    const handleStartAssessment = async () => {
        if (!course) return;
        setEnrolling(true);
        try {
            // If already enrolled, navigate based on pathway/assessment progress
            if (enrollment) {
                if (enrollment.is_pathway_ready) {
                    if (enrollment.current_lesson) {
                        navigate(`/course/${id}/lesson/${enrollment.current_lesson}`);
                    } else {
                        // Find the first lesson of the first module
                        const firstLesson = Object.values(lessonMap).flat()[0];
                        if (firstLesson) {
                            navigate(`/course/${id}/lesson/${firstLesson.id}`);
                        } else if (modules.length > 0) {
                            // Lessons not loaded yet — fetch first module's lessons
                            try {
                                const lessons = await getLessons(modules[0].id);
                                if (lessons.length > 0) {
                                    navigate(`/course/${id}/lesson/${lessons[0].id}`);
                                    return;
                                }
                            } catch { /* ignore */ }
                        }
                        navigate('/dashboard');
                    }
                    return;
                } else if (enrollment.is_assessment_started) {
                    // Resume assessment
                    navigate(`/courses/${id}/assessment`, {
                        state: { enrollmentId: enrollment.id, courseTitle: course.title },
                    });
                    return;
                } else {
                    // Start assessment flow
                    navigate(`/courses/${id}/assessment`, {
                        state: { enrollmentId: enrollment.id, courseTitle: course.title },
                    });
                    return;
                }
            }
            // Otherwise enroll first, then send to assessment
            const { enroll } = await import('../services/api');
            const { data } = await enroll(id);
            navigate(`/courses/${id}/assessment`, {
                state: { enrollmentId: data.id, courseTitle: course.title },
            });
        } catch {
            alert('Failed to start. Please try again.');
        } finally {
            setEnrolling(false);
        }
    };

    const handleGeneratePathway = () => {
        navigate(`/course/${id}/pathway`);
    };

    // ── loading / error ───────────────────────────────────────────────────────

    if (loading) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <Loader2 size={40} className="animate-spin text-secondary" />
            </div>
        );
    }

    if (error || !course) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center gap-4">
                <p className="text-destructive">{error || 'Course not found.'}</p>
                <Link to="/courses" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
                    <ArrowLeft size={16} /> Back to Courses
                </Link>
            </div>
        );
    }

    const syllabus = parseSyllabus(course.syllabus);
    const isEnrolled = !!enrollment;

    return (
        <div className="flex-1 overflow-y-auto bg-background">
            {/* ── Hero banner ─────────────────────────────────────────────── */}
            <div className="bg-gradient-to-br from-primary via-secondary to-accent text-white">
                <div className="max-w-6xl mx-auto px-6 py-10">
                    <Link
                        to="/courses"
                        className="inline-flex items-center gap-2 text-white/70 hover:text-white text-sm mb-6 no-underline transition-colors"
                    >
                        <ArrowLeft size={16} /> All Courses
                    </Link>

                    <div className="flex flex-col md:flex-row md:items-start gap-6">
                        {/* Left: info */}
                        <div className="flex-1">
                            <div className="flex items-center gap-2 mb-3">
                                <span className={`px-2.5 py-1 rounded-lg text-xs font-bold ${difficultyColor(course.difficulty)}`}>
                                    {course.difficulty}
                                </span>
                                {parseFloat(course.price) === 0 && (
                                    <span className="px-2.5 py-1 rounded-lg text-xs font-bold bg-emerald-500/90 text-white">FREE</span>
                                )}
                            </div>

                            <h1 className="text-3xl font-bold mb-3 text-white">{course.title}</h1>
                            <p className="text-white/80 text-base mb-5 leading-relaxed max-w-2xl">
                                {course.description || 'No description available.'}
                            </p>

                            {/* Stats row */}
                            <div className="flex flex-wrap items-center gap-5 text-sm text-white/80">
                                <span className="flex items-center gap-1.5">
                                    <BookOpen size={15} />
                                    {course.total_lessons_count} lessons
                                </span>
                                <span className="flex items-center gap-1.5">
                                    <Clock size={15} />
                                    {estimateDuration(course.total_lessons_count)}
                                </span>
                                {parseFloat(course.avg_rating) > 0 && (
                                    <span className="flex items-center gap-1.5">
                                        <Star size={15} className="fill-amber-300 text-amber-300" />
                                        {course.avg_rating}
                                    </span>
                                )}
                            </div>
                        </div>

                        {/* Right: CTA card (desktop) */}
                        <div className="hidden md:block w-72 shrink-0">
                            <CtaCard
                                course={course}
                                isEnrolled={isEnrolled}
                                enrolling={enrolling}
                                onStart={handleStartAssessment}
                                onGeneratePathway={handleGeneratePathway}
                                enrollment={enrollment}
                                courseId={id}
                                onRatingSubmit={(avg) => setCourse((prev) => prev ? { ...prev, avg_rating: String(avg) } : prev)}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Body ────────────────────────────────────────────────────── */}
            <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col md:flex-row gap-8">
                {/* Main content */}
                <div className="flex-1 space-y-8">

                    {/* Tags */}
                    {course.tags?.length > 0 && (
                        <div className="flex flex-wrap gap-2 items-center">
                            <Tag size={15} className="text-muted-foreground" />
                            {course.tags.map((tag, i) => (
                                <span key={i} className="px-2.5 py-1 bg-muted rounded-lg text-xs text-muted-foreground font-medium">
                                    {tag}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* What you'll learn */}
                    {syllabus.length > 0 && (
                        <section className="bg-card rounded-2xl border border-border p-6">
                            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                                <GraduationCap size={20} className="text-secondary" />
                                What you'll learn
                            </h2>
                            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                {syllabus.map((item, i) => (
                                    <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                                        <CheckCircle size={16} className="text-emerald-500 mt-0.5 shrink-0" />
                                        {item}
                                    </li>
                                ))}
                            </ul>
                        </section>
                    )}

                    {/* Course content accordion */}
                    <section>
                        <h2 className="text-lg font-semibold mb-4">
                            Course Content
                            <span className="ml-2 text-sm font-normal text-muted-foreground">
                                ({modules.length} modules · {course.total_lessons_count} lessons)
                            </span>
                        </h2>

                        {modules.length === 0 && (
                            <div className="bg-card rounded-2xl border border-border p-8 text-center text-muted-foreground text-sm">
                                No modules available yet.
                            </div>
                        )}

                        <div className="space-y-2">
                            {modules.map((mod) => {
                                const isOpen = expandedModules.has(mod.id);
                                const lessons = lessonMap[mod.id] ?? [];
                                return (
                                    <div key={mod.id} className="bg-card rounded-2xl border border-border overflow-hidden">
                                        <button
                                            onClick={() => toggleModule(mod.id)}
                                            className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-muted/40 transition-colors"
                                        >
                                            <span className="font-medium text-sm">{mod.title}</span>
                                            <ChevronDown
                                                size={18}
                                                className={`text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''}`}
                                            />
                                        </button>

                                        {isOpen && (
                                            <div className="border-t border-border divide-y divide-border">
                                                {lessons.length === 0 && (
                                                    <p className="px-5 py-3 text-xs text-muted-foreground">Loading…</p>
                                                )}
                                                {lessons.map((lesson) => {
                                                    const done = completedLessonIds.has(lesson.id);
                                                    const isCurrent = enrollment?.current_lesson === lesson.id;
                                                    return (
                                                        <div key={lesson.id} className={`flex items-center gap-3 px-5 py-3 ${isCurrent ? 'bg-secondary/5' : ''}`}>
                                                            {done ? (
                                                                <CheckCircle size={14} className="text-emerald-500 shrink-0" />
                                                            ) : (
                                                                <Lock size={14} className="text-muted-foreground shrink-0" />
                                                            )}
                                                            <span className={`text-sm flex-1 ${done ? 'text-foreground' : 'text-muted-foreground'}`}>
                                                                {lesson.title}
                                                            </span>
                                                            {isCurrent && (
                                                                <span className="text-xs px-2 py-0.5 bg-secondary/10 text-secondary rounded-full font-medium">
                                                                    Current
                                                                </span>
                                                            )}
                                                            {done && (
                                                                <span className="text-xs text-emerald-500 font-medium">Done</span>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </section>
                </div>

                {/* Sidebar CTA (mobile / sticky desktop) */}
                <div className="md:hidden">
                    <CtaCard
                        course={course}
                        isEnrolled={isEnrolled}
                        enrolling={enrolling}
                        onStart={handleStartAssessment}
                        onGeneratePathway={handleGeneratePathway}
                        enrollment={enrollment}
                        courseId={id}
                        onRatingSubmit={(avg) => setCourse((prev) => prev ? { ...prev, avg_rating: String(avg) } : prev)}
                    />
                </div>
            </div>
        </div>
    );
}

// ── CTA card sub-component ────────────────────────────────────────────────────

function CtaCard({
    course,
    isEnrolled,
    enrolling,
    onStart,
    onGeneratePathway,
    enrollment,
    courseId,
    onRatingSubmit,
}: {
    course: Course;
    isEnrolled: boolean;
    enrolling: boolean;
    onStart: () => void;
    onGeneratePathway: () => void;
    enrollment: EnrollmentInfo | null;
    courseId: number;
    onRatingSubmit?: (newAvg: number) => void;
}) {
    const [hoveredStar, setHoveredStar] = useState(0);
    const [submittedRating, setSubmittedRating] = useState(0);
    const [ratingLoading, setRatingLoading] = useState(false);

    const handleRate = async (rating: number) => {
        if (ratingLoading) return;
        setRatingLoading(true);
        try {
            const res = await submitCourseRating(courseId, rating);
            setSubmittedRating(rating);
            onRatingSubmit?.(res.avg_rating);
            toast.success(`Rated ${rating} star${rating !== 1 ? 's' : ''}!`);
        } catch {
            toast.error('Failed to submit rating. Try again.');
        } finally {
            setRatingLoading(false);
        }
    };

    return (
        <div className="bg-card rounded-2xl border border-border shadow-lg p-6 space-y-4">
            {/* Price */}
            <div className="text-center">
                {parseFloat(course.price) === 0 ? (
                    <span className="text-3xl font-bold text-emerald-600">Free</span>
                ) : (
                    <span className="text-3xl font-bold text-foreground">${course.price}</span>
                )}
            </div>

            {/* Stats */}
            <ul className="space-y-2 text-sm text-muted-foreground">
                <li className="flex items-center gap-2">
                    <BookOpen size={15} className="text-secondary" />
                    {course.total_lessons_count} lessons
                </li>
                <li className="flex items-center gap-2">
                    <Clock size={15} className="text-secondary" />
                    {estimateDuration(course.total_lessons_count)} estimated
                </li>
                <li className="flex items-center gap-2">
                    <GraduationCap size={15} className="text-secondary" />
                    {course.difficulty} level
                </li>
            </ul>

            {/* CTA button */}
            {isEnrolled ? (
                <button
                    onClick={onStart}
                    disabled={enrolling}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold text-sm hover:shadow-lg transition-all disabled:opacity-60"
                >
                    {enrolling ? (
                        <><Loader2 size={16} className="animate-spin" /> Loading…</>
                    ) : (
                        <>
                            {enrollment?.is_pathway_ready 
                                ? 'Continue Learning' 
                                : enrollment?.is_assessment_started 
                                    ? 'Resume Assessment' 
                                    : 'Start Assessment'} 
                            <ChevronRight size={16} />
                        </>
                    )}
                </button>
            ) : (
                <button
                    onClick={onStart}
                    disabled={enrolling}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-primary to-secondary text-white rounded-xl font-semibold text-sm hover:shadow-lg transition-all disabled:opacity-60"
                >
                    {enrolling ? (
                        <><Loader2 size={16} className="animate-spin" /> Enrolling…</>
                    ) : (
                        <>Start Assessment & Enroll <ChevronRight size={16} /></>
                    )}
                </button>
            )}

            {/* Capstone entry — appears once the coursework is finished */}
            {isEnrolled && enrollment && parseFloat(enrollment.progress_percentage ?? '0') >= 100 && (
                <CapstoneStartCTA courseId={courseId} variant="card" />
            )}

            {/* Star rating — enrolled students only */}
            {isEnrolled && (
                <div className="pt-1">
                    <p className="text-xs text-muted-foreground text-center mb-2">
                        {submittedRating > 0 ? 'Your rating' : 'Rate this course'}
                    </p>
                    <div className="flex justify-center gap-1">
                        {[1, 2, 3, 4, 5].map((star) => (
                            <button
                                key={star}
                                disabled={ratingLoading}
                                onClick={() => handleRate(star)}
                                onMouseEnter={() => setHoveredStar(star)}
                                onMouseLeave={() => setHoveredStar(0)}
                                className="transition-transform hover:scale-110 disabled:opacity-50"
                            >
                                <Star
                                    size={22}
                                    className={
                                        star <= (hoveredStar || submittedRating)
                                            ? 'fill-amber-400 text-amber-400'
                                            : 'text-muted-foreground'
                                    }
                                />
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* Generate Pathway button */}
            <button
                onClick={onGeneratePathway}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 border-2 border-secondary text-secondary rounded-xl font-semibold text-sm hover:bg-secondary/5 transition-all"
            >
                Generate Pathway
                <ChevronRight size={16} />
            </button>

            {!isEnrolled && (
                <p className="text-xs text-center text-muted-foreground">
                    A short placement quiz helps us personalise your learning path.
                </p>
            )}
        </div>
    );
}
