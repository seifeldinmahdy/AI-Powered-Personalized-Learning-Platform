import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { BookOpen, Users, Star, BarChart2, Loader2, ChevronRight } from 'lucide-react';
import api from '../../services/api';
import { type AdminCourse } from '../../services/admin';

interface CourseStudent {
  id: number;
  student_id: number;
  username: string;
  progress_percentage: number;
  current_score: number;
  enrolled_at: string;
}

interface CourseWithStudents extends AdminCourse {
  students?: CourseStudent[];
  studentsLoaded?: boolean;
  expanded?: boolean;
}

export default function InstructorDashboard() {
  const navigate = useNavigate();
  const [courses, setCourses] = useState<CourseWithStudents[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/courses/my-courses/')
      .then((res) => {
        const data = res.data;
        setCourses(Array.isArray(data) ? data : data.results ?? []);
      })
      .catch(() => toast.error('Failed to load your courses'))
      .finally(() => setLoading(false));
  }, []);

  const toggleCourse = async (idx: number) => {
    const course = courses[idx];
    if (!course.expanded && !course.studentsLoaded) {
      try {
        const res = await api.get(`/courses/my-courses/${course.id}/students/`);
        setCourses((prev) =>
          prev.map((c, i) =>
            i === idx ? { ...c, expanded: true, studentsLoaded: true, students: res.data } : c,
          ),
        );
      } catch {
        toast.error('Failed to load students');
      }
    } else {
      setCourses((prev) =>
        prev.map((c, i) => (i === idx ? { ...c, expanded: !c.expanded } : c)),
      );
    }
  };

  const totalStudents = courses.reduce((sum, c) => sum + (c.students?.length ?? 0), 0);
  const avgRating = courses.length
    ? (courses.reduce((s, c) => s + (c.avg_rating ?? 0), 0) / courses.length).toFixed(1)
    : '—';

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={36} className="animate-spin text-secondary" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-8 max-w-4xl mx-auto w-full">
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-1">Instructor Portal</h1>
        <p className="text-sm text-muted-foreground">Manage your courses and track student progress</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        {[
          { label: 'My Courses', value: courses.length, icon: BookOpen, color: 'from-amber-400 to-orange-500' },
          { label: 'Total Lessons', value: courses.reduce((s, c) => s + (c.total_lessons_count ?? 0), 0), icon: BarChart2, color: 'from-orange-400 to-rose-400' },
          { label: 'Avg Rating', value: avgRating, icon: Star, color: 'from-yellow-400 to-amber-500' },
        ].map((card, i) => {
          const Icon = card.icon;
          return (
            <div key={i} className="bg-card rounded-2xl border border-border shadow-sm p-5 flex items-center gap-4">
              <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${card.color} flex items-center justify-center shadow`}>
                <Icon size={22} className="text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold">{card.value}</p>
                <p className="text-sm text-muted-foreground">{card.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Courses */}
      {courses.length === 0 ? (
        <div className="bg-card rounded-2xl border border-border p-12 text-center">
          <BookOpen size={48} className="mx-auto mb-4 text-muted-foreground opacity-40" />
          <p className="font-semibold mb-1">No courses yet</p>
          <p className="text-sm text-muted-foreground">Ask an admin to assign you as instructor on a course.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {courses.map((course, idx) => (
            <div key={course.id} className="bg-card rounded-2xl border border-border shadow-sm overflow-hidden">
              {/* Course header */}
              <button
                onClick={() => toggleCourse(idx)}
                className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-muted/30 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-semibold truncate">{course.title}</p>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-muted-foreground">{course.difficulty}</span>
                    <span className="text-xs text-muted-foreground">·</span>
                    <span className="text-xs text-muted-foreground">{course.total_lessons_count} lessons</span>
                    <span className="text-xs text-muted-foreground">·</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      course.status === 'Published' ? 'bg-green-100 text-green-700' :
                      course.status === 'Draft' ? 'bg-yellow-100 text-yellow-700' :
                      'bg-gray-100 text-gray-600'
                    }`}>{course.status}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {course.avg_rating > 0 && (
                    <span className="flex items-center gap-1 text-sm text-amber-500 font-medium">
                      <Star size={13} fill="currentColor" /> {course.avg_rating.toFixed(1)}
                    </span>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/courses/${course.id}`); }}
                    className="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded-lg hover:bg-muted/60"
                  >
                    View
                  </button>
                  <ChevronRight size={16} className={`text-muted-foreground transition-transform ${course.expanded ? 'rotate-90' : ''}`} />
                </div>
              </button>

              {/* Students table */}
              {course.expanded && (
                <div className="border-t border-border">
                  {!course.studentsLoaded ? (
                    <div className="flex justify-center py-6"><Loader2 size={20} className="animate-spin text-muted-foreground" /></div>
                  ) : course.students?.length === 0 ? (
                    <div className="px-5 py-6 text-center text-sm text-muted-foreground flex items-center justify-center gap-2">
                      <Users size={16} /> No students enrolled yet
                    </div>
                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-muted/40">
                        <tr>
                          <th className="px-5 py-2.5 text-left text-xs font-semibold text-muted-foreground">Student</th>
                          <th className="px-5 py-2.5 text-left text-xs font-semibold text-muted-foreground">Progress</th>
                          <th className="px-5 py-2.5 text-left text-xs font-semibold text-muted-foreground">Score</th>
                          <th className="px-5 py-2.5 text-left text-xs font-semibold text-muted-foreground">Enrolled</th>
                        </tr>
                      </thead>
                      <tbody>
                        {course.students?.map((s) => (
                          <tr key={s.id} className="border-t border-border/50 hover:bg-muted/20 transition-colors">
                            <td className="px-5 py-2.5 font-medium">{s.username}</td>
                            <td className="px-5 py-2.5">
                              <div className="flex items-center gap-2">
                                <div className="w-24 h-1.5 rounded-full bg-muted overflow-hidden">
                                  <div
                                    className="h-full rounded-full bg-gradient-to-r from-amber-400 to-orange-500"
                                    style={{ width: `${s.progress_percentage ?? 0}%` }}
                                  />
                                </div>
                                <span className="text-xs text-muted-foreground">{s.progress_percentage ?? 0}%</span>
                              </div>
                            </td>
                            <td className="px-5 py-2.5 text-muted-foreground">{s.current_score ?? '—'}</td>
                            <td className="px-5 py-2.5 text-muted-foreground text-xs">
                              {new Date(s.enrolled_at).toLocaleDateString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {totalStudents > 0 && (
        <p className="mt-4 text-xs text-muted-foreground text-center">{totalStudents} students enrolled across all your courses</p>
      )}
    </div>
  );
}
