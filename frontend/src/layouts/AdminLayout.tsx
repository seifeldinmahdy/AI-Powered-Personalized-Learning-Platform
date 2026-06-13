import { Outlet } from "react-router";
import { TopNav } from "../components/TopNav";

export default function AdminLayout() {
    return (
        <div className="h-screen flex flex-col">
            <TopNav variant="admin" />
            <div className="flex-1 flex flex-col overflow-auto">
                <Outlet />
            </div>
        </div>
    );
}
