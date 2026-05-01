import { Header } from '../components/Header';
import { User, Mail, Calendar, Award, Bell, Lock, Palette, Globe, Shield, Zap, Loader2, LogOut, Check } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router';
import { getProfile, updateProfile, getStudentProfile, getPreferences, updatePreferences, type UserProfile, type StudentProfile, type UserPreferences } from '../services/profile';
import { getMyAchievements, getDailyStats, type UserAchievement, type DailyStudyStats } from '../services/gamification';
import axios from 'axios';

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export default function Profile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  // Form state
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [bio, setBio] = useState('');
  const [role, setRole] = useState('');
  const [createdAt, setCreatedAt] = useState('');

  // UI state
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [error, setError] = useState('');

  // Real data
  const [studentProfile, setStudentProfile] = useState<StudentProfile | null>(null);
  const [achievements, setAchievements] = useState<UserAchievement[]>([]);
  const [weeklyStats, setWeeklyStats] = useState<DailyStudyStats[]>([]);
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [savingPref, setSavingPref] = useState(false);

  useEffect(() => {
    if (!user) return;
    setLoading(true);

    Promise.allSettled([
      getProfile(),
      getStudentProfile(),
      getMyAchievements(),
      getDailyStats(),
      getPreferences(),
    ]).then(([profileRes, studentRes, achRes, statsRes, prefRes]) => {
      if (profileRes.status === 'fulfilled') {
        const p: UserProfile = profileRes.value;
        setUsername(p.username || '');
        setEmail(p.email || '');
        setBio(p.bio || '');
        setRole(p.role || 'student');
        setCreatedAt(p.created_at || '');
      } else {
        setUsername(user.username);
        setEmail(user.email);
        setRole(user.role);
      }
      if (studentRes.status === 'fulfilled') setStudentProfile(studentRes.value);
      if (achRes.status === 'fulfilled') setAchievements(achRes.value);
      if (statsRes.status === 'fulfilled') setWeeklyStats(statsRes.value.slice(-7));
      if (prefRes.status === 'fulfilled') setPreferences(prefRes.value);
    }).finally(() => setLoading(false));
  }, [user]);

  const handleSave = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!user) return;
    setError('');
    setSaving(true);
    setSaveSuccess(false);
    try {
      await updateProfile({ username, email, bio });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.data) {
        const data = err.response.data;
        const msg = typeof data === 'string' ? data : data.error || Object.values(data).flat().join(', ');
        setError(msg);
      } else {
        setError('Failed to save changes.');
      }
    } finally {
      setSaving(false);
    }
  };

  const handlePrefChange = async (key: keyof Omit<UserPreferences, 'id'>, value: boolean) => {
    if (!preferences) return;
    const updated = { ...preferences, [key]: value };
    setPreferences(updated);
    setSavingPref(true);
    try {
      await updatePreferences({ [key]: value });
    } catch {
      // revert on failure
      setPreferences(preferences);
    } finally {
      setSavingPref(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const joinDate = createdAt
    ? new Date(createdAt).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    : 'N/A';

  // Build 7-day bar chart data aligned to Mon–Sun
  const today = new Date();
  const weekData = DAY_LABELS.map((_, i) => {
    const d = new Date(today);
    const dayOfWeek = today.getDay(); // 0=Sun, 1=Mon…
    const mondayOffset = (dayOfWeek + 6) % 7; // days since last Monday
    d.setDate(today.getDate() - mondayOffset + i);
    const iso = d.toISOString().slice(0, 10);
    const stat = weeklyStats.find((s) => s.study_date === iso);
    return { day: DAY_LABELS[i], hours: stat ? parseFloat(stat.hours_spent) : 0 };
  });
  const maxHours = Math.max(...weekData.map((d) => d.hours), 0.1);
  const weekTotal = weekData.reduce((s, d) => s + d.hours, 0);

  const stats = [
    { label: 'Days Active', value: studentProfile?.days_active ?? '—', icon: Calendar, color: 'from-primary to-secondary' },
    { label: 'Achievements', value: achievements.length || '—', icon: Award, color: 'from-secondary to-accent' },
    { label: 'Messages', value: studentProfile?.messages_count ?? '—', icon: Mail, color: 'from-accent to-primary' },
  ];

  if (loading) {
    return (
      <>
        <Header title="Profile & Settings" subtitle="Manage your account and preferences" />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={40} className="animate-spin text-secondary" />
        </div>
      </>
    );
  }

  return (
    <>
      <Header
        title="Profile & Settings"
        subtitle="Manage your account and preferences"
      />

      <div className="flex-1 overflow-y-auto">
        <div className="p-8 max-w-7xl mx-auto">
          {/* Profile Header Card */}
          <div className="bg-gradient-to-br from-primary via-secondary to-accent rounded-2xl p-8 text-white shadow-xl mb-8">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-6">
                {/* Avatar */}
                <div className="relative">
                  <div className="w-32 h-32 rounded-2xl bg-white/20 backdrop-blur-sm border-4 border-white/30 flex items-center justify-center shadow-xl">
                    <User size={64} className="text-white" />
                  </div>
                </div>

                {/* Info */}
                <div>
                  <h1 className="mb-2 text-white">{username || 'User'}</h1>
                  <p className="text-white/90 mb-4 text-lg capitalize">{role} · AI Learner</p>
                  <div className="flex flex-wrap gap-2">
                    <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                      ✉️ {email}
                    </span>
                    <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                      🎓 Joined {joinDate}
                    </span>
                  </div>
                </div>
              </div>

              {/* Stats + Logout */}
              <div className="flex flex-col items-end gap-4">
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2 px-4 py-2 bg-white/15 backdrop-blur-sm hover:bg-white/25 rounded-xl text-sm font-semibold transition-all"
                >
                  <LogOut size={16} />
                  Sign Out
                </button>
                <div className="flex gap-4">
                  {stats.map((stat, index) => {
                    const Icon = stat.icon;
                    return (
                      <div key={index} className="bg-white/10 backdrop-blur-sm rounded-xl p-4 text-center min-w-[100px]">
                        <Icon size={24} className="mx-auto mb-2 opacity-90" />
                        <p className="text-2xl font-bold mb-1">{stat.value}</p>
                        <p className="text-xs opacity-90">{stat.label}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Main Settings */}
            <div className="lg:col-span-2 space-y-6">
              {/* Personal Information */}
              <div className="bg-card rounded-2xl shadow-sm border border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5">
                  <h3 className="mb-0 flex items-center gap-2">
                    <User size={20} className="text-secondary" />
                    Personal Information
                  </h3>
                </div>
                <div className="p-6">
                  {error && (
                    <div className="mb-5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm">
                      {error}
                    </div>
                  )}
                  {saveSuccess && (
                    <div className="mb-5 px-4 py-3 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-600 text-sm flex items-center gap-2">
                      <Check size={16} />
                      Profile updated successfully!
                    </div>
                  )}

                  <form onSubmit={handleSave} className="space-y-5">
                    <div>
                      <label htmlFor="username" className="block mb-2 text-sm">Username</label>
                      <input
                        id="username"
                        type="text"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        disabled={saving}
                      />
                    </div>

                    <div>
                      <label htmlFor="email" className="block mb-2 text-sm">Email Address</label>
                      <input
                        id="email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        disabled={saving}
                      />
                    </div>

                    <div>
                      <label htmlFor="bio" className="block mb-2 text-sm">Bio</label>
                      <textarea
                        id="bio"
                        placeholder="Tell us about yourself..."
                        rows={4}
                        value={bio}
                        onChange={(e) => setBio(e.target.value)}
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors resize-none"
                        disabled={saving}
                      />
                    </div>

                    <button
                      type="submit"
                      disabled={saving}
                      className="px-6 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-2 disabled:opacity-70 disabled:cursor-not-allowed"
                    >
                      {saving ? (
                        <>
                          <Loader2 size={18} className="animate-spin" />
                          Saving...
                        </>
                      ) : (
                        'Save Changes'
                      )}
                    </button>
                  </form>
                </div>
              </div>

              {/* Preferences */}
              <div className="bg-card rounded-2xl shadow-sm border border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-accent/5 to-primary/5">
                  <h3 className="mb-0 flex items-center gap-2">
                    <Palette size={20} className="text-accent" />
                    Preferences
                    {savingPref && <Loader2 size={14} className="animate-spin text-muted-foreground ml-auto" />}
                  </h3>
                </div>
                <div className="p-6 space-y-5">
                  {[
                    { key: 'email_notifications' as const, label: 'Email Notifications', desc: 'Receive updates about your courses', icon: Bell, iconBg: 'bg-secondary/10', iconColor: 'text-secondary', checked: preferences?.email_notifications ?? true },
                    { key: 'ai_tutor_voice_enabled' as const, label: 'AI Tutor Voice', desc: 'Enable voice feedback from AI tutor', icon: Zap, iconBg: 'bg-accent/10', iconColor: 'text-accent', checked: preferences?.ai_tutor_voice_enabled ?? true },
                    { key: 'study_reminders' as const, label: 'Study Reminders', desc: 'Daily reminders to keep learning', icon: Calendar, iconBg: 'bg-primary/10', iconColor: 'text-primary', checked: preferences?.study_reminders ?? true },
                  ].map((pref) => {
                    const Icon = pref.icon;
                    return (
                      <div key={pref.key} className="flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors">
                        <div className="flex items-center gap-3">
                          <div className={`w-10 h-10 rounded-lg ${pref.iconBg} flex items-center justify-center`}>
                            <Icon size={20} className={pref.iconColor} />
                          </div>
                          <div>
                            <h5 className="mb-1">{pref.label}</h5>
                            <p className="text-xs text-muted-foreground">{pref.desc}</p>
                          </div>
                        </div>
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={pref.checked}
                            onChange={(e) => handlePrefChange(pref.key, e.target.checked)}
                            className="sr-only peer"
                            disabled={savingPref}
                          />
                          <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-secondary"></div>
                        </label>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Security */}
              <div className="bg-card rounded-2xl shadow-sm border border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-primary/5 to-accent/5">
                  <h3 className="mb-0 flex items-center gap-2">
                    <Shield size={20} className="text-primary" />
                    Security
                  </h3>
                </div>
                <div className="p-6 space-y-4">
                  <button className="w-full flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors text-left">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-secondary/10 flex items-center justify-center">
                        <Lock size={20} className="text-secondary" />
                      </div>
                      <div>
                        <h5 className="mb-1">Change Password</h5>
                        <p className="text-xs text-muted-foreground">Update your password</p>
                      </div>
                    </div>
                    <span className="text-secondary">→</span>
                  </button>

                  <button className="w-full flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors text-left">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                        <Globe size={20} className="text-accent" />
                      </div>
                      <div>
                        <h5 className="mb-1">Active Sessions</h5>
                        <p className="text-xs text-muted-foreground">Manage your active devices</p>
                      </div>
                    </div>
                    <span className="text-accent">→</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Achievements Sidebar */}
            <div className="space-y-6">
              {/* Achievements */}
              <div className="bg-card rounded-2xl shadow-sm border border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-accent/5 to-secondary/5">
                  <h3 className="mb-0 flex items-center gap-2">
                    <Award size={20} className="text-accent" />
                    Achievements
                    <span className="ml-auto text-xs text-muted-foreground font-normal">{achievements.length} earned</span>
                  </h3>
                </div>
                <div className="p-4 space-y-3 max-h-[400px] overflow-y-auto">
                  {achievements.length === 0 ? (
                    <div className="py-6 text-center">
                      <div className="w-12 h-12 rounded-2xl bg-muted/50 flex items-center justify-center mx-auto mb-3">
                        <Lock size={20} className="text-muted-foreground" />
                      </div>
                      <p className="text-xs text-muted-foreground">No achievements yet. Keep learning!</p>
                    </div>
                  ) : (
                    achievements.map((ua) => (
                      <div
                        key={ua.id}
                        className="rounded-xl p-4 bg-gradient-to-br from-accent/10 to-secondary/10 border border-accent/20 shadow-sm hover:shadow-md transition-all"
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
                            <h5 className="mb-0.5 text-sm">{ua.achievement.name}</h5>
                            <p className="text-xs text-muted-foreground">{ua.achievement.description}</p>
                          </div>
                          <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold shrink-0">
                            +{ua.achievement.xp_reward}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Weekly Activity Chart */}
              <div className="bg-gradient-to-br from-primary to-secondary rounded-2xl p-6 text-white shadow-xl">
                <h4 className="mb-4 text-white">Weekly Activity</h4>
                <div className="space-y-3">
                  {weekData.map(({ day, hours }) => (
                    <div key={day} className="flex items-center gap-3">
                      <span className="text-sm w-8 opacity-80">{day}</span>
                      <div className="flex-1 h-2 bg-white/20 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-white/80 rounded-full transition-all duration-500"
                          style={{ width: `${(hours / maxHours) * 100}%` }}
                        />
                      </div>
                      <span className="text-sm font-mono w-10 text-right opacity-80">
                        {hours > 0 ? `${hours.toFixed(1)}h` : '—'}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 pt-4 border-t border-white/20">
                  <div className="flex items-center justify-between">
                    <span className="text-sm opacity-90">Total This Week</span>
                    <span className="text-xl font-bold">{weekTotal.toFixed(1)}h</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
