import { Header } from '../../components/Header';
import { CircularProgress } from '../../components/CircularProgress';
import { Play, Clock, Award, TrendingUp, BookOpen, Target, Zap, Calendar } from 'lucide-react';
import { Link } from 'react-router';
import { useAuth } from '../../contexts/AuthContext';

export default function Dashboard() {
  const { user } = useAuth();

  const currentCourse = {
    id: 'python-101',
    name: 'Python 101',
    progress: 45,
    currentLesson: 'variables',
    currentLessonTitle: 'Intro to Python Variables',
    totalLessons: 12,
    completedLessons: 8,
    timeSpent: '4h 32m',
  };

  const stats = [
    { label: 'Total Time', value: '18h 45m', icon: Clock, color: 'bg-secondary' },
    { label: 'Streak', value: '7 days', icon: TrendingUp, color: 'bg-accent' },
    { label: 'Challenges', value: '7/15', icon: Target, color: 'bg-primary' },
  ];

  const recentActivity = [
    { lesson: 'Functions Basics', date: '2 days ago', completed: true, module: 'Module 4' },
    { lesson: 'Control Flow', date: '3 days ago', completed: true, module: 'Module 3' },
    { lesson: 'Data Types', date: '5 days ago', completed: true, module: 'Module 2' },
  ];

  const upcomingLessons = [
    { title: 'Lists & Tuples', duration: '15 min', difficulty: 'Easy' },
    { title: 'Dictionaries', duration: '20 min', difficulty: 'Medium' },
    { title: 'File Handling', duration: '25 min', difficulty: 'Medium' },
  ];

  const achievements = [
    { title: 'First Steps', description: 'Complete your first lesson', earned: true, icon: '🎯' },
    { title: 'Consistent Learner', description: '7-day learning streak', earned: true, icon: '🔥' },
    { title: 'Code Master', description: 'Complete 10 challenges', earned: false, icon: '⚡' },
    { title: 'Night Owl', description: 'Study past midnight', earned: true, icon: '🦉' },
  ];

  return (
    <>
      <Header
        title="Welcome back, Alex Chen"
        subtitle="Continue your learning journey"
      />

      <div className="flex-1 overflow-y-auto">
        <div className="p-8 max-w-7xl mx-auto">
          {/* Stats Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            {stats.map((stat, index) => {
              const Icon = stat.icon;
              return (
                <div
                  key={index}
                  className={`${stat.color} text-white rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow`}
                >
                  <div className="flex items-center justify-between mb-3">
                    <Icon size={24} className="opacity-90" />
                    <span className="text-sm font-medium opacity-90">{stat.label}</span>
                  </div>
                  <p className="text-3xl font-bold">{stat.value}</p>
                </div>
              );
            })}
          </div>

          {/* Current Course Hero */}
          <section className="mb-8">
            <div className="bg-gradient-to-br from-primary to-secondary rounded-2xl p-8 text-white shadow-xl">
              <div className="flex items-start justify-between gap-8">
                <div className="flex-1">
                  <div className="inline-block px-3 py-1 bg-white/20 rounded-full text-xs font-semibold mb-4 backdrop-blur-sm">
                    CURRENT COURSE
                  </div>
                  <h1 className="mb-3 text-white">{currentCourse.name}</h1>
                  <p className="text-white/90 mb-6 text-lg">
                    Lesson {currentCourse.completedLessons + 1} of {currentCourse.totalLessons}: {currentCourse.currentLessonTitle}
                  </p>

                  {/* Progress Bar */}
                  <div className="mb-6">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-white/80">Progress</span>
                      <span className="text-sm font-semibold text-white">{currentCourse.progress}%</span>
                    </div>
                    <div className="h-3 bg-white/20 rounded-full overflow-hidden backdrop-blur-sm">
                      <div
                        className="h-full bg-accent rounded-full transition-all duration-500"
                        style={{ width: `${currentCourse.progress}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    <Link
                      to={`/course/${currentCourse.id}/lesson/${currentCourse.currentLesson}`}
                      className="px-8 py-4 bg-white text-primary rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-3 group"
                    >
                      <Play size={20} fill="currentColor" className="group-hover:scale-110 transition-transform" />
                      <span>Resume Learning</span>
                    </Link>

                    <div className="flex gap-4 px-6 py-3 bg-white/10 rounded-xl backdrop-blur-sm">
                      <div className="flex items-center gap-2">
                        <Clock size={18} className="opacity-80" />
                        <span className="text-sm font-medium">{currentCourse.timeSpent}</span>
                      </div>
                      <div className="w-px bg-white/20" />
                      <div className="flex items-center gap-2">
                        <BookOpen size={18} className="opacity-80" />
                        <span className="text-sm font-medium">{currentCourse.completedLessons}/{currentCourse.totalLessons}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="hidden lg:block">
                  <div className="relative">
                    <div className="w-32 h-32 rounded-full bg-white/10 backdrop-blur-sm flex items-center justify-center">
                      <CircularProgress percentage={currentCourse.progress} size={120} strokeWidth={8} />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Recent Activity */}
            <section className="lg:col-span-2">
              <div className="flex items-center justify-between mb-6">
                <h2 className="mb-0">Recent Activity</h2>
                <button className="text-sm text-secondary hover:text-primary transition-colors font-medium">
                  View All
                </button>
              </div>
              <div className="bg-card rounded-xl shadow-sm border border-border overflow-hidden">
                {recentActivity.map((activity, index) => (
                  <div
                    key={index}
                    className={`flex items-center justify-between px-6 py-5 ${index !== recentActivity.length - 1 ? 'border-b border-border' : ''
                      } hover:bg-muted/50 transition-colors group`}
                  >
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white shadow-md">
                        <Award size={20} />
                      </div>
                      <div>
                        <h4 className="mb-1 group-hover:text-primary transition-colors">{activity.lesson}</h4>
                        <div className="flex items-center gap-3">
                          <span className="text-xs text-muted-foreground">{activity.module}</span>
                          <span className="text-xs text-muted-foreground">•</span>
                          <span className="text-xs text-muted-foreground">{activity.date}</span>
                        </div>
                      </div>
                    </div>
                    <button className="px-4 py-2 rounded-lg border border-border bg-card hover:border-secondary hover:text-secondary transition-colors text-sm font-medium">
                      Review
                    </button>
                  </div>
                ))}
              </div>

              {/* Upcoming Lessons */}
              <div className="mt-8">
                <h3 className="mb-4">Up Next</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {upcomingLessons.map((lesson, index) => (
                    <div
                      key={index}
                      className="bg-card rounded-xl p-5 border border-border hover:border-secondary hover:shadow-md transition-all cursor-pointer group"
                    >
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center text-muted-foreground group-hover:bg-secondary group-hover:text-white transition-colors">
                          <Zap size={16} />
                        </div>
                        <span className={`text-xs font-semibold px-2 py-1 rounded ${lesson.difficulty === 'Easy' ? 'bg-green-100 text-green-700' :
                          lesson.difficulty === 'Medium' ? 'bg-yellow-100 text-yellow-700' :
                            'bg-red-100 text-red-700'
                          }`}>
                          {lesson.difficulty}
                        </span>
                      </div>
                      <h5 className="mb-2 group-hover:text-secondary transition-colors">{lesson.title}</h5>
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Clock size={14} />
                        <span className="text-xs">{lesson.duration}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            {/* Sidebar - Achievements & Calendar */}
            <section className="space-y-8">
              {/* Achievements */}
              <div>
                <h3 className="mb-4">Achievements</h3>
                <div className="space-y-3">
                  {achievements.map((achievement, index) => (
                    <div
                      key={index}
                      className={`bg-card rounded-xl p-4 border transition-all ${achievement.earned
                        ? 'border-accent shadow-sm hover:shadow-md'
                        : 'border-border opacity-60'
                        }`}
                    >
                      <div className="flex items-start gap-3">
                        <span className="text-2xl">{achievement.icon}</span>
                        <div className="flex-1">
                          <h5 className="mb-1">{achievement.title}</h5>
                          <p className="text-xs text-muted-foreground">{achievement.description}</p>
                        </div>
                        {achievement.earned && (
                          <div className="w-6 h-6 rounded-full bg-accent flex items-center justify-center text-white text-xs">
                            ✓
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Study Calendar */}
              <div>
                <h3 className="mb-4">This Week</h3>
                <div className="bg-card rounded-xl p-5 border border-border shadow-sm">
                  <div className="space-y-3">
                    {[
                      { day: 'Monday', hours: 2.5, completed: true },
                      { day: 'Tuesday', hours: 1.5, completed: true },
                      { day: 'Wednesday', hours: 3.0, completed: true },
                      { day: 'Thursday', hours: 2.0, completed: false },
                      { day: 'Friday', hours: 0, completed: false },
                    ].map((day, index) => (
                      <div key={index} className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className={`w-2 h-2 rounded-full ${day.completed ? 'bg-accent' : 'bg-muted'}`} />
                          <span className={`text-sm ${day.completed ? 'text-foreground' : 'text-muted-foreground'}`}>
                            {day.day}
                          </span>
                        </div>
                        <span className={`text-sm font-mono ${day.hours > 0 ? 'text-foreground font-semibold' : 'text-muted-foreground'}`}>
                          {day.hours > 0 ? `${day.hours}h` : '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 pt-4 border-t border-border flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Weekly Total</span>
                    <span className="text-lg font-bold text-primary">9.0h</span>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </>
  );
}
