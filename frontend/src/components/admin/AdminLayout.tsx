import { Outlet } from "react-router";
import { AdminSidebar } from "./AdminSidebar";
import { AdminTopBar } from "./AdminTopBar";
import { useAdminIdleTimer } from "../../hooks/useAdminIdleTimer";

export function AdminLayout() {
  // A.2: Auto-logout after 20 minutes of inactivity
  useAdminIdleTimer();

  return (
    <div className="admin-scope min-h-screen flex items-start bg-[var(--admin-paper)]">
      <AdminSidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <AdminTopBar />
        <main className="flex-1 overflow-y-auto">
          <div className="admin-animate-page p-8 lg:p-12 max-w-[1600px] mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
