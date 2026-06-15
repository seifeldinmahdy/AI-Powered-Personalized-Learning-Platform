import { useState, useEffect } from "react";
import { useNavigate } from "react-router";
import axios from "axios";
import { useAuth } from "../contexts/AuthContext";
import {
  getProfile, updateProfile, getStudentProfile, updateStudentProfile,
  getPreferences, updatePreferences,
  type UserProfile, type StudentProfile, type UserPreferences,
} from "../services/profile";
import { getMyAchievements, getDailyStats, type UserAchievement, type DailyStudyStats } from "../services/gamification";

/* Profile — codex. Every field shown or edited maps to a real DB column
   (users, student_profiles, user_preferences, user_achievements,
   daily_study_stats). No fake/non-functional controls. */

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button type="button" disabled={disabled} onClick={() => onChange(!on)}
      style={{ width: 46, height: 26, borderRadius: 999, background: on ? "var(--ink-black)" : "var(--steel)", border: "none", position: "relative", cursor: disabled ? "default" : "pointer", transition: "background 180ms linear", flexShrink: 0 }}>
      <span style={{ position: "absolute", top: 3, left: on ? 23 : 3, width: 20, height: 20, borderRadius: "50%", background: "#fff", transition: "left 200ms cubic-bezier(.7,0,.2,1)" }} />
    </button>
  );
}

export default function Profile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [bio, setBio] = useState("");
  const [role, setRole] = useState("");
  const [createdAt, setCreatedAt] = useState("");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);
  const [error, setError] = useState("");

  const [studentProfile, setStudentProfile] = useState<StudentProfile | null>(null);
  const [achievements, setAchievements] = useState<UserAchievement[]>([]);
  const [weeklyStats, setWeeklyStats] = useState<DailyStudyStats[]>([]);
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [savingPref, setSavingPref] = useState(false);
  const [goal, setGoal] = useState<number>(30);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([getProfile(), getStudentProfile(), getMyAchievements(), getDailyStats(), getPreferences()])
      .then(([profileRes, studentRes, achRes, statsRes, prefRes]) => {
        if (profileRes.status === "fulfilled") {
          const p: UserProfile = profileRes.value;
          setUsername(p.username || "");
          setEmail(p.email || "");
          setBio(p.bio || "");
          setRole(p.role || "student");
          setCreatedAt(p.created_at || "");
        } else {
          setUsername(user.username); setEmail(user.email); setRole(user.role);
        }
        if (studentRes.status === "fulfilled") { setStudentProfile(studentRes.value); setGoal(studentRes.value.daily_goal_minutes ?? 30); }
        if (achRes.status === "fulfilled") setAchievements(achRes.value);
        if (statsRes.status === "fulfilled") setWeeklyStats(statsRes.value.slice(-14));
        if (prefRes.status === "fulfilled") setPreferences(prefRes.value);
      })
      .finally(() => setLoading(false));
  }, [user]);

  const handleSave = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!user) return;
    setError(""); setSaving(true); setSaveOk(false);
    try {
      await updateProfile({ username, email, bio });
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 3000);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.data) {
        const data = err.response.data;
        setError(typeof data === "string" ? data : data.error || Object.values(data).flat().join(", "));
      } else setError("Failed to save changes.");
    } finally { setSaving(false); }
  };

  const handlePrefChange = async (key: keyof Omit<UserPreferences, "id">, value: boolean) => {
    if (!preferences) return;
    const prev = preferences;
    setPreferences({ ...preferences, [key]: value });
    setSavingPref(true);
    try { await updatePreferences({ [key]: value }); }
    catch { setPreferences(prev); }
    finally { setSavingPref(false); }
  };

  const saveGoal = async () => {
    const v = Math.max(5, Math.min(600, goal || 30));
    setGoal(v);
    if (studentProfile && v === studentProfile.daily_goal_minutes) return;
    try {
      await updateStudentProfile({ daily_goal_minutes: v });
      setStudentProfile((p) => (p ? { ...p, daily_goal_minutes: v } : p));
    } catch { /* ignore */ }
  };

  const handleLogout = () => { logout(); navigate("/login"); };

  const joinDate = createdAt ? new Date(createdAt).toLocaleDateString("en-US", { month: "long", year: "numeric" }) : "—";
  const initials = (username || user?.username || "U").slice(0, 2).toUpperCase();

  // 7-day chart aligned Mon–Sun
  const today = new Date();
  const weekData = DAY_LABELS.map((_, i) => {
    const d = new Date(today);
    const mondayOffset = (today.getDay() + 6) % 7;
    d.setDate(today.getDate() - mondayOffset + i);
    const iso = d.toISOString().slice(0, 10);
    const stat = weeklyStats.find((s) => s.study_date === iso);
    return { day: DAY_LABELS[i], hours: stat ? parseFloat(stat.hours_spent) : 0 };
  });
  const maxHours = Math.max(...weekData.map((d) => d.hours), 0.1);
  const weekTotal = weekData.reduce((s, d) => s + d.hours, 0);

  const totalHours = Math.floor((studentProfile?.total_minutes_learned ?? 0) / 60);
  const stats = [
    { label: "LEVEL", value: studentProfile?.level ?? 1, sub: "current" },
    { label: "XP", value: studentProfile?.current_xp ?? 0, sub: "earned" },
    { label: "STREAK", value: studentProfile?.current_streak ?? 0, sub: `best ${studentProfile?.longest_streak ?? 0}` },
    { label: "HOURS", value: totalHours, sub: "learned" },
    { label: "DAYS", value: studentProfile?.days_active ?? 0, sub: "active" },
  ];

  const pad = "clamp(20px,5vw,64px)";

  if (loading) {
    return (
      <div className="codex" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-primary)" }}>
        <span className="t-mono steel">LOADING PROFILE…</span>
      </div>
    );
  }

  return (
    <div className="codex" style={{ flex: 1, overflowY: "auto", background: "var(--bg-primary)" }}>
      <style>{`
        .pf-grid { display:grid; grid-template-columns: minmax(0,1fr) 340px; gap: 40px; align-items:start; }
        @media (max-width: 900px){ .pf-grid { grid-template-columns:1fr; gap:28px; } }
      `}</style>

      <div style={{ padding: `clamp(28px,4vw,48px) ${pad} 64px`, maxWidth: 1320, marginInline: "auto", display: "flex", flexDirection: "column", gap: 36 }}>

        {/* Identity header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24, flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 22, alignItems: "center" }}>
            {studentProfile?.avatar_url ? (
              <img src={studentProfile.avatar_url} alt="" style={{ width: 84, height: 84, objectFit: "cover", border: "1px solid var(--hairline)" }} />
            ) : (
              <span style={{ width: 84, height: 84, background: "var(--accent-primary)", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 32 }}>{initials}</span>
            )}
            <div>
              <div className="t-display" style={{ fontSize: "clamp(30px,4vw,48px)", color: "var(--text-primary)" }}>{username || "User"}</div>
              <div className="t-mono steel" style={{ marginTop: 8, display: "flex", gap: 16, flexWrap: "wrap" }}>
                <span style={{ textTransform: "uppercase" }}>{role}</span>
                <span>{email}</span>
                <span>JOINED {joinDate.toUpperCase()}</span>
              </div>
            </div>
          </div>
          <button onClick={handleLogout} className="btn btn-ghost-dark">SIGN OUT</button>
        </div>

        {/* Stat strip */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
          {stats.map((s, i) => (
            <div key={s.label} style={{ padding: "22px 24px", borderRight: i < stats.length - 1 ? "1px solid var(--hairline)" : "none", borderBottom: "1px solid var(--hairline)" }}>
              <div className="t-label" style={{ color: "var(--text-secondary)" }}>{s.label}</div>
              <div className="t-display" style={{ fontSize: "clamp(28px,3.4vw,42px)", marginTop: 10, color: "var(--text-primary)" }}>{s.value}</div>
              <div className="t-mono steel" style={{ marginTop: 8 }}>{s.sub}</div>
            </div>
          ))}
        </div>

        <div className="pf-grid">
          {/* Main column */}
          <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
            {/* Personal info */}
            <section style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, padding: 28 }}>
              <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 20 }}>PERSONAL INFORMATION</div>

              {error && <div style={{ marginBottom: 18, fontFamily: "var(--ff-mono)", fontSize: 12, color: "var(--error-red)", borderLeft: "2px solid var(--error-red)", paddingLeft: 12, lineHeight: 1.5 }}>{error}</div>}
              {saveOk && <div style={{ marginBottom: 18, fontFamily: "var(--ff-mono)", fontSize: 12, color: "var(--accent-success)", borderLeft: "2px solid var(--accent-success)", paddingLeft: 12 }}>Profile updated.</div>}

              <form onSubmit={handleSave} style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                <label style={{ display: "block" }}>
                  <div className="t-label" style={{ color: "var(--text-primary)", marginBottom: 8 }}>USERNAME</div>
                  <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} disabled={saving} />
                </label>
                <label style={{ display: "block" }}>
                  <div className="t-label" style={{ color: "var(--text-primary)", marginBottom: 8 }}>EMAIL</div>
                  <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} disabled={saving} />
                </label>
                <label style={{ display: "block" }}>
                  <div className="t-label" style={{ color: "var(--text-primary)", marginBottom: 8 }}>BIO</div>
                  <textarea className="input" rows={4} placeholder="Tell us about yourself…" value={bio} onChange={(e) => setBio(e.target.value)} disabled={saving} style={{ resize: "vertical" }} />
                </label>
                <button type="submit" disabled={saving} className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
                  {saving ? "SAVING…" : "SAVE CHANGES"}
                </button>
              </form>
            </section>

            {/* Preferences */}
            <section style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, padding: 28 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span className="t-label" style={{ color: "var(--accent-primary)" }}>PREFERENCES</span>
                {savingPref && <span className="t-mono steel">SAVING…</span>}
              </div>
              {[
                { key: "email_notifications" as const, label: "Email notifications", desc: "Course updates and reminders by email.", checked: preferences?.email_notifications ?? true },
                { key: "ai_tutor_voice_enabled" as const, label: "AI tutor voice", desc: "Spoken feedback from Dr. Nova.", checked: preferences?.ai_tutor_voice_enabled ?? true },
                { key: "study_reminders" as const, label: "Study reminders", desc: "Daily nudges to keep your streak.", checked: preferences?.study_reminders ?? true },
              ].map((p, i) => (
                <div key={p.key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, padding: "18px 0", borderTop: i === 0 ? "1px solid var(--hairline)" : "none", borderBottom: "1px solid var(--hairline)" }}>
                  <div>
                    <div style={{ fontFamily: "var(--ff-body)", fontWeight: 600, fontSize: 14, color: "var(--text-primary)" }}>{p.label}</div>
                    <div className="t-body" style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 4 }}>{p.desc}</div>
                  </div>
                  <Toggle on={p.checked} disabled={savingPref || !preferences} onChange={(v) => handlePrefChange(p.key, v)} />
                </div>
              ))}

              {/* Daily goal (student_profiles.daily_goal_minutes) */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, padding: "18px 0" }}>
                <div>
                  <div style={{ fontFamily: "var(--ff-body)", fontWeight: 600, fontSize: 14, color: "var(--text-primary)" }}>Daily goal</div>
                  <div className="t-body" style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 4 }}>Target minutes of study per day.</div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="number" className="input" value={goal} min={5} max={600} onChange={(e) => setGoal(Number(e.target.value))} onBlur={saveGoal} style={{ width: 88, textAlign: "right" }} />
                  <span className="t-mono steel">MIN</span>
                </div>
              </div>
            </section>
          </div>

          {/* Sidebar */}
          <aside style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            {/* Achievements */}
            <section style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, padding: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 18 }}>
                <span className="t-label" style={{ color: "var(--accent-primary)" }}>ACHIEVEMENTS</span>
                <span className="t-mono steel">{achievements.length} EARNED</span>
              </div>
              {achievements.length === 0 ? (
                <div className="t-mono steel" style={{ textAlign: "center", padding: "24px 0" }}>NONE YET — KEEP LEARNING</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 380, overflowY: "auto" }}>
                  {achievements.map((ua) => (
                    <div key={ua.id} style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: 14, border: "1px solid var(--hairline)", borderRadius: 6, background: "var(--bg-primary)" }}>
                      <span style={{ width: 34, height: 34, flexShrink: 0, background: "var(--bg-surface)", border: "1px solid var(--hairline)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                        {ua.achievement.icon_url ? <img src={ua.achievement.icon_url} alt="" style={{ width: 18, height: 18 }} /> : <span style={{ width: 8, height: 8, background: "var(--accent-warm)" }} />}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontFamily: "var(--ff-body)", fontWeight: 600, fontSize: 13, color: "var(--text-primary)" }}>{ua.achievement.name}</div>
                        <div className="t-body" style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>{ua.achievement.description}</div>
                      </div>
                      <span className="t-mono" style={{ color: "var(--accent-warm)", flexShrink: 0 }}>+{ua.achievement.xp_reward}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Weekly activity */}
            <section style={{ background: "var(--bg-surface)", border: "1px solid var(--hairline)", borderRadius: 8, padding: 24 }}>
              <div className="t-label" style={{ color: "var(--accent-primary)", marginBottom: 18 }}>THIS WEEK</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {weekData.map(({ day, hours }) => (
                  <div key={day} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span className="t-mono steel" style={{ width: 32 }}>{day.toUpperCase()}</span>
                    <div style={{ flex: 1, height: 4, background: "var(--hairline)" }}>
                      <div style={{ width: `${(hours / maxHours) * 100}%`, height: "100%", background: hours > 0 ? "var(--accent-primary)" : "transparent" }} />
                    </div>
                    <span className="t-mono" style={{ width: 38, textAlign: "right", color: hours > 0 ? "var(--text-primary)" : "var(--steel-light)" }}>{hours > 0 ? `${hours.toFixed(1)}h` : "—"}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--hairline)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span className="t-label" style={{ color: "var(--text-secondary)" }}>WEEK TOTAL</span>
                <span className="t-display" style={{ fontSize: 24, color: "var(--text-primary)" }}>{weekTotal.toFixed(1)}h</span>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
