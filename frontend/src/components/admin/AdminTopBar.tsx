import { Search, Bell, Command } from "lucide-react";
import { useLocation, Link } from "react-router";
import { useAuth } from "../../contexts/AuthContext";

const breadcrumbMap: Record<string, string> = {
  "/admin": "Overview",
  "/admin/content": "Content",
  "/admin/students": "Students",
  "/admin/students/new": "New student",
  "/admin/enrollments": "Enrollments",
  "/admin/ai-ops": "AI Operations",
  "/admin/health": "Health Monitor",
  "/admin/settings": "Settings",
};

export function AdminTopBar() {
  const location = useLocation();
  const { user } = useAuth();

  const segments = location.pathname
    .split("/")
    .filter(Boolean)
    .reduce<string[]>((acc, _segment, index, arr) => {
      const path = "/" + arr.slice(0, index + 1).join("/");
      if (breadcrumbMap[path]) {
        acc.push(breadcrumbMap[path]);
      }
      return acc;
    }, []);

  return (
    <header className="h-16 px-8 flex items-center justify-between bg-[var(--admin-paper-elevated)] border-b border-[var(--admin-hairline)]">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb">
        <ol className="flex items-center gap-2 admin-label">
          <li>
            <Link to="/admin" className="hover:text-[var(--admin-accent)] transition-colors">
              Admin
            </Link>
          </li>
          {segments.map((segment, index) => (
            <li key={index} className="flex items-center gap-2">
              <span className="text-[var(--admin-hairline)]">/</span>
              <span className={index === segments.length - 1 ? "text-[var(--admin-ink)]" : ""}>
                {segment}
              </span>
            </li>
          ))}
        </ol>
      </nav>

      {/* Search */}
      <div className="flex-1 max-w-md mx-8">
        <div className="relative">
          <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--admin-ink-tertiary)]" />
          <input
            type="text"
            placeholder="Search..."
            className="admin-input pl-11 pr-12 py-2.5 text-[14px]"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1 text-[var(--admin-ink-tertiary)]">
            <Command size={12} />
            <span className="admin-body-sm">K</span>
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-4">
        <button className="relative p-2 text-[var(--admin-ink-secondary)] hover:text-[var(--admin-ink)] transition-colors">
          <Bell size={20} />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-[var(--admin-error)] rounded-full" />
        </button>

        <div className="flex items-center gap-3 pl-4 border-l border-[var(--admin-hairline)]">
          <div className="w-9 h-9 flex items-center justify-center bg-[var(--admin-accent)] text-white rounded-[var(--admin-radius-md)] font-[family-name:var(--admin-font-display)] font-bold text-[13px]">
            {user?.username?.slice(0, 2).toUpperCase() ?? "AD"}
          </div>
          <div className="hidden md:block">
            <p className="font-[family-name:var(--admin-font-display)] font-semibold text-[13px] text-[var(--admin-ink)]">
              {user?.username ?? "Admin"}
            </p>
            <p className="admin-body-sm">Administrator</p>
          </div>
        </div>
      </div>
    </header>
  );
}
