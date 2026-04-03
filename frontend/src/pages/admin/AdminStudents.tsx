import { Header } from '../../components/Header';
import { useState, useEffect } from 'react';
import { Search, Loader2, Users, Trophy, Flame, Clock, BookOpen, Star } from 'lucide-react';
import { toast } from 'sonner';
import { getAdminStudents, type AdminStudent } from '../../services/admin';

export default function AdminStudents() {
    const [students, setStudents] = useState<AdminStudent[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');

    useEffect(() => {
        getAdminStudents()
            .then(setStudents)
            .catch(() => toast.error('Failed to load students'))
            .finally(() => setLoading(false));
    }, []);

    const filtered = students.filter(s =>
        s.username.toLowerCase().includes(search.toLowerCase()) ||
        s.email.toLowerCase().includes(search.toLowerCase())
    );

    const levelColor = (level: number) => {
        if (level >= 8) return 'from-yellow-400 to-orange-400';
        if (level >= 5) return 'from-secondary to-accent';
        return 'from-primary to-secondary';
    };

    if (loading) return (
        <>
            <Header title="Students" subtitle="Manage all students" backLink="/admin" backLabel="Dashboard" />
            <div className="flex-1 flex items-center justify-center">
                <Loader2 size={40} className="animate-spin text-secondary" />
            </div>
        </>
    );

    return (
        <>
            <Header title="Students" subtitle={`${students.length} students registered`} backLink="/admin" backLabel="Dashboard" />
            <div className="flex-1 overflow-y-auto">
                <div className="p-8 max-w-[1400px] mx-auto">

                    {/* Summary cards */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                        {[
                            { label: 'Total Students', value: students.length, icon: Users, color: 'from-secondary to-accent' },
                            { label: 'Avg. Level', value: students.length ? (students.reduce((s, u) => s + u.level, 0) / students.length).toFixed(1) : 0, icon: Star, color: 'from-yellow-400 to-orange-400' },
                            { label: 'Avg. XP', value: students.length ? Math.round(students.reduce((s, u) => s + u.current_xp, 0) / students.length) : 0, icon: Trophy, color: 'from-accent to-primary' },
                            { label: 'Total Enrollments', value: students.reduce((s, u) => s + u.enrollments, 0), icon: BookOpen, color: 'from-primary to-secondary' },
                        ].map((card, i) => {
                            const Icon = card.icon;
                            return (
                                <div key={i} className="bg-card rounded-2xl border-2 border-border p-5 flex items-center gap-4">
                                    <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${card.color} flex items-center justify-center flex-shrink-0`}>
                                        <Icon size={22} className="text-white" />
                                    </div>
                                    <div>
                                        <p className="text-2xl font-bold">{card.value}</p>
                                        <p className="text-xs text-muted-foreground">{card.label}</p>
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    {/* Search */}
                    <div className="mb-6 relative max-w-md">
                        <Search size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
                        <input
                            type="text"
                            placeholder="Search by username or email..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            className="w-full pl-12 pr-4 py-3 bg-card border-2 border-border rounded-xl focus:outline-none focus:border-secondary transition-colors"
                        />
                    </div>

                    {/* Table */}
                    <div className="bg-card rounded-2xl border-2 border-border overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-muted/50 border-b-2 border-border">
                                    <tr>
                                        <th className="px-6 py-4 text-left text-sm font-semibold">Student</th>
                                        <th className="px-6 py-4 text-left text-sm font-semibold">Level / XP</th>
                                        <th className="px-6 py-4 text-left text-sm font-semibold">Streak</th>
                                        <th className="px-6 py-4 text-left text-sm font-semibold">Time Learned</th>
                                        <th className="px-6 py-4 text-left text-sm font-semibold">Enrollments</th>
                                        <th className="px-6 py-4 text-left text-sm font-semibold">Achievements</th>
                                        <th className="px-6 py-4 text-left text-sm font-semibold">Joined</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filtered.map(student => (
                                        <tr key={student.id} className="border-b border-border hover:bg-muted/30 transition-colors">
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-3">
                                                    <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${levelColor(student.level)} flex items-center justify-center text-white font-bold text-sm flex-shrink-0`}>
                                                        {student.username.slice(0, 2).toUpperCase()}
                                                    </div>
                                                    <div>
                                                        <p className="font-semibold text-sm">{student.username}</p>
                                                        <p className="text-xs text-muted-foreground">{student.email}</p>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-2">
                                                    <span className={`px-2.5 py-1 rounded-lg text-xs font-bold bg-gradient-to-r ${levelColor(student.level)} text-white`}>
                                                        Lv {student.level}
                                                    </span>
                                                    <span className="text-sm font-mono text-muted-foreground">{student.current_xp} XP</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-1.5">
                                                    <Flame size={16} className={student.current_streak > 0 ? 'text-orange-400' : 'text-muted-foreground'} />
                                                    <span className="font-semibold text-sm">{student.current_streak}</span>
                                                    <span className="text-xs text-muted-foreground">days</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-1.5">
                                                    <Clock size={16} className="text-muted-foreground" />
                                                    <span className="text-sm">{Math.floor(student.total_minutes_learned / 60)}h {student.total_minutes_learned % 60}m</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-1.5">
                                                    <BookOpen size={16} className="text-muted-foreground" />
                                                    <span className="font-semibold text-sm">{student.enrollments}</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-1.5">
                                                    <Trophy size={16} className="text-yellow-500" />
                                                    <span className="font-semibold text-sm">{student.achievements}</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-muted-foreground">
                                                {new Date(student.joined).toLocaleDateString()}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            {filtered.length === 0 && (
                                <div className="py-16 text-center">
                                    <Users size={48} className="mx-auto mb-4 text-muted-foreground opacity-40" />
                                    <p className="text-muted-foreground">No students found</p>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
}
