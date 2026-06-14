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
    <header className="h-14 px-8 flex items-center bg-[var(--admin-paper-elevated)] border-b border-[var(--admin-hairline)]">
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
    </header>
  );
}
