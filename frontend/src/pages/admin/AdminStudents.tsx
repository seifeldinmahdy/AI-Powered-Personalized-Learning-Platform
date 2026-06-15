import { useState, useEffect, useMemo } from 'react';
import { Search, Loader2, Users, Trophy, Flame, Clock, BookOpen, Star, ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { toast } from 'sonner';
import { getAdminStudents, type AdminStudent } from '../../services/admin';

type StudentSortKey = 'username' | 'current_xp' | 'current_streak' | 'total_minutes_learned' | 'enrollments' | 'achievements' | 'joined';
type SortDir = 'asc' | 'desc';

interface SortState {
  key: StudentSortKey | null;
  dir: SortDir | null;
}

const COLUMN_HEADERS: { key: StudentSortKey; label: string }[] = [
  { key: 'username', label: 'Student' },
  { key: 'current_xp', label: 'Level / XP' },
  { key: 'current_streak', label: 'Streak' },
  { key: 'total_minutes_learned', label: 'Time Learned' },
  { key: 'enrollments', label: 'Enrollments' },
  { key: 'achievements', label: 'Achievements' },
  { key: 'joined', label: 'Joined' },
];

export default function AdminStudents() {
    const [students, setStudents] = useState<AdminStudent[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [sort, setSort] = useState<SortState>({ key: null, dir: null });

    useEffect(() => {
        getAdminStudents()
            .then(setStudents)
            .catch(() => toast.error('Failed to load students'))
            .finally(() => setLoading(false));
    }, []);

    // Reset sort when the search filter changes
    useEffect(() => {
        setSort({ key: null, dir: null });
    }, [search]);

    const handleSort = (key: StudentSortKey) => {
        setSort(prev => {
            if (prev.key !== key) {
                return { key, dir: 'asc' };
            }
            if (prev.dir === 'asc') {
                return { key, dir: 'desc' };
            }
            return { key: null, dir: null };
        });
    };

    const filtered = useMemo(() => {
        let result = students.filter(s =>
            s.username.toLowerCase().includes(search.toLowerCase()) ||
            s.email.toLowerCase().includes(search.toLowerCase())
        );

        if (sort.key && sort.dir) {
            result = [...result].sort((a, b) => {
                let cmp = 0;
                switch (sort.key) {
                    case 'username':
                        cmp = a.username.toLowerCase().localeCompare(b.username.toLowerCase());
                        break;
                    case 'current_xp':
                        cmp = a.current_xp - b.current_xp;
                        break;
                    case 'current_streak':
                        cmp = a.current_streak - b.current_streak;
                        break;
                    case 'total_minutes_learned':
                        cmp = a.total_minutes_learned - b.total_minutes_learned;
                        break;
                    case 'enrollments':
                        cmp = a.enrollments - b.enrollments;
                        break;
                    case 'achievements':
                        cmp = a.achievements - b.achievements;
                        break;
                    case 'joined':
                        cmp = new Date(a.joined).getTime() - new Date(b.joined).getTime();
                        break;
                }
                return sort.dir === 'asc' ? cmp : -cmp;
            });
        }

        return result;
    }, [students, search, sort]);

    const SortHeader = ({ column }: { column: { key: StudentSortKey; label: string } }) => {
        const active = sort.key === column.key;
        const dir = active ? sort.dir : null;
        let Icon = ArrowUpDown;
        if (dir === 'asc') Icon = ArrowUp;
        if (dir === 'desc') Icon = ArrowDown;
        return (
            <th
                onClick={() => handleSort(column.key)}
                className="cursor-pointer select-none"
                style={{ userSelect: 'none' }}
            >
                <span className="inline-flex items-center gap-1">
                    {column.label}
                    <Icon size={14} className={active ? 'opacity-100' : 'opacity-40'} />
                </span>
            </th>
        );
    };

    if (loading) {
        return (
            <div className="admin-animate-page">
                <div className="mb-8">
                    <div className="admin-skeleton h-12 w-64 mb-3" />
                    <div className="admin-skeleton h-6 w-48" />
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <div key={i} className="admin-card p-5 flex items-center gap-4">
                            <div className="admin-skeleton w-12 h-12 rounded-xl flex-shrink-0" />
                            <div className="flex-1 space-y-2">
                                <div className="admin-skeleton h-6 w-16" />
                                <div className="admin-skeleton h-4 w-24" />
                            </div>
                        </div>
                    ))}
                </div>
                <div className="admin-skeleton h-10 w-full max-w-md mb-6" />
                <div className="admin-card overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="admin-table">
                            <thead>
                                <tr>
                                    <th>Student</th>
                                    <th>Level / XP</th>
                                    <th>Streak</th>
                                    <th>Time Learned</th>
                                    <th>Enrollments</th>
                                    <th>Achievements</th>
                                    <th>Joined</th>
                                </tr>
                            </thead>
                            <tbody>
                                {Array.from({ length: 6 }).map((_, i) => (
                                    <tr key={i}>
                                        <td><div className="admin-skeleton h-10 w-48" /></td>
                                        <td><div className="admin-skeleton h-6 w-24" /></td>
                                        <td><div className="admin-skeleton h-6 w-16" /></td>
                                        <td><div className="admin-skeleton h-6 w-20" /></td>
                                        <td><div className="admin-skeleton h-6 w-12" /></td>
                                        <td><div className="admin-skeleton h-6 w-12" /></td>
                                        <td><div className="admin-skeleton h-6 w-24" /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="admin-animate-page">
            {/* Header */}
            <div className="mb-8">
                <h1 className="admin-heading-md mb-2">Students</h1>
                <p className="admin-body-lg" style={{ color: 'var(--admin-ink-secondary)' }}>{students.length} students registered</p>
            </div>

            {/* Summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                {[
                    { label: 'Total Students', value: students.length, icon: Users, color: 'var(--admin-accent)' },
                    { label: 'Avg. Level', value: students.length ? (students.reduce((s, u) => s + u.level, 0) / students.length).toFixed(1) : 0, icon: Star, color: 'var(--admin-warning)' },
                    { label: 'Avg. XP', value: students.length ? Math.round(students.reduce((s, u) => s + u.current_xp, 0) / students.length) : 0, icon: Trophy, color: 'var(--admin-accent)' },
                    { label: 'Total Enrollments', value: students.reduce((s, u) => s + u.enrollments, 0), icon: BookOpen, color: 'var(--admin-success)' },
                ].map((card, i) => {
                    const Icon = card.icon;
                    return (
                        <div key={i} className="admin-card flex items-center gap-4 p-5">
                            <div
                                className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0"
                                style={{ background: `${card.color}22` }}
                            >
                                <Icon size={22} style={{ color: card.color }} />
                            </div>
                            <div>
                                <p className="text-2xl font-bold" style={{ color: 'var(--admin-ink)' }}>{card.value}</p>
                                <p className="text-xs" style={{ color: 'var(--admin-ink-secondary)' }}>{card.label}</p>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Search */}
            <div className="mb-6 relative max-w-md">
                <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: 'var(--admin-ink-tertiary)' }} />
                <input
                    type="text"
                    placeholder="Search by username or email..."
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="admin-input w-full pl-12"
                />
            </div>

            {/* Table */}
            <div className="admin-card overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="admin-table">
                        <thead>
                            <tr>
                                {COLUMN_HEADERS.map(col => <SortHeader key={col.key} column={col} />)}
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map(student => (
                                <tr key={student.id}>
                                    <td>
                                        <div className="flex items-center gap-3">
                                            <div
                                                className="w-9 h-9 rounded-lg flex items-center justify-center text-white font-bold text-sm flex-shrink-0"
                                                style={{ background: student.level >= 8 ? 'var(--admin-warning)' : student.level >= 5 ? 'var(--admin-accent)' : 'var(--admin-success)' }}
                                            >
                                                {student.username.slice(0, 2).toUpperCase()}
                                            </div>
                                            <div>
                                                <p className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{student.username}</p>
                                                <p className="text-xs" style={{ color: 'var(--admin-ink-tertiary)' }}>{student.email}</p>
                                            </div>
                                        </div>
                                    </td>
                                    <td>
                                        <div className="flex items-center gap-2">
                                            <span
                                                className="px-2.5 py-1 rounded-lg text-xs font-bold text-white"
                                                style={{ background: student.level >= 8 ? 'var(--admin-warning)' : student.level >= 5 ? 'var(--admin-accent)' : 'var(--admin-success)' }}
                                            >
                                                Lv {student.level}
                                            </span>
                                            <span className="text-sm font-mono" style={{ color: 'var(--admin-ink-secondary)' }}>{student.current_xp} XP</span>
                                        </div>
                                    </td>
                                    <td>
                                        <div className="flex items-center gap-1.5">
                                            <Flame size={16} style={{ color: student.current_streak > 0 ? 'var(--admin-warning)' : 'var(--admin-ink-tertiary)' }} />
                                            <span className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{student.current_streak}</span>
                                            <span className="text-xs" style={{ color: 'var(--admin-ink-tertiary)' }}>days</span>
                                        </div>
                                    </td>
                                    <td>
                                        <div className="flex items-center gap-1.5">
                                            <Clock size={16} style={{ color: 'var(--admin-ink-tertiary)' }} />
                                            <span className="text-sm" style={{ color: 'var(--admin-ink)' }}>{Math.floor(student.total_minutes_learned / 60)}h {student.total_minutes_learned % 60}m</span>
                                        </div>
                                    </td>
                                    <td>
                                        <div className="flex items-center gap-1.5">
                                            <BookOpen size={16} style={{ color: 'var(--admin-ink-tertiary)' }} />
                                            <span className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{student.enrollments}</span>
                                        </div>
                                    </td>
                                    <td>
                                        <div className="flex items-center gap-1.5">
                                            <Trophy size={16} style={{ color: 'var(--admin-warning)' }} />
                                            <span className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{student.achievements}</span>
                                        </div>
                                    </td>
                                    <td>
                                        <span className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>
                                            {new Date(student.joined).toLocaleDateString()}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {filtered.length === 0 && (
                        <div className="py-16 text-center">
                            <Users size={48} className="mx-auto mb-4 opacity-40" style={{ color: 'var(--admin-ink-tertiary)' }} />
                            <p style={{ color: 'var(--admin-ink-tertiary)' }}>No students found</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
