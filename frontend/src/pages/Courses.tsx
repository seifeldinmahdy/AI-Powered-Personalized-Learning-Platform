import { Header } from '../components/Header';
import { Search, Filter, BookOpen, Clock, Star, ChevronRight, Loader2, GraduationCap } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';
import { getCourses, Course } from '../services/courses';
import { Link, useSearchParams } from 'react-router';

const DIFFICULTY_OPTIONS = ['All', 'Beginner', 'Intermediate', 'Advanced'];
const SORT_OPTIONS = [
    { label: 'Newest', value: '-created_at' },
    { label: 'Title A–Z', value: 'title' },
    { label: 'Price ↑', value: 'price' },
    { label: 'Rating ↓', value: '-avg_rating' },
];

export default function Courses() {
    const [searchParams] = useSearchParams();
    const [courses, setCourses] = useState<Course[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState(searchParams.get('search') || '');
    const [difficulty, setDifficulty] = useState('All');
    const [ordering, setOrdering] = useState('-created_at');
    const [totalCount, setTotalCount] = useState(0);

    const fetchCourses = useCallback(async () => {
        setLoading(true);
        try {
            const params: Record<string, string> = { ordering };
            if (search.trim()) params.search = search.trim();
            if (difficulty !== 'All') params.difficulty = difficulty;
            const data = await getCourses(params);
            setCourses(data.results);
            setTotalCount(data.count);
        } catch {
            setCourses([]);
            setTotalCount(0);
        } finally {
            setLoading(false);
        }
    }, [search, difficulty, ordering]);

    useEffect(() => {
        const timeout = setTimeout(fetchCourses, 300);
        return () => clearTimeout(timeout);
    }, [fetchCourses]);

    const difficultyColor = (d: string) => {
        switch (d) {
            case 'Beginner': return 'bg-emerald-100 text-emerald-700';
            case 'Intermediate': return 'bg-amber-100 text-amber-700';
            case 'Advanced': return 'bg-rose-100 text-rose-700';
            default: return 'bg-muted text-muted-foreground';
        }
    };

    return (
        <>
            <Header title="Browse Courses" subtitle={`${totalCount} courses available`} />

            <div className="flex-1 overflow-y-auto">
                <div className="p-8 max-w-7xl mx-auto">
                    {/* Search & Filters */}
                    <div className="bg-card rounded-2xl shadow-sm border border-border p-6 mb-8">
                        <div className="flex flex-col md:flex-row gap-4">
                            {/* Search Bar */}
                            <div className="flex-1 relative">
                                <Search size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
                                <input
                                    type="text"
                                    placeholder="Search courses by title, description, or tags..."
                                    value={search}
                                    onChange={(e) => setSearch(e.target.value)}
                                    className="w-full pl-12 pr-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors text-sm"
                                />
                            </div>

                            {/* Difficulty Filter */}
                            <div className="flex items-center gap-2">
                                <Filter size={18} className="text-muted-foreground flex-shrink-0" />
                                <div className="flex gap-1.5">
                                    {DIFFICULTY_OPTIONS.map((opt) => (
                                        <button
                                            key={opt}
                                            onClick={() => setDifficulty(opt)}
                                            className={`px-3.5 py-2 rounded-lg text-xs font-semibold transition-all ${difficulty === opt
                                                ? 'bg-gradient-to-r from-secondary to-accent text-white shadow-md'
                                                : 'bg-muted/50 text-muted-foreground hover:bg-muted'
                                                }`}
                                        >
                                            {opt}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Sort */}
                            <select
                                value={ordering}
                                onChange={(e) => setOrdering(e.target.value)}
                                className="px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary text-sm cursor-pointer"
                            >
                                {SORT_OPTIONS.map((opt) => (
                                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                                ))}
                            </select>
                        </div>
                    </div>

                    {/* Loading */}
                    {loading && (
                        <div className="flex justify-center py-20">
                            <Loader2 size={40} className="animate-spin text-secondary" />
                        </div>
                    )}

                    {/* Empty State */}
                    {!loading && courses.length === 0 && (
                        <div className="flex flex-col items-center justify-center py-20 text-center">
                            <div className="w-20 h-20 rounded-2xl bg-muted/50 flex items-center justify-center mb-6">
                                <BookOpen size={40} className="text-muted-foreground" />
                            </div>
                            <h3 className="mb-2">No courses found</h3>
                            <p className="text-muted-foreground text-sm max-w-md">
                                {search ? `No results for "${search}". Try a different search term or filter.` : 'No courses available yet — check back soon!'}
                            </p>
                        </div>
                    )}

                    {/* Courses Grid */}
                    {!loading && courses.length > 0 && (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            {courses.map((course) => (
                                <div
                                    key={course.id}
                                    className="bg-card rounded-2xl shadow-sm border border-border overflow-hidden hover:shadow-lg hover:border-secondary/40 transition-all group"
                                >
                                    {/* Card Header Gradient */}
                                    <div className="h-36 bg-gradient-to-br from-primary via-secondary to-accent relative overflow-hidden">
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            <GraduationCap size={56} className="text-white/20" />
                                        </div>
                                        <div className="absolute top-4 left-4">
                                            <span className={`px-2.5 py-1 rounded-lg text-xs font-bold ${difficultyColor(course.difficulty)}`}>
                                                {course.difficulty}
                                            </span>
                                        </div>
                                        {parseFloat(course.price) > 0 && (
                                            <div className="absolute top-4 right-4 bg-white/20 backdrop-blur-sm px-3 py-1 rounded-lg">
                                                <span className="text-white text-sm font-bold">${course.price}</span>
                                            </div>
                                        )}
                                        {parseFloat(course.price) === 0 && (
                                            <div className="absolute top-4 right-4 bg-emerald-500/90 backdrop-blur-sm px-3 py-1 rounded-lg">
                                                <span className="text-white text-xs font-bold">FREE</span>
                                            </div>
                                        )}
                                    </div>

                                    {/* Card Body */}
                                    <div className="p-5">
                                        <h4 className="mb-2 group-hover:text-secondary transition-colors line-clamp-1">{course.title}</h4>
                                        <p className="text-sm text-muted-foreground mb-4 line-clamp-2 min-h-[2.5rem]">
                                            {course.description || 'No description available.'}
                                        </p>

                                        {/* Stats Row */}
                                        <div className="flex items-center gap-4 mb-4 text-xs text-muted-foreground">
                                            <div className="flex items-center gap-1">
                                                <BookOpen size={14} />
                                                <span>{course.total_lessons_count} lessons</span>
                                            </div>
                                            <div className="flex items-center gap-1">
                                                <Star size={14} className="text-amber-400 fill-amber-400" />
                                                <span>{parseFloat(course.avg_rating) > 0 ? course.avg_rating : '—'}</span>
                                            </div>
                                            {course.instructor_name && (
                                                <div className="flex items-center gap-1">
                                                    <Clock size={14} />
                                                    <span>{course.instructor_name}</span>
                                                </div>
                                            )}
                                        </div>

                                        {/* Tags */}
                                        {course.tags && course.tags.length > 0 && (
                                            <div className="flex flex-wrap gap-1.5 mb-4">
                                                {course.tags.slice(0, 3).map((tag, i) => (
                                                    <span key={i} className="px-2 py-0.5 bg-muted/50 rounded text-xs text-muted-foreground">
                                                        {tag}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {/* CTA */}
                                        <Link
                                            to={`/course/${course.id}/lesson/1`}
                                            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold text-sm hover:shadow-lg transition-all group-hover:shadow-md"
                                        >
                                            <span>View Course</span>
                                            <ChevronRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
                                        </Link>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </>
    );
}
