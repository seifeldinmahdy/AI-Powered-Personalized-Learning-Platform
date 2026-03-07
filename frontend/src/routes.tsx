import { createBrowserRouter, Navigate } from "react-router";
import Login from "./pages/auth/Login";
import Dashboard from "./pages/student/Dashboard";
import LiveSession from "./pages/student/LiveSession";
import PracticeArea from "./pages/student/PracticeArea";
import AdminDashboard from "./pages/admin/AdminDashboard";
import Profile from "./pages/Profile";
import NotFound from "./pages/shared/NotFound";
import StudentLayout from "./layouts/StudentLayout";
import AdminLayout from "./layouts/AdminLayout";
import RequireAuth from "./components/RequireAuth";

export const router = createBrowserRouter([
    // Public routes
    { path: "/login", Component: Login },

    // Student / User routes
    {
        element: (
            <RequireAuth allowedRoles={["student"]}>
                <StudentLayout />
            </RequireAuth>
        ),
        children: [
            { path: "/", element: <Navigate to="/dashboard" replace /> },
            { path: "dashboard", Component: Dashboard },
            { path: "courses", lazy: () => import("./pages/Courses").then(m => ({ Component: m.default })) },
            { path: "practice", Component: PracticeArea },
            { path: "profile", Component: Profile },
            { path: "course/:courseId/lesson/:lessonId", Component: LiveSession },
        ],
    },

    // Admin routes
    {
        element: (
            <RequireAuth allowedRoles={["admin"]}>
                <AdminLayout />
            </RequireAuth>
        ),
        children: [
            { path: "admin", Component: AdminDashboard },
            // Future admin sub-pages go here:
            // { path: "admin/courses", Component: AdminCourses },
            // { path: "admin/students", Component: AdminStudents },
            // { path: "admin/analytics", Component: AdminAnalytics },
            // { path: "admin/settings", Component: AdminSettings },
        ],
    },

    // 404 fallback
    { path: "*", Component: NotFound },
]);
