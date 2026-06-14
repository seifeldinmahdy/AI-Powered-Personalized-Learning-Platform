import { Search, Command } from "lucide-react";
import { useLocation, Link } from "react-router";

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

      {/* Spacer to keep layout balanced */}
      <div className="w-8" />
    </header>
  );
}
