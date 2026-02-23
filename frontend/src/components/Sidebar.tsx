import {
  Home,
  BookOpen,
  User,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Settings,
  Users,
  BarChart,
  Shield,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router";
import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";

// --------------- Types ---------------
interface NavItem {
  path: string;
  label: string;
  icon: typeof Home;
}

interface SidebarProps {
  variant?: "student" | "admin";
  collapsible?: boolean;
  defaultCollapsed?: boolean;
}

// --------------- Navigation configs ---------------
const studentNavItems: NavItem[] = [
  { path: "/dashboard", label: "Dashboard", icon: Home },
  { path: "/profile", label: "Profile", icon: User },
];

const adminNavItems: NavItem[] = [
  { path: "/admin", label: "Overview", icon: Home },
  { path: "/admin/courses", label: "Courses", icon: BookOpen },
  { path: "/admin/students", label: "Students", icon: Users },
  { path: "/admin/analytics", label: "Analytics", icon: BarChart },
  { path: "/admin/settings", label: "Settings", icon: Settings },
];

// --------------- Component ---------------
export function Sidebar({
  variant = "student",
  collapsible = false,
  defaultCollapsed = false,
}: SidebarProps) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout, isAdmin } = useAuth();

  const navItems = variant === "admin" ? adminNavItems : studentNavItems;

  const isActive = (path: string) => {
    if (path === "/dashboard") {
      return location.pathname === "/" || location.pathname === "/dashboard";
    }
    if (path === "/admin") {
      return location.pathname === "/admin";
    }
    return location.pathname.startsWith(path);
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };


  // ---- Collapsed state ----
  if (isCollapsed && collapsible) {
    return (
      <aside className="w-20 border-r-2 border-border bg-card flex flex-col shadow-sm">
        {/* Logo */}
        <div className="flex flex-col items-center py-6 border-b border-border">
          <div
            className={`w-12 h-12 rounded-xl bg-gradient-to-br ${variant === "admin"
              ? "from-rose-500 via-purple-600 to-indigo-600"
              : "from-primary via-secondary to-accent"
              } flex items-center justify-center shadow-lg mb-2`}
          >
            <span className="font-bold text-white text-lg">
              {variant === "admin" ? (
                <Shield size={20} />
              ) : (
                "AI"
              )}
            </span>
          </div>
        </div>

        {/* Navigation */}
        <div className="flex-1 flex flex-col items-center py-6 gap-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`
                  w-12 h-12 rounded-xl flex items-center justify-center transition-all
                  ${isActive(item.path)
                    ? "bg-gradient-to-br from-secondary to-accent text-white shadow-lg"
                    : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
                  }
                `}
                title={item.label}
              >
                <Icon size={20} />
              </Link>
            );
          })}
        </div>

        {/* Expand Button */}
        <div className="p-4 border-t border-border">
          <button
            onClick={() => setIsCollapsed(false)}
            className="w-full h-12 rounded-xl bg-muted/50 hover:bg-muted transition-colors flex items-center justify-center"
            title="Expand sidebar"
          >
            <ChevronRight size={20} />
          </button>
        </div>
      </aside>
    );
  }

  // ---- Expanded state ----
  return (
    <aside className="w-72 border-r-2 border-border bg-card flex flex-col shadow-sm">
      {/* Logo/Brand */}
      <div className="px-6 py-6 border-b border-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className={`w-12 h-12 rounded-xl bg-gradient-to-br ${variant === "admin"
                ? "from-rose-500 via-purple-600 to-indigo-600"
                : "from-primary via-secondary to-accent"
                } flex items-center justify-center shadow-lg`}
            >
              <span className="font-bold text-white text-lg">
                {variant === "admin" ? (
                  <Shield size={22} />
                ) : (
                  "AI"
                )}
              </span>
            </div>
            <div>
              <h3 className="mb-0 text-base">
                {variant === "admin" ? "Admin Panel" : "AI Tutor"}
              </h3>
              <p className="text-xs text-muted-foreground">
                {variant === "admin" ? "Management Console" : "Learning Platform"}
              </p>
            </div>
          </div>
          {collapsible && (
            <button
              onClick={() => setIsCollapsed(true)}
              className="p-2 rounded-lg hover:bg-muted transition-colors"
              title="Collapse sidebar"
            >
              <ChevronLeft size={18} />
            </button>
          )}
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 py-6">
        <div className="space-y-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`
                  flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium
                  ${isActive(item.path)
                    ? "bg-gradient-to-r from-secondary to-accent text-white shadow-md"
                    : "text-foreground hover:bg-muted/50"
                  }
                `}
              >
                <Icon size={20} />
                <span className="text-sm">{item.label}</span>
              </Link>
            );
          })}
        </div>

        {/* Quick Stats (student only) */}
        {variant === "student" && (
          <div className="mt-8 p-4 bg-gradient-to-br from-primary/5 to-accent/5 rounded-xl border border-border">
            <h5 className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">
              Today's Progress
            </h5>
            <div className="space-y-3">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-foreground">Lessons</span>
                  <span className="text-xs font-mono text-foreground">2/3</span>
                </div>
                <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-secondary to-accent rounded-full"
                    style={{ width: "67%" }}
                  />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-foreground">Time</span>
                  <span className="text-xs font-mono text-foreground">1.5h</span>
                </div>
                <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-accent to-primary rounded-full"
                    style={{ width: "75%" }}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Admin quick stats */}
        {variant === "admin" && (
          <div className="mt-8 p-4 bg-gradient-to-br from-rose-500/5 to-purple-500/5 rounded-xl border border-border">
            <h5 className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">
              Platform Stats
            </h5>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-foreground">Total Students</span>
                <span className="text-xs font-mono font-semibold text-foreground">175</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-foreground">Active Courses</span>
                <span className="text-xs font-mono font-semibold text-foreground">4</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-foreground">Completion Rate</span>
                <span className="text-xs font-mono font-semibold text-foreground">67%</span>
              </div>
            </div>
          </div>
        )}
      </nav>

      {/* User Section */}
      <div className="p-4 border-t border-border">
        <div className="flex items-center gap-3 p-3 rounded-xl bg-muted/30 mb-3">
          <div
            className={`w-10 h-10 rounded-lg bg-gradient-to-br ${variant === "admin"
              ? "from-rose-500 to-purple-600"
              : "from-primary to-accent"
              } flex items-center justify-center text-white font-bold`}
          >
            {user?.full_name
              ?.split(" ")
              .map((n) => n[0])
              .join("")
              .toUpperCase()
              .slice(0, 2) || "AC"}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold truncate">
              {user?.full_name || "Alex Chen"}
            </p>
            <p className="text-xs text-muted-foreground capitalize">
              {user?.role || "student"}
            </p>
          </div>
        </div>


        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-xl border-2 border-border hover:border-destructive hover:text-destructive transition-all font-medium"
        >
          <LogOut size={18} />
          <span className="text-sm">Logout</span>
        </button>
      </div>
    </aside>
  );
}
