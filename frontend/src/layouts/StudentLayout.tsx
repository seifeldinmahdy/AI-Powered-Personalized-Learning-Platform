import { Outlet } from "react-router";
import { TopNav } from "../components/TopNav";

export default function StudentLayout() {
    return (
        <div className="h-screen flex flex-col">
            <TopNav variant="student" />
            <div className="flex-1 flex flex-col overflow-hidden">
                <Outlet />
            </div>
        </div>
    );
}
