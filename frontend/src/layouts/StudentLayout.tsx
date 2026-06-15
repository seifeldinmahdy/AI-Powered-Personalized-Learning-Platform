import { Outlet } from "react-router";
import { PaiTopNav } from "../components/personifai/PaiTopNav";

export default function StudentLayout() {
    return (
        <div style={{ height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-primary)" }}>
            <PaiTopNav />
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                <Outlet />
            </div>
        </div>
    );
}
