import { createBrowserRouter, Navigate } from "react-router";
import Login from "./pages/auth/Login";
import OAuthCallback from "./pages/auth/OAuthCallback";
import Landing from "./pages/Landing";
import { useAuth } from "./contexts/AuthContext";
import Dashboard from "./pages/student/Dashboard";
import LiveSession from "./pages/student/LiveSession";
import CodingLab from "./pages/student/CodingLab";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminStudents from "./pages/admin/AdminStudents";
import AdminCourseEditor from "./pages/admin/AdminCourseEditor";
import ContentManagement from "./pages/admin/ContentManagement";
import StudentCreate from "./pages/admin/StudentCreate";
import StudentDetail from "./pages/admin/StudentDetail";
import Enrollments from "./pages/admin/Enrollments";
import AiOperations from "./pages/admin/AiOperations";
import HealthMonitor from "./pages/admin/HealthMonitor";
import Settings from "./pages/admin/Settings";
import Profile from "./pages/Profile";
import NotFound from "./pages/shared/NotFound";
import StudentLayout from "./layouts/StudentLayout";
import { AdminLayout } from "./components/admin/AdminLayout";
import RequireAuth from "./components/RequireAuth";
import RequirePathway from "./components/RequirePathway";

// Public landing page at "/". Authenticated users are bounced to their
// role's home so the marketing page never shadows the app for logged-in users.
function LandingRoute() {
    const { isAuthenticated, user } = useAuth();
    if (isAuthenticated && user) {
        return <Navigate to={user.role === "admin" ? "/admin" : "/dashboard"} replace />;
    }
    return <Landing />;
}

export const router = createBrowserRouter([
    // Public routes
    { path: "/", Component: LandingRoute },
    { path: "/login", Component: Login },
    { path: "/auth/callback/:provider", Component: OAuthCallback },

    // Student / User routes
    {
        element: (
            <RequireAuth allowedRoles={["student"]}>
                <StudentLayout />
            </RequireAuth>
        ),
        children: [
            { path: "dashboard", Component: Dashboard },
            {
                path: "courses",
                lazy: () => import("./pages/Courses").then(m => ({ Component: m.default })),
            },
            {
                path: "courses/:courseId",
                lazy: () => import("./pages/CourseDetail").then(m => ({ Component: m.default })),
            },
            {
                path: "courses/:courseId/assessment",
                lazy: () => import("./pages/Assessment").then(m => ({ Component: m.default })),
            },
            {
                path: "course/:courseId/pathway",
                lazy: () => import("./pages/student/CoursePathway").then(m => ({ Component: m.default })),
            },
            { path: "course/:courseId/lesson/:lessonId/lab", Component: CodingLab },
            {
                path: "course/:courseId/lesson/:lessonId/problem-set",
                lazy: () => import("./pages/student/ProblemSet").then(m => ({ Component: m.default })),
            },
            { path: "profile", Component: Profile },
            {
                path: "course/:courseId/lesson/:lessonId",
                element: (
                    <RequirePathway>
                        <LiveSession />
                    </RequirePathway>
                )
            },
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
            { path: "admin/content", Component: ContentManagement },
            { path: "admin/students", Component: AdminStudents },
            { path: "admin/students/new", Component: StudentCreate },
            { path: "admin/students/:id", Component: StudentDetail },
            { path: "admin/enrollments", Component: Enrollments },
            { path: "admin/ai-ops", Component: AiOperations },
            { path: "admin/health", Component: HealthMonitor },
            { path: "admin/settings", Component: Settings },
            { path: "admin/courses/:courseId/editor", Component: AdminCourseEditor },
        ],
    },

    // 404 fallback
    { path: "*", Component: NotFound },
]);
