import {
  Plus,
  Edit,
  Trash2,
  Users,
  BookOpen,
  BarChart,
  TrendingUp,
  Clock,
  Search,
  Eye,
  Loader2,
  X,
  Check,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { useNavigate } from 'react-router';
import {
  getAdminStats, getAdminCourses, createCourse, updateCourse, deleteCourse,
  type AdminStats, type AdminCourse,
} from '../../services/admin';

const DIFFICULTIES = ['Beginner', 'Intermediate', 'Advanced'];
const STATUSES = ['Draft', 'Published', 'Archived'];

const emptyForm = { title: '', description: '', difficulty: 'Beginner', status: 'Draft', tags: [] as string[] };

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');

  const [showForm, setShowForm] = useState(false);
  const [editingCourse, setEditingCourse] = useState<AdminCourse | null>(null);
  const [previewCourse, setPreviewCourse] = useState<AdminCourse | null>(null);
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
    setForm({ title: course.title, description: course.description, difficulty: course.difficulty, status: course.status, tags: course.tags ?? [] });
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
    if (!confirm('Are you sure you want to delete this course? This action cannot be undone.')) return;
    setDeletingId(id);
    try {
      await deleteCourse(id);
      setCourses(cs => cs.filter(c => c.id !== id));
      toast.success('Course deleted');
    } catch (err: any) {
      const message = err?.response?.data?.detail || err?.response?.data?.error || err?.message || 'Failed to delete course';
      toast.error(message);
    } finally {
      setDeletingId(null);
    }
  };

  const getDifficultyBadge = (difficulty: string) => {
    if (difficulty === 'Beginner') return 'admin-badge admin-badge-green';
    if (difficulty === 'Intermediate') return 'admin-badge admin-badge-amber';
    return 'admin-badge admin-badge-gray';
  };

  const getStatusBadge = (status: string) => {
    if (status === 'Published') return 'admin-badge admin-badge-blue';
    if (status === 'Draft') return 'admin-badge admin-badge-amber';
    return 'admin-badge admin-badge-gray';
  };

  if (loading) return (
    <div className="flex-1 flex items-center justify-center min-h-[60vh]">
      <div className="admin-loading-spinner" />
    </div>
  );

  return (
    <div className="admin-animate-page">
      {/* Page header */}
      <div className="mb-10">
        <h1 className="admin-heading-md mb-3">Platform overview.</h1>
        <p className="admin-body-lg max-w-2xl">
          Live status, recent activity, and key metrics for the learning platform.
        </p>
      </div>


      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        {[
          { label: 'Total Students', value: stats?.total_students ?? 0, icon: Users },
          { label: 'Active Courses', value: stats?.active_courses ?? 0, icon: BookOpen },
          { label: 'Avg. Completion', value: `${stats?.avg_completion ?? 0}%`, icon: BarChart },
          { label: 'Total Enrollments', value: stats?.total_enrollments ?? 0, icon: TrendingUp },
        ].map((stat, i) => {
          const Icon = stat.icon;
          return (
            <div key={i} className="admin-card p-6 hover:border-[var(--admin-accent)] transition-colors duration-200">
              <Icon size={24} className="text-[var(--admin-accent)] mb-4" />
              <p className="admin-heading-xs mb-1">{stat.value}</p>
              <p className="admin-body-sm">{stat.label}</p>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Course Management */}
        <div className="lg:col-span-2">
          <div className="admin-card">
            <div className="px-6 py-5 border-b border-[var(--admin-hairline)] flex items-center justify-between">
              <div>
                <h2 className="admin-heading-xs">Course Management</h2>
                <p className="admin-body-sm mt-1">{courses.length} courses total</p>
              </div>
              <button onClick={openCreate} className="admin-btn admin-btn-primary">
                <Plus size={16} />
                <span>New Course</span>
              </button>
            </div>

            <div className="px-6 py-4 border-b border-[var(--admin-hairline)] bg-[var(--admin-paper-muted)] flex gap-4">
              <div className="flex-1 relative">
                <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--admin-ink-tertiary)] pointer-events-none" />
                <input
                  type="text"
                  placeholder="Search courses..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  className="admin-input pl-11 w-full"
                />
              </div>
              <div className="relative flex-shrink-0 min-w-[200px]">
                <select
                  value={filterStatus}
                  onChange={e => setFilterStatus(e.target.value)}
                  className="admin-input admin-select w-full"
                >
                  <option value="all">All Status</option>
                  {STATUSES.map(s => <option key={s} value={s.toLowerCase()}>{s}</option>)}
                </select>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Course</th>
                    <th>Difficulty</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCourses.map(course => (
                    <tr key={course.id}>
                      <td>
                        <p className="font-[family-name:var(--admin-font-display)] font-semibold text-[14px] text-[var(--admin-ink)]">{course.title}</p>
                        <p className="admin-body-sm">{course.description?.slice(0, 60) || 'No description'}{course.description?.length > 60 ? '…' : ''}</p>
                      </td>
                      <td><span className={getDifficultyBadge(course.difficulty)}>{course.difficulty}</span></td>
                      <td><span className={getStatusBadge(course.status)}>{course.status}</span></td>
                      <td>
                        <div className="flex gap-2">
                          <button onClick={() => setPreviewCourse(course)} className="admin-btn admin-btn-ghost admin-btn-icon" title="Preview Course">
                            <Eye size={16} />
                          </button>
                          <button onClick={() => openEdit(course)} className="admin-btn admin-btn-ghost admin-btn-icon" title="Edit Details">
                            <Edit size={16} />
                          </button>
                          <button
                            onClick={() => handleDelete(course.id)}
                            disabled={deletingId === course.id}
                            className="admin-btn admin-btn-ghost-danger admin-btn-icon"
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
                  <BookOpen size={48} className="mx-auto mb-4 text-[var(--admin-ink-tertiary)] opacity-50" />
                  <p className="admin-body-md">No courses found</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right sidebar */}
        <div className="space-y-6">
          <button
            onClick={() => navigate('/admin/students')}
            className="w-full admin-card-dark p-6 text-left hover:shadow-lg transition-shadow"
          >
            <Users size={32} className="mb-3 opacity-90" />
            <h3 className="admin-heading-xs text-white mb-1">Manage Students</h3>
            <p className="admin-body-sm text-white/80">View all {stats?.total_students ?? 0} students, their progress, XP and achievements.</p>
          </button>

          <div className="admin-card">
            <div className="px-6 py-4 border-b border-[var(--admin-hairline)]">
              <h3 className="admin-heading-xs flex items-center gap-2">
                <Clock size={18} className="text-[var(--admin-accent)]" />
                Recent Enrollments
              </h3>
            </div>
            <div className="p-4 space-y-3">
              {stats?.recent_enrollments.length === 0 && (
                <p className="admin-body-sm text-center py-4">No enrollments yet</p>
              )}
              {stats?.recent_enrollments.map((e, i) => (
                <div key={i} className="flex items-start gap-3 pb-3 border-b border-[var(--admin-hairline-light)] last:border-0 last:pb-0">
                  <div className="w-2 h-2 rounded-full bg-[var(--admin-accent)] mt-2 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] mb-0.5 text-[var(--admin-ink)]">
                      <span className="font-semibold">{e.student}</span>
                      <span className="text-[var(--admin-ink-secondary)]"> enrolled in </span>
                      <span className="font-semibold text-[var(--admin-accent)]">{e.course}</span>
                    </p>
                    <p className="admin-body-sm">{new Date(e.enrolled_at).toLocaleDateString()}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="admin-card-dark p-6">
            <h3 className="admin-heading-xs text-white mb-4">Platform Summary</h3>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="admin-body-sm text-white/90">Total Courses</span>
                <span className="admin-heading-xs text-white">{stats?.total_courses ?? 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="admin-body-sm text-white/90">Completed Lessons</span>
                <span className="admin-heading-xs text-white">{stats?.completed_lessons ?? 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="admin-body-sm text-white/90">Avg. Completion</span>
                <span className="admin-heading-xs text-white">{stats?.avg_completion ?? 0}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Course Preview Modal */}
      {previewCourse && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="admin-card w-full max-w-lg shadow-2xl">
            <div className="px-6 py-4 border-b border-[var(--admin-hairline)] flex items-center justify-between">
              <h3 className="admin-heading-xs">Course Preview</h3>
              <button onClick={() => setPreviewCourse(null)} className="admin-btn admin-btn-ghost admin-btn-icon">
                <X size={20} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="admin-input-label">Title</label>
                <p className="admin-body-md">{previewCourse.title}</p>
              </div>
              <div>
                <label className="admin-input-label">Description</label>
                <p className="admin-body-md">{previewCourse.description || 'No description'}</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="admin-input-label">Difficulty</label>
                  <p className="admin-body-md">{previewCourse.difficulty}</p>
                </div>
                <div>
                  <label className="admin-input-label">Status</label>
                  <p className="admin-body-md">{previewCourse.status}</p>
                </div>
              </div>
              {previewCourse.tags.length > 0 && (
                <div>
                  <label className="admin-input-label">Tags</label>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {previewCourse.tags.map(tag => (
                      <span key={tag} className="admin-badge admin-badge-ghost-gray text-xs px-2 py-1">{tag}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-[var(--admin-hairline)] flex gap-3 justify-end">
              <button onClick={() => setPreviewCourse(null)} className="admin-btn admin-btn-ghost">Close</button>
              <button onClick={() => { setPreviewCourse(null); navigate(`/admin/courses/${previewCourse.id}/editor`); }} className="admin-btn admin-btn-primary">Open Editor</button>
            </div>
          </div>
        </div>
      )}

      {/* Course Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="admin-card w-full max-w-lg shadow-2xl">
            <div className="px-6 py-4 border-b border-[var(--admin-hairline)] flex items-center justify-between">
              <h3 className="admin-heading-xs">{editingCourse ? 'Edit Course' : 'New Course'}</h3>
              <button onClick={() => setShowForm(false)} className="admin-btn admin-btn-ghost admin-btn-icon">
                <X size={20} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="admin-input-label">Title</label>
                <input
                  type="text"
                  value={form.title}
                  onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  placeholder="e.g. Python for Data Science"
                  className="admin-input"
                />
              </div>
              <div>
                <label className="admin-input-label">Description</label>
                <textarea
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="Brief course description..."
                  rows={3}
                  className="admin-input resize-none"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="admin-input-label">Difficulty</label>
                  <select
                    value={form.difficulty}
                    onChange={e => setForm(f => ({ ...f, difficulty: e.target.value }))}
                    className="admin-input admin-select"
                  >
                    {DIFFICULTIES.map(d => <option key={d}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label className="admin-input-label">Status</label>
                  <select
                    value={form.status}
                    onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
                    className="admin-input admin-select"
                  >
                    {STATUSES.map(s => <option key={s}>{s}</option>)}
                  </select>
                </div>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-[var(--admin-hairline)] flex gap-3 justify-end">
              <button onClick={() => setShowForm(false)} className="admin-btn admin-btn-ghost">
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="admin-btn admin-btn-primary disabled:opacity-60"
              >
                {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                {editingCourse ? 'Save Changes' : 'Create Course'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
