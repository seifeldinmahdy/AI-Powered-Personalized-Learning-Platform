import { Header } from '../../components/Header';
import { User, Mail, Calendar, Award, Bell, Lock, Palette, Globe, Shield, Zap } from 'lucide-react';
import { useState } from 'react';

export default function Profile() {
  const [notifications, setNotifications] = useState({
    email: true,
    voice: true,
    reminders: true,
  });

  const stats = [
    { label: 'Days Active', value: '42', icon: Calendar, color: 'from-primary to-secondary' },
    { label: 'Achievements', value: '8', icon: Award, color: 'from-secondary to-accent' },
    { label: 'Messages', value: '15', icon: Mail, color: 'from-accent to-primary' },
  ];

  const achievements = [
    { title: 'First Steps', description: 'Complete your first lesson', icon: '🎯', earned: true },
    { title: 'Consistent Learner', description: '7-day learning streak', icon: '🔥', earned: true },
    { title: 'Night Owl', description: 'Study past midnight', icon: '🦉', earned: true },
    { title: 'Code Master', description: 'Complete 10 challenges', icon: '⚡', earned: false },
    { title: 'Perfect Score', description: 'Score 100% on a quiz', icon: '💯', earned: false },
    { title: 'Helper', description: 'Help another student', icon: '🤝', earned: false },
  ];

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
                  <button className="absolute -bottom-3 -right-3 w-10 h-10 bg-white text-primary rounded-xl shadow-lg hover:shadow-xl transition-shadow flex items-center justify-center font-bold">
                    ✎
                  </button>
                </div>

                {/* Info */}
                <div>
                  <h1 className="mb-2 text-white">Alex Chen</h1>
                  <p className="text-white/90 mb-4 text-lg">Student · Python Learner</p>
                  <div className="flex flex-wrap gap-2">
                    <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                      📍 San Francisco, CA
                    </span>
                    <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                      🎓 Joined Feb 2026
                    </span>
                    <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-sm font-semibold">
                      ⚡ Level 5
                    </span>
                  </div>
                </div>
              </div>

              {/* Stats */}
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
                  <form className="space-y-5">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label htmlFor="firstName" className="block mb-2 text-sm">First Name</label>
                        <input
                          id="firstName"
                          type="text"
                          defaultValue="Alex"
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        />
                      </div>
                      <div>
                        <label htmlFor="lastName" className="block mb-2 text-sm">Last Name</label>
                        <input
                          id="lastName"
                          type="text"
                          defaultValue="Chen"
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        />
                      </div>
                    </div>

                    <div>
                      <label htmlFor="email" className="block mb-2 text-sm">Email Address</label>
                      <input
                        id="email"
                        type="email"
                        defaultValue="alex.chen@example.com"
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                      />
                    </div>

                    <div>
                      <label htmlFor="bio" className="block mb-2 text-sm">Bio</label>
                      <textarea
                        id="bio"
                        placeholder="Tell us about yourself..."
                        rows={4}
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors resize-none"
                        defaultValue="Learning Python to transition into data science. Passionate about coding and problem-solving."
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label htmlFor="location" className="block mb-2 text-sm">Location</label>
                        <input
                          id="location"
                          type="text"
                          defaultValue="San Francisco, CA"
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        />
                      </div>
                      <div>
                        <label htmlFor="timezone" className="block mb-2 text-sm">Timezone</label>
                        <select
                          id="timezone"
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        >
                          <option>PST (GMT-8)</option>
                          <option>EST (GMT-5)</option>
                          <option>UTC (GMT+0)</option>
                        </select>
                      </div>
                    </div>

                    <button
                      type="submit"
                      className="px-6 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all"
                    >
                      Save Changes
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
                          style={{ width: `${[80, 60, 90, 70, 0, 0, 40][index]}%` }}
                        />
                      </div>
                      <span className="text-sm font-mono w-10 text-right">
                        {[2.5, 1.8, 3.2, 2.1, 0, 0, 1.2][index]}h
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 pt-4 border-t border-white/20">
                  <div className="flex items-center justify-between">
                    <span className="text-sm opacity-90">Total This Week</span>
                    <span className="text-xl font-bold">11.8h</span>
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
