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
  Menu,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router";
import { useAuth } from "../../contexts/AuthContext";
import { useState, useEffect } from "react";

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
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  // Close mobile drawer when entering desktop breakpoint
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 1024) {
        setMobileOpen(false);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

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

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className={`px-6 py-8 border-b border-[var(--admin-hairline)] flex items-center ${collapsed ? 'justify-center' : 'justify-between'}`}>
        <Link to="/admin" className={`flex items-center gap-3 group ${collapsed ? 'justify-center' : ''}`}>
          <div className="w-10 h-10 flex items-center justify-center bg-[var(--admin-paper-dark)] text-white rounded-[var(--admin-radius-md)] flex-shrink-0">
            <Shield size={20} />
          </div>
          {!collapsed && (
            <div>
              <p className="font-[family-name:var(--admin-font-display)] font-bold text-[15px] tracking-tight text-[var(--admin-ink)]">
                Personif<span className="text-[var(--admin-accent)]">AI</span>
              </p>
              <p className="admin-label admin-label-accent text-[10px] tracking-[0.1em]">Admin Portal</p>
            </div>
          )}
        </Link>
        {/* Desktop collapse toggle */}
        <button
          onClick={() => setCollapsed(c => !c)}
          className="hidden lg:flex items-center justify-center w-8 h-8 rounded-[var(--admin-radius-md)] hover:bg-[var(--admin-paper-muted)] transition-colors text-[var(--admin-ink-secondary)]"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 py-6 overflow-y-auto">
        {!collapsed && <p className="px-4 mb-4 admin-label">Platform</p>}
        <ul className="space-y-1">
          {adminNavItems.map((item) => {
            const active = isActive(item.path);
            const Icon = item.icon;
            return (
              <li key={item.path}>
                <Link
                  to={item.path}
                  title={collapsed ? item.label : undefined}
                  className={`
                    relative flex items-center gap-3 px-4 py-3 rounded-[var(--admin-radius-md)]
                    font-[family-name:var(--admin-font-display)] text-[14px] font-medium
                    transition-all duration-200
                    ${collapsed ? 'justify-center' : ''}
                    ${active
                      ? "bg-[var(--admin-accent-subtle)] text-[var(--admin-accent)]"
                      : "text-[var(--admin-ink-secondary)] hover:bg-[var(--admin-paper-muted)] hover:text-[var(--admin-ink)]"
                    }
                  `}
                >
                  {!collapsed && (
                    <span className={`
                      absolute left-0 w-1 h-6 rounded-r transition-all duration-200
                      ${active ? "bg-[var(--admin-accent)]" : "bg-transparent"}
                    `} />
                  )}
                  <Icon size={18} className="relative z-10 flex-shrink-0" />
                  {!collapsed && <span className="relative z-10">{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* User + Logout */}
      <div className="p-4 border-t border-[var(--admin-hairline)]">
        {!collapsed && (
          <div className="px-4 py-3 mb-3">
            <p className="font-[family-name:var(--admin-font-display)] font-semibold text-[14px] text-[var(--admin-ink)]">
              {user?.username ?? "Admin"}
            </p>
            <p className="admin-body-sm">{user?.email ?? ""}</p>
          </div>
        )}
        <button
          onClick={handleLogout}
          title={collapsed ? "Log out" : undefined}
          className={`admin-btn admin-btn-ghost w-full ${collapsed ? 'justify-center' : 'justify-start'}`}
        >
          <LogOut size={16} />
          {!collapsed && <span>Log out</span>}
        </button>
      </div>
    </>
  );

  return (
    <>
      {/* Mobile hamburger button — toggles the drawer */}
      <button
        onClick={() => setMobileOpen(o => !o)}
        className="lg:hidden fixed top-4 left-4 z-[60] w-10 h-10 flex items-center justify-center rounded-[var(--admin-radius-md)] bg-[var(--admin-paper-elevated)] border border-[var(--admin-hairline)] shadow-sm text-[var(--admin-ink)]"
        aria-label={mobileOpen ? "Close sidebar" : "Open sidebar"}
        aria-expanded={mobileOpen}
      >
        {mobileOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-[50] bg-black/40"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Single sidebar that behaves as a mobile drawer or desktop sticky panel */}
      <aside
        className={`
          fixed lg:sticky top-0 left-0 z-[55] lg:z-auto h-screen
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
          ${collapsed ? 'lg:w-20' : 'lg:w-64'}
          w-64
          flex flex-col bg-[var(--admin-paper-elevated)] border-r border-[var(--admin-hairline)]
          transition-all duration-300 ease-in-out flex-shrink-0
        `}
      >
        {/* Mobile-only close button inside the drawer */}
        <div className="absolute top-4 right-4 lg:hidden">
          <button
            onClick={() => setMobileOpen(false)}
            className="w-8 h-8 flex items-center justify-center rounded-[var(--admin-radius-md)] hover:bg-[var(--admin-paper-muted)] text-[var(--admin-ink-secondary)]"
            aria-label="Close sidebar"
          >
            <X size={18} />
          </button>
        </div>
        {sidebarContent}
      </aside>
    </>
  );
}
