import { Header } from '../../components/Header';
import { CircularProgress } from '../../components/CircularProgress';
import { Play, Clock, Award, TrendingUp, BookOpen, Target, Loader2, Bookmark } from 'lucide-react';
import { Link } from 'react-router';
import { useAuth } from '../../contexts/AuthContext';
import { useState, useEffect } from 'react';
import { getEnrollments } from '../../services/api';
import { getLessonCompletions, getBookmarks, type LessonCompletion, type Bookmark as BookmarkType } from '../../services/progress';
import { getMyAchievements, getDailyStats, type UserAchievement, type DailyStudyStats } from '../../services/gamification';
import { getStudentProfile, type StudentProfile } from '../../services/profile';

interface EnrollmentData {
  id: number;
  course: number;
  course_title: string;
  current_lesson: number | null;
  progress_percentage: string;
  current_score: number;
}

export default function Dashboard() {
  const { user } = useAuth();
  const displayName = user?.full_name || user?.username || 'Learner';

  const [loading, setLoading] = useState(true);
  const [enrollments, setEnrollments] = useState<EnrollmentData[]>([]);
  const [completions, setCompletions] = useState<LessonCompletion[]>([]);
  const [achievements, setAchievements] = useState<UserAchievement[]>([]);
  const [dailyStats, setDailyStats] = useState<DailyStudyStats[]>([]);
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [bookmarks, setBookmarks] = useState<BookmarkType[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [enrollRes, completionsRes, achievementsRes, statsRes, profileRes, bookmarksRes] =
          await Promise.allSettled([
            getEnrollments(),
            getLessonCompletions(),
            getMyAchievements(),
            getDailyStats(),
            getStudentProfile(),
            getBookmarks(),
          ]);

        if (cancelled) return;

        if (enrollRes.status === 'fulfilled') {
          const raw = enrollRes.value.data;
          setEnrollments(Array.isArray(raw) ? raw : raw.results ?? []);
        }
        if (completionsRes.status === 'fulfilled') setCompletions(completionsRes.value);
        if (achievementsRes.status === 'fulfilled') setAchievements(achievementsRes.value);
        if (statsRes.status === 'fulfilled') setDailyStats(statsRes.value);
        if (profileRes.status === 'fulfilled') setProfile(profileRes.value);
        if (bookmarksRes.status === 'fulfilled') setBookmarks(bookmarksRes.value);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  // Derived values
  const currentEnrollment = enrollments[0] as EnrollmentData | undefined;
  const progress = currentEnrollment ? parseFloat(currentEnrollment.progress_percentage) : 0;
  const completedCount = completions.filter((c) => c.status === 'Completed').length;
  const totalMinutes = profile?.total_minutes_learned ?? 0;
  const streak = profile?.current_streak ?? 0;

  const formatTime = (minutes: number) => {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  const stats = [
    { label: 'Total Time', value: formatTime(totalMinutes), icon: Clock, iconBg: 'bg-secondary/10', iconColor: 'text-secondary', tint: 'from-secondary/5 to-transparent' },
    { label: 'Day Streak', value: `${streak} days`, icon: TrendingUp, iconBg: 'bg-accent/10', iconColor: 'text-accent', tint: 'from-accent/5 to-transparent' },
    { label: 'Lessons Done', value: completedCount, icon: Target, iconBg: 'bg-primary/10', iconColor: 'text-primary', tint: 'from-primary/5 to-transparent' },
  ];

  // Recent completed lessons
  const recentActivity = completions
    .filter((c) => c.status === 'Completed')
    .slice(0, 3);

  // Weekly stats
  const weekStats = dailyStats.slice(-7);

  if (loading) {
    return (
      <>
        <Header title={`Welcome back, ${displayName}`} subtitle="Loading your data..." />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={40} className="animate-spin text-secondary" />
        </div>
      </>
    );
  }

  return (
    <>
      <Header
        title={`Welcome back, ${displayName}`}
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
                  className={`bg-card rounded-2xl border border-border p-6 shadow-sm hover:shadow-md transition-all bg-gradient-to-br ${stat.tint}`}
                >
                  <div className="flex items-center justify-between mb-4">
                    <div className={`w-10 h-10 rounded-xl ${stat.iconBg} flex items-center justify-center`}>
                      <Icon size={20} className={stat.iconColor} />
                    </div>
                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{stat.label}</span>
                  </div>
                  <p className="text-3xl font-bold text-foreground">{stat.value}</p>
                </div>
              );
            })}
          </div>

          {/* Current Course Hero */}
          {currentEnrollment ? (
            <section className="mb-8">
              <div className="bg-gradient-to-br from-primary to-secondary rounded-2xl p-8 text-white shadow-xl">
                <div className="flex items-start justify-between gap-8">
                  <div className="flex-1">
                    <div className="inline-block px-3 py-1 bg-white/20 rounded-full text-xs font-semibold mb-4 backdrop-blur-sm">
                      CURRENT COURSE
                    </div>
                    <h1 className="mb-3 text-white">{currentEnrollment.course_title}</h1>
                    <p className="text-white/90 mb-6 text-lg">
                      {completedCount} lessons completed &middot; Score: {currentEnrollment.current_score}
                    </p>

                    {/* Progress Bar */}
                    <div className="mb-6">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm text-white/80">Progress</span>
                        <span className="text-sm font-semibold text-white">{progress.toFixed(0)}%</span>
                      </div>
                      <div className="h-3 bg-white/20 rounded-full overflow-hidden backdrop-blur-sm">
                        <div
                          className="h-full bg-accent rounded-full transition-all duration-500"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      <Link
                        to={
                          currentEnrollment.current_lesson
                            ? `/course/${currentEnrollment.course}/lesson/${currentEnrollment.current_lesson}`
                            : `/courses`
                        }
                        className="px-8 py-4 bg-white text-primary rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-3 group"
                      >
                        <Play size={20} fill="currentColor" className="group-hover:scale-110 transition-transform" />
                        <span>Resume Learning</span>
                      </Link>

                      <div className="flex gap-4 px-6 py-3 bg-white/10 rounded-xl backdrop-blur-sm">
                        <div className="flex items-center gap-2">
                          <Clock size={18} className="opacity-80" />
                          <span className="text-sm font-medium">{formatTime(totalMinutes)}</span>
                        </div>
                        <div className="w-px bg-white/20" />
                        <div className="flex items-center gap-2">
                          <BookOpen size={18} className="opacity-80" />
                          <span className="text-sm font-medium">{completedCount} done</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="hidden lg:block">
                    <div className="relative">
                      <div className="w-32 h-32 rounded-full bg-white/10 backdrop-blur-sm flex items-center justify-center">
                        <CircularProgress percentage={progress} size={120} strokeWidth={8} />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          ) : (
            <section className="mb-8">
              <div className="bg-gradient-to-br from-primary to-secondary rounded-2xl p-8 text-white shadow-xl text-center">
                <h2 className="text-white mb-4">No courses yet</h2>
                <p className="text-white/80 mb-6">Browse our catalog and enroll in your first course!</p>
                <Link
                  to="/courses"
                  className="inline-block px-8 py-4 bg-white text-primary rounded-xl font-semibold hover:shadow-lg transition-all"
                >
                  Browse Courses
                </Link>
              </div>
            </section>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Recent Activity */}
            <section className="lg:col-span-2">
              <div className="flex items-center justify-between mb-6">
                <h2 className="mb-0">Recent Activity</h2>
              </div>
              <div className="bg-card rounded-xl shadow-sm border border-border overflow-hidden">
                {recentActivity.length === 0 ? (
                  <div className="px-6 py-8 text-center text-muted-foreground">
                    <p className="text-sm">No completed lessons yet. Start learning!</p>
                  </div>
                ) : (
                  recentActivity.map((activity, index) => (
                    <div
                      key={activity.id}
                      className={`flex items-center justify-between px-6 py-5 ${
                        index !== recentActivity.length - 1 ? 'border-b border-border' : ''
                      } hover:bg-muted/50 transition-colors group`}
                    >
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white shadow-md">
                          <Award size={20} />
                        </div>
                        <div>
                          <h4 className="mb-1 group-hover:text-primary transition-colors">
                            {activity.lesson_title}
                          </h4>
                          <div className="flex items-center gap-3">
                            <span className="text-xs text-muted-foreground">
                              Score: {activity.score}
                            </span>
                            {activity.completed_at && (
                              <>
                                <span className="text-xs text-muted-foreground">&middot;</span>
                                <span className="text-xs text-muted-foreground">
                                  {new Date(activity.completed_at).toLocaleDateString()}
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </section>

            {/* Sidebar - Achievements & Weekly Stats */}
            <section className="space-y-8">
              {/* Achievements */}
              <div>
                <h3 className="mb-4">Achievements</h3>
                <div className="space-y-3">
                  {achievements.length === 0 ? (
                    <div className="bg-card rounded-xl p-4 border border-border text-center">
                      <p className="text-xs text-muted-foreground">No achievements yet. Keep learning!</p>
                    </div>
                  ) : (
                    achievements.map((ua) => (
                      <div
                        key={ua.id}
                        className="bg-card rounded-xl p-4 border border-accent shadow-sm hover:shadow-md transition-all"
                      >
                        <div className="flex items-start gap-3">
                          <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                            {ua.achievement.icon_url ? (
                              <img src={ua.achievement.icon_url} alt="" className="w-6 h-6" />
                            ) : (
                              <Award size={20} className="text-accent" />
                            )}
                          </div>
                          <div className="flex-1">
                            <h5 className="mb-1">{ua.achievement.name}</h5>
                            <p className="text-xs text-muted-foreground">{ua.achievement.description}</p>
                          </div>
                          <div className="w-6 h-6 rounded-full bg-accent flex items-center justify-center text-white text-xs">
                            +{ua.achievement.xp_reward}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Saved Items */}
              <div>
                <h3 className="mb-4">Saved Items</h3>
                <div className="bg-card rounded-xl p-5 border border-border shadow-sm space-y-3">
                  {bookmarks.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center">No bookmarks yet. Bookmark slides while studying!</p>
                  ) : (
                    bookmarks.slice(0, 5).map((bm) => (
                      <Link
                        key={bm.id}
                        to={`/course/${bm.course_id}/lesson/${bm.lesson}`}
                        className="flex items-center gap-3 text-sm hover:text-secondary transition-colors no-underline"
                      >
                        <Bookmark size={14} className="text-secondary shrink-0" />
                        <span className="flex-1 truncate text-foreground">{bm.lesson_title}</span>
                        {bm.slide_index !== null && (
                          <span className="text-xs text-muted-foreground shrink-0">slide {bm.slide_index + 1}</span>
                        )}
                      </Link>
                    ))
                  )}
                </div>
              </div>

              {/* Weekly Study Stats */}
              <div>
                <h3 className="mb-4">This Week</h3>
                <div className="bg-card rounded-xl p-5 border border-border shadow-sm">
                  {weekStats.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center">No study data yet.</p>
                  ) : (
                    <>
                      <div className="space-y-3">
                        {weekStats.map((day) => (
                          <div key={day.id} className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                              <div
                                className={`w-2 h-2 rounded-full ${
                                  parseFloat(day.hours_spent) > 0 ? 'bg-accent' : 'bg-muted'
                                }`}
                              />
                              <span className="text-sm text-foreground">{day.study_date}</span>
                            </div>
                            <span
                              className={`text-sm font-mono ${
                                parseFloat(day.hours_spent) > 0
                                  ? 'text-foreground font-semibold'
                                  : 'text-muted-foreground'
                              }`}
                            >
                              {parseFloat(day.hours_spent) > 0
                                ? `${day.hours_spent}h`
                                : '\u2014'}
                            </span>
                          </div>
                        ))}
                      </div>
                      <div className="mt-4 pt-4 border-t border-border flex items-center justify-between">
                        <span className="text-sm text-muted-foreground">Weekly Total</span>
                        <span className="text-lg font-bold text-primary">
                          {weekStats
                            .reduce((sum, d) => sum + parseFloat(d.hours_spent), 0)
                            .toFixed(1)}
                          h
                        </span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </>
  );
}
