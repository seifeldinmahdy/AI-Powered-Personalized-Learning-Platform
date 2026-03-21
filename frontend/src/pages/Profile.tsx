import { Header } from '../components/Header';
import { User, Mail, Calendar, Award, Bell, Lock, Palette, Globe, Shield, Zap, Loader2, LogOut, Check } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router';
import { getProfile, updateProfile, UserProfile } from '../services/profile';
import axios from 'axios';

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

  const [notifications, setNotifications] = useState({
    email: true,
    voice: true,
    reminders: true,
  });

  // Fetch profile on mount
  useEffect(() => {
    if (!user) return;
    setLoading(true);
    getProfile()
      .then((profile) => {
        setUsername(profile.username || '');
        setEmail(profile.email || '');
        setBio(profile.bio || '');
        setRole(profile.role || 'student');
        setCreatedAt(profile.created_at || '');
      })
      .catch(() => {
        // Fall back to auth context data
        setUsername(user.username);
        setEmail(user.email);
        setRole(user.role);
      })
      .finally(() => setLoading(false));
  }, [user]);

  const handleSave = async (e: React.FormEvent) => {
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

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const joinDate = createdAt
    ? new Date(createdAt).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    : 'N/A';

  const stats = [
    { label: 'Days Active', value: '—', icon: Calendar, color: 'from-primary to-secondary' },
    { label: 'Achievements', value: '—', icon: Award, color: 'from-secondary to-accent' },
    { label: 'Messages', value: '—', icon: Mail, color: 'from-accent to-primary' },
  ];

  const achievements = [
    { title: 'First Steps', description: 'Complete your first lesson', icon: '🎯', earned: false },
    { title: 'Consistent Learner', description: '7-day learning streak', icon: '🔥', earned: false },
    { title: 'Night Owl', description: 'Study past midnight', icon: '🦉', earned: false },
    { title: 'Code Master', description: 'Complete 10 challenges', icon: '⚡', earned: false },
    { title: 'Perfect Score', description: 'Score 100% on a quiz', icon: '💯', earned: false },
    { title: 'Helper', description: 'Help another student', icon: '🤝', earned: false },
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
                  {/* Error / Success Messages */}
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
                  </h3>
                </div>
                <div className="p-6 space-y-5">
                  <div className="flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-secondary/10 flex items-center justify-center">
                        <Bell size={20} className="text-secondary" />
                      </div>
                      <div>
                        <h5 className="mb-1">Email Notifications</h5>
                        <p className="text-xs text-muted-foreground">Receive updates about your courses</p>
                      </div>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={notifications.email}
                        onChange={(e) => setNotifications({ ...notifications, email: e.target.checked })}
                        className="sr-only peer"
                      />
                      <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-secondary"></div>
                    </label>
                  </div>

                  <div className="flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                        <Zap size={20} className="text-accent" />
                      </div>
                      <div>
                        <h5 className="mb-1">AI Tutor Voice</h5>
                        <p className="text-xs text-muted-foreground">Enable voice feedback from AI tutor</p>
                      </div>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={notifications.voice}
                        onChange={(e) => setNotifications({ ...notifications, voice: e.target.checked })}
                        className="sr-only peer"
                      />
                      <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-secondary"></div>
                    </label>
                  </div>

                  <div className="flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                        <Calendar size={20} className="text-primary" />
                      </div>
                      <div>
                        <h5 className="mb-1">Study Reminders</h5>
                        <p className="text-xs text-muted-foreground">Daily reminders to keep learning</p>
                      </div>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={notifications.reminders}
                        onChange={(e) => setNotifications({ ...notifications, reminders: e.target.checked })}
                        className="sr-only peer"
                      />
                      <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-secondary"></div>
                    </label>
                  </div>
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
                  </h3>
                </div>
                <div className="p-4 space-y-3 max-h-[600px] overflow-y-auto">
                  {achievements.map((achievement, index) => (
                    <div
                      key={index}
                      className={`rounded-xl p-4 transition-all ${achievement.earned
                        ? 'bg-gradient-to-br from-accent/10 to-secondary/10 border-2 border-accent/30 shadow-sm'
                        : 'bg-muted/30 border-2 border-transparent opacity-60'
                        }`}
                    >
                      <div className="flex items-start gap-3">
                        <span className="text-3xl">{achievement.icon}</span>
                        <div className="flex-1">
                          <h5 className="mb-1 text-sm">{achievement.title}</h5>
                          <p className="text-xs text-muted-foreground">{achievement.description}</p>
                        </div>
                        {achievement.earned && (
                          <div className="w-6 h-6 rounded-full bg-accent flex items-center justify-center text-white text-xs flex-shrink-0">
                            ✓
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Learning Stats */}
              <div className="bg-gradient-to-br from-primary to-secondary rounded-2xl p-6 text-white shadow-xl">
                <h4 className="mb-4 text-white">Weekly Activity</h4>
                <div className="space-y-3">
                  {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day, index) => (
                    <div key={day} className="flex items-center gap-3">
                      <span className="text-sm w-8">{day}</span>
                      <div className="flex-1 h-2 bg-white/20 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-white/80 rounded-full transition-all"
                          style={{ width: `${[0, 0, 0, 0, 0, 0, 0][index]}%` }}
                        />
                      </div>
                      <span className="text-sm font-mono w-10 text-right">
                        {[0, 0, 0, 0, 0, 0, 0][index]}h
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 pt-4 border-t border-white/20">
                  <div className="flex items-center justify-between">
                    <span className="text-sm opacity-90">Total This Week</span>
                    <span className="text-xl font-bold">0h</span>
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
