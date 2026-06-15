import { useState, useEffect, useCallback, useMemo } from "react";
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
  Info,
  Search,
  CalendarDays,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../contexts/AuthContext";
import { Link } from "react-router";
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
          style={{ background: "var(--admin-accent)", color: "#fff" }}
        >
          <SettingsIcon size={22} />
        </div>
        <div>
          <h1 className="admin-heading-md" id="settings-title">
            Settings
          </h1>
          <p className="admin-body-lg">Users, roles, and audit trail</p>
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
                color: tab === t ? "#fff" : "var(--admin-ink-secondary)",
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
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "admin" | "student">("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

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

  const isSelf = (u: UserEntry) => currentUser?.id === u.id;

  const filtered = useMemo(() => {
    return users.filter((u) => {
      const matchSearch =
        search === "" ||
        u.username.toLowerCase().includes(search.toLowerCase()) ||
        u.email.toLowerCase().includes(search.toLowerCase());
      const matchRole =
        roleFilter === "all" || u.role === roleFilter;
      const joinDate = u.date_joined ? new Date(u.date_joined) : null;
      const matchDateFrom = !dateFrom || (joinDate && joinDate >= new Date(dateFrom));
      const matchDateTo = !dateTo || (joinDate && joinDate <= new Date(dateTo + "T23:59:59"));
      return matchSearch && matchRole && matchDateFrom && matchDateTo;
    });
  }, [users, search, roleFilter, dateFrom, dateTo]);

  const adminCount = users.filter((u) => u.role === "admin").length;
  const studentCount = users.filter((u) => u.role === "student").length;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="admin-loading-spinner" />
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
          { label: "Students", value: studentCount, icon: UserCheck, color: "var(--admin-success)" },
        ].map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="admin-card flex items-center gap-4 p-4">
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center"
                style={{ background: `${s.color}22` }}
              >
                <Icon size={20} style={{ color: s.color }} />
              </div>
              <div>
                <p className="text-xl font-bold" style={{ color: "var(--admin-ink)" }}>{s.value}</p>
                <p className="text-xs" style={{ color: "var(--admin-ink-secondary)" }}>{s.label}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Filters */}
      <div className="admin-card p-4 mb-6">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "var(--admin-ink-tertiary)" }} />
            <input
              type="text"
              placeholder="Search by name or email..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="admin-input w-full pl-11"
            />
          </div>

          {/* Role filter */}
          <div className="flex items-center gap-1 admin-card p-1">
            {(["all", "admin", "student"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setRoleFilter(f)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
                style={{
                  background: roleFilter === f ? "var(--admin-accent)" : "transparent",
                  color: roleFilter === f ? "#fff" : "var(--admin-ink-secondary)",
                }}
              >
                {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1) + "s"}
              </button>
            ))}
          </div>

          {/* Date range */}
          <div className="flex items-center gap-2">
            <CalendarDays size={16} style={{ color: "var(--admin-ink-tertiary)" }} />
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="admin-input text-sm py-1.5"
              title="Joined from"
            />
            <span className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="admin-input text-sm py-1.5"
              title="Joined to"
            />
          </div>
        </div>
      </div>

      {/* User Table — Actions column removed; replaced with profile link for students */}
      <div className="admin-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="admin-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Joined</th>
                <th>Profile</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="flex items-center gap-3">
                      <div
                        className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm"
                        style={{
                          background: u.role === "admin" ? "var(--admin-accent)" : "var(--admin-paper-muted)",
                          color: u.role === "admin" ? "#fff" : "var(--admin-ink-secondary)",
                        }}
                      >
                        {u.username.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <p className="text-sm font-semibold" style={{ color: "var(--admin-ink)" }}>
                          {u.username}
                          {isSelf(u) && (
                            <span className="ml-1.5 text-xs font-normal" style={{ color: "var(--admin-ink-tertiary)" }}>
                              (you)
                            </span>
                          )}
                        </p>
                        <p className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>{u.email}</p>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span
                      className="admin-badge text-xs px-2.5 py-1 rounded-lg flex items-center gap-1 w-fit"
                      style={{
                        background: u.role === "admin" ? "var(--admin-accent)22" : "var(--admin-paper-muted)",
                        color: u.role === "admin" ? "var(--admin-accent)" : "var(--admin-ink-secondary)",
                      }}
                    >
                      {u.role === "admin" ? <Shield size={12} /> : <UserCheck size={12} />}
                      {u.role}
                    </span>
                  </td>
                  <td className="text-sm" style={{ color: "var(--admin-ink-secondary)" }}>
                    {u.date_joined ? new Date(u.date_joined).toLocaleDateString() : "—"}
                  </td>
                  <td>
                    {u.role === "student" ? (
                      <Link
                        to={`/admin/students/${u.id}`}
                        className="admin-btn admin-btn-ghost text-xs px-3 py-1.5 inline-flex items-center gap-1"
                      >
                        <ExternalLink size={12} />
                        View Profile
                      </Link>
                    ) : (
                      <span className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="py-16 text-center" style={{ color: "var(--admin-ink-tertiary)" }}>
              <Users size={48} className="mx-auto mb-4 opacity-40" />
              <p>No users match your filters</p>
            </div>
          )}
        </div>
      </div>
      <p className="admin-body-sm mt-3">{filtered.length} of {users.length} users shown</p>
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
        <div className="admin-loading-spinner" />
      </div>
    );
  }

  return (
    <div>
      {/* Info banner */}
      <div
        className="admin-card p-4 mb-4 flex items-start gap-3"
        style={{ background: "var(--admin-accent-subtle)", borderColor: "var(--admin-accent)33" }}
      >
        <Info size={18} className="flex-shrink-0 mt-0.5" style={{ color: "var(--admin-accent)" }} />
        <div className="text-sm" style={{ color: "var(--admin-ink-secondary)" }}>
          <strong style={{ color: "var(--admin-ink)" }}>Audit logs</strong> track every privileged
          admin action — student creation, role changes, retraining triggers, and course deletions.
          Each entry records who performed the action, when, from which IP, and what changed.
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Filter size={14} style={{ color: "var(--admin-ink-tertiary)" }} />
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className="admin-input admin-select text-sm py-1.5"
          >
            <option value="all">All Actions</option>
            {actionTypes.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>
        <button onClick={fetchLogs} className="admin-btn admin-btn-ghost flex items-center gap-2 text-xs">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Log Entries */}
      {logs.length === 0 ? (
        <div className="admin-card py-16 text-center" style={{ color: "var(--admin-ink-tertiary)" }}>
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
                    style={{ background: "var(--admin-paper-muted)" }}
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
                        <span className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>
                          on {log.target_type}
                          {log.target_id ? ` #${log.target_id}` : ""}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <span className="text-xs flex items-center gap-1" style={{ color: "var(--admin-ink-tertiary)" }}>
                        <Clock size={10} /> {new Date(log.created_at).toLocaleString()}
                      </span>
                      {log.ip_address && (
                        <span className="text-xs" style={{ color: "var(--admin-ink-tertiary)" }}>
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
