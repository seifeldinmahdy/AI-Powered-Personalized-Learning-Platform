import { Header } from '../../components/Header';
import {
    Plus, Edit, Trash2, Users, BookOpen, BarChart, TrendingUp,
    Clock, Search, Filter, Eye, Loader2, X, Check, FolderOpen,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import {
    getAdminStats, getAdminCourses, createCourse, updateCourse, deleteCourse,
    type AdminStats, type AdminCourse,
} from '../../services/admin';
import { useNavigate } from 'react-router';

const DIFFICULTIES = ['Beginner', 'Intermediate', 'Advanced'];
const STATUSES = ['Draft', 'Published', 'Archived'];

const emptyForm = { title: '', description: '', difficulty: 'Beginner', status: 'Draft', price: '0.00', tags: [] as string[] };

export default function AdminDashboard() {
    const navigate = useNavigate();
    const [stats, setStats] = useState<AdminStats | null>(null);
    const [courses, setCourses] = useState<AdminCourse[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [filterStatus, setFilterStatus] = useState('all');

    // Course form state
    const [showForm, setShowForm] = useState(false);
    const [editingCourse, setEditingCourse] = useState<AdminCourse | null>(null);
    const [form, setForm] = useState(emptyForm);
    const [saving, setSaving] = useState(false);
    const [deletingId, setDeletingId] = useState<number | null>(null);

    useEffect(() => {
        Promise.all([getAdminStats(), getAdminCourses()])
            .then(([s, c]) => { setStats(s); setCourses(c); })
            .catch(() => toast.error('Failed to load dashboard data'))
            .finally(() => setLoading(false));
    }, []);

    const filteredCourses = courses.filter(c => {
        const matchesSearch = c.title.toLowerCase().includes(searchQuery.toLowerCase());
        const matchesFilter = filterStatus === 'all' || c.status.toLowerCase() === filterStatus.toLowerCase();
        return matchesSearch && matchesFilter;
    });

    const openCreate = () => { setEditingCourse(null); setForm(emptyForm); setShowForm(true); };
    const openEdit = (course: AdminCourse) => {
        setEditingCourse(course);
        setForm({ title: course.title, description: course.description, difficulty: course.difficulty, status: course.status, price: course.price, tags: course.tags ?? [] });
        setShowForm(true);
    };

    const handleSave = async () => {
        if (!form.title.trim()) { toast.error('Course title is required'); return; }
        setSaving(true);
        try {
            if (editingCourse) {
                const updated = await updateCourse(editingCourse.id, form);
                setCourses(cs => cs.map(c => c.id === updated.id ? updated : c));
                toast.success('Course updated');
            } else {
                const created = await createCourse(form);
                setCourses(cs => [created, ...cs]);
                toast.success('Course created');
            }
            setShowForm(false);
        } catch {
            toast.error('Failed to save course');
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (id: number) => {
        setDeletingId(id);
        try {
            await deleteCourse(id);
            setCourses(cs => cs.filter(c => c.id !== id));
            toast.success('Course deleted');
        } catch {
            toast.error('Failed to delete course');
        } finally {
            setDeletingId(null);
        }
    };

    const statCards = stats ? [
        { label: 'Total Students', value: stats.total_students, icon: Users, color: 'from-secondary to-accent' },
        { label: 'Active Courses', value: stats.active_courses, icon: BookOpen, color: 'from-accent to-primary' },
        { label: 'Avg. Completion', value: `${stats.avg_completion}%`, icon: BarChart, color: 'from-primary to-secondary' },
        { label: 'Total Enrollments', value: stats.total_enrollments, icon: TrendingUp, color: 'from-secondary to-accent' },
    ] : [];

    if (loading) return (
        <>
            <Header title="Admin Dashboard" subtitle="Manage courses, students, and content" />
            <div className="flex-1 flex items-center justify-center">
                <Loader2 size={40} className="animate-spin text-secondary" />
            </div>
        </>
    );

    return (
        <>
            <Header title="Admin Dashboard" subtitle="Manage courses, students, and content" />
            <div className="flex-1 overflow-y-auto">
                <div className="p-8 max-w-[1600px] mx-auto">

                    {/* Stats */}
                    <section className="mb-8">
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            {statCards.map((stat, i) => {
                                const Icon = stat.icon;
                                return (
                                    <div key={i} className="bg-card rounded-2xl border-2 border-border p-6 hover:shadow-lg hover:border-secondary/30 transition-all group">
                                        <div className="flex items-start justify-between mb-4">
                                            <div className={`w-14 h-14 rounded-xl bg-gradient-to-br ${stat.color} flex items-center justify-center shadow-lg group-hover:scale-110 transition-transform`}>
                                                <Icon size={28} className="text-white" />
                                            </div>
                                        </div>
                                        <h2 className="mb-1">{stat.value}</h2>
                                        <p className="text-sm text-muted-foreground">{stat.label}</p>
                                    </div>
                                );
                            })}
                        </div>
                    </section>

                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        {/* Course Management */}
                        <div className="lg:col-span-2 space-y-6">
                            <div className="bg-card rounded-2xl border-2 border-border overflow-hidden">
                                <div className="px-6 py-5 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h3 className="mb-1">Course Management</h3>
                                            <p className="text-sm text-muted-foreground">{courses.length} courses total</p>
                                        </div>
                                        <button
                                            onClick={openCreate}
                                            className="px-5 py-2.5 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-2 group"
                                        >
                                            <Plus size={18} className="group-hover:rotate-90 transition-transform" />
                                            <span>New Course</span>
                                        </button>
                                    </div>
                                </div>

                                {/* Search & Filter */}
                                <div className="px-6 py-4 border-b border-border bg-muted/30 flex gap-4">
                                    <div className="flex-1 relative">
                                        <Search size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
                                        <input
                                            type="text"
                                            placeholder="Search courses..."
                                            value={searchQuery}
                                            onChange={e => setSearchQuery(e.target.value)}
                                            className="w-full pl-12 pr-4 py-2.5 bg-background border-2 border-border rounded-xl focus:outline-none focus:border-secondary transition-colors"
                                        />
                                    </div>
                                    <div className="relative">
                                        <Filter size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
                                        <select
                                            value={filterStatus}
                                            onChange={e => setFilterStatus(e.target.value)}
                                            className="pl-12 pr-8 py-2.5 bg-background border-2 border-border rounded-xl focus:outline-none focus:border-secondary transition-colors appearance-none cursor-pointer"
                                        >
                                            <option value="all">All Status</option>
                                            {STATUSES.map(s => <option key={s} value={s.toLowerCase()}>{s}</option>)}
                                        </select>
                                    </div>
                                </div>

                                {/* Table */}
                                <div className="overflow-x-auto">
                                    <table className="w-full">
                                        <thead className="bg-muted/50 border-b-2 border-border">
                                            <tr>
                                                <th className="px-6 py-4 text-left text-sm font-semibold">Course</th>
                                                <th className="px-6 py-4 text-left text-sm font-semibold">Difficulty</th>
                                                <th className="px-6 py-4 text-left text-sm font-semibold">Lessons</th>
                                                <th className="px-6 py-4 text-left text-sm font-semibold">Status</th>
                                                <th className="px-6 py-4 text-left text-sm font-semibold">Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {filteredCourses.map(course => (
                                                <tr key={course.id} className="border-b border-border hover:bg-muted/30 transition-colors group">
                                                    <td className="px-6 py-4">
                                                        <h5 className="mb-0.5 group-hover:text-secondary transition-colors">{course.title}</h5>
                                                        <p className="text-xs text-muted-foreground">${course.price}</p>
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <span className={`px-2.5 py-1 rounded-lg text-xs font-semibold ${
                                                            course.difficulty === 'Beginner' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
                                                            course.difficulty === 'Intermediate' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
                                                            'bg-rose-50 text-rose-700 border border-rose-200'
                                                        }`}>{course.difficulty}</span>
                                                    </td>
                                                    <td className="px-6 py-4 font-mono font-semibold">{course.total_lessons_count}</td>
                                                    <td className="px-6 py-4">
                                                        <span className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                                                            course.status === 'Published' ? 'bg-green-50 text-green-700 border border-green-200' :
                                                            course.status === 'Draft' ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' :
                                                            'bg-gray-50 text-gray-600 border border-gray-200'
                                                        }`}>{course.status}</span>
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <div className="flex gap-2">
                                                            <button onClick={() => navigate(`/courses/${course.id}`)} className="p-2 rounded-lg border-2 border-border hover:border-secondary hover:bg-secondary/5 transition-all" title="View">
                                                                <Eye size={16} />
                                                            </button>
                                                            <button onClick={() => openEdit(course)} className="p-2 rounded-lg border-2 border-border hover:border-accent hover:bg-accent/5 transition-all" title="Edit">
                                                                <Edit size={16} />
                                                            </button>
                                                            <button onClick={() => navigate(`/admin/courses/${course.id}/editor`)} className="p-2 rounded-lg border-2 border-border hover:border-primary hover:bg-primary/5 transition-all" title="Manage Content">
                                                                <FolderOpen size={16} />
                                                            </button>
                                                            <button
                                                                onClick={() => handleDelete(course.id)}
                                                                disabled={deletingId === course.id}
                                                                className="p-2 rounded-lg border-2 border-border hover:border-destructive hover:bg-destructive/5 hover:text-destructive transition-all disabled:opacity-50"
                                                                title="Delete"
                                                            >
                                                                {deletingId === course.id ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                                                            </button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                    {filteredCourses.length === 0 && (
                                        <div className="px-6 py-12 text-center">
                                            <BookOpen size={48} className="mx-auto mb-4 text-muted-foreground opacity-50" />
                                            <p className="text-muted-foreground">No courses found</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Right Sidebar */}
                        <div className="space-y-6">
                            {/* Students quick link */}
                            <button
                                onClick={() => navigate('/admin/students')}
                                className="w-full bg-gradient-to-br from-secondary to-accent rounded-2xl p-6 text-white shadow-xl hover:shadow-2xl transition-all text-left"
                            >
                                <Users size={32} className="mb-3 opacity-90" />
                                <h4 className="text-white mb-1">Manage Students</h4>
                                <p className="text-white/80 text-sm">View all {stats?.total_students ?? 0} students, their progress, XP and achievements</p>
                            </button>

                            {/* Recent Activity */}
                            <div className="bg-card rounded-2xl border-2 border-border overflow-hidden">
                                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5">
                                    <h4 className="mb-0 flex items-center gap-2">
                                        <Clock size={20} className="text-primary" />
                                        Recent Enrollments
                                    </h4>
                                </div>
                                <div className="p-4 space-y-3">
                                    {stats?.recent_enrollments.length === 0 && (
                                        <p className="text-sm text-muted-foreground text-center py-4">No enrollments yet</p>
                                    )}
                                    {stats?.recent_enrollments.map((e, i) => (
                                        <div key={i} className="flex items-start gap-3 pb-3 border-b border-border last:border-0 last:pb-0">
                                            <div className="w-2 h-2 rounded-full bg-secondary mt-2 flex-shrink-0" />
                                            <div className="flex-1 min-w-0">
                                                <p className="text-sm mb-0.5">
                                                    <span className="font-semibold">{e.student}</span>
                                                    <span className="text-muted-foreground"> enrolled in </span>
                                                    <span className="font-semibold text-secondary">{e.course}</span>
                                                </p>
                                                <p className="text-xs text-muted-foreground">{new Date(e.enrolled_at).toLocaleDateString()}</p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Platform summary */}
                            <div className="bg-gradient-to-br from-primary via-secondary to-accent rounded-2xl p-6 text-white shadow-xl">
                                <h4 className="mb-4 text-white">Platform Summary</h4>
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-white/90">Total Courses</span>
                                        <span className="text-2xl font-bold">{stats?.total_courses ?? 0}</span>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-white/90">Completed Lessons</span>
                                        <span className="text-2xl font-bold">{stats?.completed_lessons ?? 0}</span>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-white/90">Avg. Completion</span>
                                        <span className="text-2xl font-bold">{stats?.avg_completion ?? 0}%</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Course Create/Edit Modal */}
            {showForm && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="bg-card rounded-2xl border-2 border-border w-full max-w-lg shadow-2xl">
                        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
                            <h3 className="mb-0">{editingCourse ? 'Edit Course' : 'New Course'}</h3>
                            <button onClick={() => setShowForm(false)} className="p-2 rounded-lg hover:bg-muted transition-colors">
                                <X size={20} />
                            </button>
                        </div>
                        <div className="p-6 space-y-4">
                            <div>
                                <label className="block mb-1.5 text-sm font-semibold">Title</label>
                                <input
                                    type="text"
                                    value={form.title}
                                    onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                                    placeholder="e.g. Python for Data Science"
                                    className="w-full px-4 py-3 border-2 border-border rounded-xl bg-background focus:outline-none focus:border-secondary transition-colors"
                                />
                            </div>
                            <div>
                                <label className="block mb-1.5 text-sm font-semibold">Description</label>
                                <textarea
                                    value={form.description}
                                    onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                                    placeholder="Brief course description..."
                                    rows={3}
                                    className="w-full px-4 py-3 border-2 border-border rounded-xl bg-background focus:outline-none focus:border-secondary transition-colors resize-none"
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block mb-1.5 text-sm font-semibold">Difficulty</label>
                                    <select
                                        value={form.difficulty}
                                        onChange={e => setForm(f => ({ ...f, difficulty: e.target.value }))}
                                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-background focus:outline-none focus:border-secondary transition-colors"
                                    >
                                        {DIFFICULTIES.map(d => <option key={d}>{d}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="block mb-1.5 text-sm font-semibold">Status</label>
                                    <select
                                        value={form.status}
                                        onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
                                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-background focus:outline-none focus:border-secondary transition-colors"
                                    >
                                        {STATUSES.map(s => <option key={s}>{s}</option>)}
                                    </select>
                                </div>
                            </div>
                            <div>
                                <label className="block mb-1.5 text-sm font-semibold">Price ($)</label>
                                <input
                                    type="number"
                                    min="0"
                                    step="0.01"
                                    value={form.price}
                                    onChange={e => setForm(f => ({ ...f, price: e.target.value }))}
                                    className="w-full px-4 py-3 border-2 border-border rounded-xl bg-background focus:outline-none focus:border-secondary transition-colors"
                                />
                            </div>
                        </div>
                        <div className="px-6 py-4 border-t border-border flex gap-3 justify-end">
                            <button onClick={() => setShowForm(false)} className="px-5 py-2.5 border-2 border-border rounded-xl font-semibold hover:border-secondary transition-colors">
                                Cancel
                            </button>
                            <button
                                onClick={handleSave}
                                disabled={saving}
                                className="px-5 py-2.5 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-2 disabled:opacity-60"
                            >
                                {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                                {editingCourse ? 'Save Changes' : 'Create Course'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
