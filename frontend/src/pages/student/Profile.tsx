import { Header } from '../../components/Header';
import { User, Mail, Calendar, Award, Bell, Lock, Palette, Globe, Shield, Zap, Loader2 } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import {
  getProfile, updateProfile,
  getStudentProfile, updateStudentProfile,
  getPreferences, updatePreferences,
  type UserProfile, type StudentProfile, type UserPreferences,
} from '../../services/profile';

export default function Profile() {
  const { user } = useAuth();

  // --- data state ---
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [studentProfile, setStudentProfile] = useState<StudentProfile | null>(null);
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // --- form state ---
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [bio, setBio] = useState('');
  const [location, setLocation] = useState('');
  const [timezone, setTimezone] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [p, sp, prefs] = await Promise.all([
        getProfile(),
        getStudentProfile(),
        getPreferences(),
      ]);
      setProfile(p);
      setStudentProfile(sp);
      setPrefs(prefs);
      setUsername(p.username ?? '');
      setEmail(p.email ?? '');
      setBio(sp.bio ?? p.bio ?? '');
      setLocation(sp.location ?? '');
      setTimezone(sp.timezone ?? '');
    } catch {
      setMessage('Failed to load profile.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const updatedUser = await updateProfile({ username, email, bio });
      setProfile(updatedUser);
      await updateStudentProfile({ bio, location, timezone });
      setMessage('Profile saved successfully.');
    } catch {
      setMessage('Failed to save profile.');
    } finally {
      setSaving(false);
    }
  };

  const handleTogglePref = async (key: keyof Omit<UserPreferences, 'id'>, value: boolean) => {
    if (!prefs) return;
    const updated = { ...prefs, [key]: value };
    setPrefs(updated);
    setSavingPrefs(true);
    try {
      await updatePreferences({ [key]: value });
    } catch {
      setPrefs(prefs); // revert on error
    } finally {
      setSavingPrefs(false);
    }
  };

  const stats = [
    { label: 'Days Active', value: studentProfile?.days_active ?? '-', icon: Calendar, color: 'from-primary to-secondary' },
    { label: 'Level', value: studentProfile?.level ?? '-', icon: Award, color: 'from-secondary to-accent' },
    { label: 'XP', value: studentProfile?.current_xp ?? '-', icon: Zap, color: 'from-accent to-primary' },
  ];

  const displayName = profile?.username ?? user?.username ?? 'User';
  const joinedDate = profile?.created_at
    ? new Date(profile.created_at).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    : '';

  if (loading) {
    return (
      <>
        <Header title="Profile & Settings" subtitle="Manage your account and preferences" />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-secondary" size={32} />
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

          {/* Success/Error message */}
          {message && (
            <div className={`mb-4 p-3 rounded-xl text-sm font-medium ${
              message.includes('success') ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}>
              {message}
            </div>
          )}

          {/* Profile Header Card */}
          <div className="bg-gradient-to-br from-primary via-secondary to-accent rounded-2xl p-8 text-white shadow-xl mb-8">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-6">
                <div className="relative">
                  <div className="w-32 h-32 rounded-2xl bg-white/20 backdrop-blur-sm border-4 border-white/30 flex items-center justify-center shadow-xl">
                    <User size={64} className="text-white" />
                  </div>
                </div>
                <div>
                  <h1 className="mb-2 text-white">{displayName}</h1>
                  <p className="text-white/90 mb-4 text-lg">{profile?.role ?? 'Student'} · {email}</p>
                  <div className="flex flex-wrap gap-2">
                    {location && (
                      <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                        {location}
                      </span>
                    )}
                    {joinedDate && (
                      <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                        Joined {joinedDate}
                      </span>
                    )}
                    <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                      Level {studentProfile?.level ?? 1}
                    </span>
                  </div>
                </div>
              </div>

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
                  <form className="space-y-5" onSubmit={handleSaveProfile}>
                    <div>
                      <label htmlFor="username" className="block mb-2 text-sm">Username</label>
                      <input
                        id="username"
                        type="text"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
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
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label htmlFor="location" className="block mb-2 text-sm">Location</label>
                        <input
                          id="location"
                          type="text"
                          value={location}
                          onChange={(e) => setLocation(e.target.value)}
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        />
                      </div>
                      <div>
                        <label htmlFor="timezone" className="block mb-2 text-sm">Timezone</label>
                        <input
                          id="timezone"
                          type="text"
                          value={timezone}
                          onChange={(e) => setTimezone(e.target.value)}
                          placeholder="e.g. PST, EST, UTC"
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        />
                      </div>
                    </div>

                    <button
                      type="submit"
                      disabled={saving}
                      className="px-6 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all disabled:opacity-50 flex items-center gap-2"
                    >
                      {saving && <Loader2 size={16} className="animate-spin" />}
                      {saving ? 'Saving...' : 'Save Changes'}
                    </button>
                  </form>
                </div>
              </div>

              {/* Preferences */}
              <div className="bg-card rounded-2xl shadow-sm border border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-accent/5 to-primary/5">
                  <h3 className="mb-0 flex items-center gap-2">
                    <Palette size={20} className="text-accent" />
                    Preferences {savingPrefs && <Loader2 size={14} className="animate-spin text-muted-foreground" />}
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
                        checked={prefs?.email_notifications ?? true}
                        onChange={(e) => handleTogglePref('email_notifications', e.target.checked)}
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
                        checked={prefs?.ai_tutor_voice_enabled ?? true}
                        onChange={(e) => handleTogglePref('ai_tutor_voice_enabled', e.target.checked)}
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
                        checked={prefs?.study_reminders ?? true}
                        onChange={(e) => handleTogglePref('study_reminders', e.target.checked)}
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
                  <button className="w-full flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors text-left opacity-60 cursor-not-allowed" disabled title="Coming soon">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-secondary/10 flex items-center justify-center">
                        <Lock size={20} className="text-secondary" />
                      </div>
                      <div>
                        <h5 className="mb-1">Change Password</h5>
                        <p className="text-xs text-muted-foreground">Coming soon</p>
                      </div>
                    </div>
                    <span className="text-secondary">→</span>
                  </button>

                  <button className="w-full flex items-center justify-between p-4 bg-muted/30 rounded-xl hover:bg-muted/50 transition-colors text-left opacity-60 cursor-not-allowed" disabled title="Coming soon">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                        <Globe size={20} className="text-accent" />
                      </div>
                      <div>
                        <h5 className="mb-1">Active Sessions</h5>
                        <p className="text-xs text-muted-foreground">Coming soon</p>
                      </div>
                    </div>
                    <span className="text-accent">→</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Sidebar — Streak & Stats */}
            <div className="space-y-6">
              <div className="bg-card rounded-2xl shadow-sm border border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-accent/5 to-secondary/5">
                  <h3 className="mb-0 flex items-center gap-2">
                    <Award size={20} className="text-accent" />
                    Stats
                  </h3>
                </div>
                <div className="p-6 space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Current Streak</span>
                    <span className="font-bold">{studentProfile?.current_streak ?? 0} days</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Longest Streak</span>
                    <span className="font-bold">{studentProfile?.longest_streak ?? 0} days</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Total Learning</span>
                    <span className="font-bold">{studentProfile?.total_minutes_learned ?? 0} min</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Daily Goal</span>
                    <span className="font-bold">{studentProfile?.daily_goal_minutes ?? 30} min</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Messages Sent</span>
                    <span className="font-bold">{studentProfile?.messages_count ?? 0}</span>
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
