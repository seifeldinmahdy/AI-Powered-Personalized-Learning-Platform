import { useState, useEffect, useCallback } from "react";
import {
  Settings as SettingsIcon,
  Users,
  Shield,
  ScrollText,
  Loader2,
  RefreshCw,
  Crown,
  UserCheck,
  Clock,
  Filter,
} from "lucide-react";
import { toast } from "sonner";
import api from "../../services/api";
import { getAuditLogs, type AuditLogEntry } from "../../services/admin";

/* ─── Tabs ─── */
const TABS = ["Users & Roles", "Audit Log"] as const;
type Tab = (typeof TABS)[number];

export default function Settings() {
  const [tab, setTab] = useState<Tab>("Users & Roles");

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center"
          style={{ background: "var(--admin-accent)", color: "var(--admin-ink)" }}
        >
          <SettingsIcon size={22} />
        </div>
        <div>
          <h1 className="admin-heading" id="settings-title">
            Settings
          </h1>
          <p className="admin-subheading">Users, roles, and audit trail</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 admin-card p-1 w-fit">
        {TABS.map((t) => {
          const Icon = t === "Users & Roles" ? Users : ScrollText;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all"
              style={{
                background: tab === t ? "var(--admin-accent)" : "transparent",
                color: tab === t ? "var(--admin-ink)" : "var(--admin-muted)",
              }}
            >
              <Icon size={16} />
              {t}
            </button>
          );
        })}
      </div>

      {tab === "Users & Roles" && <UsersRolesTab />}
      {tab === "Audit Log" && <AuditLogTab />}
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   Users & Roles Tab
   ══════════════════════════════════════════════════════ */

interface UserEntry {
  id: number;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  date_joined: string;
}

function UsersRolesTab() {
  const [users, setUsers] = useState<UserEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<number | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      // Use admin-students which returns all students, plus admin info
      const studentsRes = await api.get("/users/admin-students/");
      const students = (Array.isArray(studentsRes.data) ? studentsRes.data : []).map(
        (s: Record<string, unknown>) => ({
          id: s.id as number,
          username: s.username as string,
          email: s.email as string,
          role: "student",
          is_active: true,
          date_joined: s.joined as string,
        })
      );
      // Get current admin user info
      const meRes = await api.get("/users/me/");
      const me = meRes.data;
      const adminEntry: UserEntry = {
        id: me.id,
        username: me.username,
        email: me.email,
        role: me.role || "admin",
        is_active: true,
        date_joined: me.date_joined || me.created_at || "",
      };

      // Combine, with admin first
      const all = [adminEntry, ...students.filter((s: UserEntry) => s.id !== me.id)];
      setUsers(all);
    } catch {
      toast.error("Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleToggleRole = async (user: UserEntry) => {
    const newRole = user.role === "admin" ? "student" : "admin";
    const action = newRole === "admin" ? "promote" : "demote";
    if (
      !confirm(
        `Are you sure you want to ${action} "${user.username}" to ${newRole}?`
      )
    )
      return;

    setToggling(user.id);
    try {
      await api.patch(`/users/${user.id}/`, { role: newRole });
      toast.success(`${user.username} ${action}d to ${newRole}`);
      fetchUsers();
    } catch {
      toast.error(`Failed to ${action} user`);
    } finally {
      setToggling(null);
    }
  };

  const adminCount = users.filter((u) => u.role === "admin").length;
  const studentCount = users.filter((u) => u.role === "student").length;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--admin-accent)" }} />
      </div>
    );
  }

  return (
    <div>
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {[
          { label: "Total Users", value: users.length, icon: Users, color: "var(--admin-accent)" },
          { label: "Admins", value: adminCount, icon: Crown, color: "var(--admin-accent)" },
          { label: "Students", value: studentCount, icon: UserCheck, color: "var(--admin-lime)" },
        ].map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="admin-card flex items-center gap-4 p-4">
              <Icon size={20} style={{ color: s.color }} />
              <div>
                <p className="text-xl font-bold" style={{ color: "var(--admin-ink)" }}>{s.value}</p>
                <p className="text-xs" style={{ color: "var(--admin-muted)" }}>{s.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* User Table */}
      <div className="admin-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: "2px solid var(--admin-border)" }}>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>User</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Role</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Joined</th>
                <th className="px-6 py-4 text-left text-xs font-semibold" style={{ color: "var(--admin-muted)" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  className="transition-colors"
                  style={{ borderBottom: "1px solid var(--admin-border)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--admin-surface)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div
                        className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm"
                        style={{
                          background: u.role === "admin" ? "var(--admin-accent)" : "var(--admin-surface)",
                          color: u.role === "admin" ? "var(--admin-ink)" : "var(--admin-muted)",
                        }}
                      >
                        {u.username.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <p className="text-sm font-semibold" style={{ color: "var(--admin-ink)" }}>{u.username}</p>
                        <p className="text-xs" style={{ color: "var(--admin-muted)" }}>{u.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className="admin-badge text-xs px-2.5 py-1 rounded-lg flex items-center gap-1 w-fit"
                      style={{
                        background: u.role === "admin" ? "var(--admin-accent)22" : "var(--admin-surface)",
                        color: u.role === "admin" ? "var(--admin-accent)" : "var(--admin-muted)",
                      }}
                    >
                      {u.role === "admin" ? <Shield size={12} /> : <UserCheck size={12} />}
                      {u.role}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-xs" style={{ color: "var(--admin-muted)" }}>
                    {u.date_joined ? new Date(u.date_joined).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-6 py-4">
                    <button
                      onClick={() => handleToggleRole(u)}
                      disabled={toggling === u.id}
                      className="admin-btn admin-btn-secondary text-xs px-3 py-1.5 flex items-center gap-1"
                    >
                      {toggling === u.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : u.role === "admin" ? (
                        <UserCheck size={12} />
                      ) : (
                        <Crown size={12} />
                      )}
                      {u.role === "admin" ? "Demote" : "Promote"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════
   Audit Log Tab
   ══════════════════════════════════════════════════════ */

function AuditLogTab() {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState("all");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (actionFilter !== "all") params.action = actionFilter;
      const data = await getAuditLogs(params);
      setLogs(data);
    } catch {
      toast.error("Failed to load audit logs");
    } finally {
      setLoading(false);
    }
  }, [actionFilter]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const actionTypes = [...new Set(logs.map((l) => l.action))].sort();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={32} className="animate-spin" style={{ color: "var(--admin-accent)" }} />
      </div>
    );
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Filter size={14} style={{ color: "var(--admin-muted)" }} />
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className="admin-input text-sm py-1.5"
          >
            <option value="all">All Actions</option>
            {actionTypes.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>
        <button onClick={fetchLogs} className="admin-btn admin-btn-secondary flex items-center gap-2 text-xs">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Log Entries */}
      {logs.length === 0 ? (
        <div className="admin-card py-16 text-center" style={{ color: "var(--admin-muted)" }}>
          <ScrollText size={48} className="mx-auto mb-4 opacity-40" />
          <p>No audit log entries found</p>
        </div>
      ) : (
        <div className="space-y-2">
          {logs.map((log) => (
            <div key={log.id} className="admin-card p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center"
                    style={{ background: "var(--admin-surface)" }}
                  >
                    <Shield size={14} style={{ color: "var(--admin-accent)" }} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold" style={{ color: "var(--admin-ink)" }}>
                        {log.admin_username}
                      </span>
                      <span
                        className="admin-badge text-xs px-2 py-0.5 rounded"
                        style={{ background: "var(--admin-accent)22", color: "var(--admin-accent)" }}
                      >
                        {log.action}
                      </span>
                      {log.target_type && (
                        <span className="text-xs" style={{ color: "var(--admin-muted)" }}>
                          on {log.target_type}
                          {log.target_id ? ` #${log.target_id}` : ""}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <span className="text-xs flex items-center gap-1" style={{ color: "var(--admin-muted)" }}>
                        <Clock size={10} /> {new Date(log.created_at).toLocaleString()}
                      </span>
                      {log.ip_address && (
                        <span className="text-xs" style={{ color: "var(--admin-muted)" }}>
                          IP: {log.ip_address}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
