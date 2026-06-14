import {
  LayoutDashboard,
  BookOpen,
  Users,
  GraduationCap,
  Bot,
  Activity,
  Settings,
  LogOut,
  Shield,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router";
import { useAuth } from "../../contexts/AuthContext";

interface NavItem {
  path: string;
  label: string;
  icon: typeof LayoutDashboard;
}

const adminNavItems: NavItem[] = [
  { path: "/admin", label: "Overview", icon: LayoutDashboard },
  { path: "/admin/content", label: "Content", icon: BookOpen },
  { path: "/admin/students", label: "Students", icon: Users },
  { path: "/admin/enrollments", label: "Enrollments", icon: GraduationCap },
  { path: "/admin/ai-ops", label: "AI Operations", icon: Bot },
  { path: "/admin/health", label: "Health Monitor", icon: Activity },
  { path: "/admin/settings", label: "Settings", icon: Settings },
];

export function AdminSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const isActive = (path: string) => {
    if (path === "/admin") {
      return location.pathname === "/admin";
    }
    return location.pathname.startsWith(path);
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <aside className="w-64 h-screen flex flex-col bg-[var(--admin-paper-elevated)] border-r border-[var(--admin-hairline)]">
      {/* Logo */}
      <div className="px-6 py-8 border-b border-[var(--admin-hairline)]">
        <Link to="/admin" className="flex items-center gap-3 group">
          <div className="w-10 h-10 flex items-center justify-center bg-[var(--admin-paper-dark)] text-white rounded-[var(--admin-radius-md)]">
            <Shield size={20} />
          </div>
          <div>
            <p className="font-[family-name:var(--admin-font-display)] font-bold text-[15px] tracking-tight text-[var(--admin-ink)]">
              Personif<span className="text-[var(--admin-accent)]">AI</span>
            </p>
            <p className="admin-label admin-label-accent text-[10px] tracking-[0.1em]">Admin Portal</p>
          </div>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 py-6 overflow-y-auto">
        <p className="px-4 mb-4 admin-label">Platform</p>
        <ul className="space-y-1">
          {adminNavItems.map((item) => {
            const active = isActive(item.path);
            const Icon = item.icon;
            return (
              <li key={item.path}>
                <Link
                  to={item.path}
                  className={`
                    relative flex items-center gap-3 px-4 py-3 rounded-[var(--admin-radius-md)]
                    font-[family-name:var(--admin-font-display)] text-[14px] font-medium
                    transition-all duration-200
                    ${active
                      ? "bg-[var(--admin-accent-subtle)] text-[var(--admin-accent)]"
                      : "text-[var(--admin-ink-secondary)] hover:bg-[var(--admin-paper-muted)] hover:text-[var(--admin-ink)]"
                    }
                  `}
                >
                  <span className={`
                    absolute left-0 w-1 h-6 rounded-r transition-all duration-200
                    ${active ? "bg-[var(--admin-accent)]" : "bg-transparent"}
                  `} />
                  <Icon size={18} className="relative z-10" />
                  <span className="relative z-10">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* User + Logout */}
      <div className="p-4 border-t border-[var(--admin-hairline)]">
        <div className="px-4 py-3 mb-3">
          <p className="font-[family-name:var(--admin-font-display)] font-semibold text-[14px] text-[var(--admin-ink)]">
            {user?.username ?? "Admin"}
          </p>
          <p className="admin-body-sm">{user?.email ?? ""}</p>
        </div>
        <button
          onClick={handleLogout}
          className="admin-btn admin-btn-ghost w-full justify-start"
        >
          <LogOut size={16} />
          <span>Log out</span>
        </button>
      </div>
    </aside>
  );
}
