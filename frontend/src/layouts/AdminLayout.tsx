import { Outlet } from "react-router";
import { Sidebar } from "../components/Sidebar";

/**
 * Layout wrapper for the Admin view.
 * Provides the admin sidebar + a scrollable main content area.
 * Child routes render inside <Outlet />.
 */
export default function AdminLayout() {
    return (
        <div className="h-screen flex">
            <Sidebar variant="admin" />
            <div className="flex-1 flex flex-col overflow-hidden">
                <Outlet />
            </div>
        </div>
    );
}
