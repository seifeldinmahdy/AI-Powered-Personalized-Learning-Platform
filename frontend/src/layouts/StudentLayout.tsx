import { Outlet } from "react-router";
import { Sidebar } from "../components/Sidebar";

/**
 * Layout wrapper for the Student / regular-user view.
 * Provides the sidebar + a scrollable main content area.
 * Child routes render inside <Outlet />.
 */
export default function StudentLayout() {
    return (
        <div className="h-screen flex">
            <Sidebar variant="student" />
            <div className="flex-1 flex flex-col overflow-hidden">
                <Outlet />
            </div>
        </div>
    );
}
