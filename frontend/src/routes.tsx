import { createBrowserRouter, Navigate } from "react-router";
import Login from "./pages/auth/Login";
import Dashboard from "./pages/student/Dashboard";
import LiveSession from "./pages/student/LiveSession";
import PracticeArea from "./pages/student/PracticeArea";
import Leaderboard from "./pages/student/Leaderboard";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminStudents from "./pages/admin/AdminStudents";
import AdminCourseEditor from "./pages/admin/AdminCourseEditor";
import InstructorDashboard from "./pages/instructor/InstructorDashboard";
import InstructorLayout from "./layouts/InstructorLayout";
import Profile from "./pages/Profile";
import NotFound from "./pages/shared/NotFound";
import StudentLayout from "./layouts/StudentLayout";
import AdminLayout from "./layouts/AdminLayout";
import RequireAuth from "./components/RequireAuth";
import RequirePathway from "./components/RequirePathway";

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
            { path: "practice", Component: PracticeArea },
            { path: "practice/:topic", Component: PracticeArea },
            { path: "leaderboard", Component: Leaderboard },
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
            { path: "admin/students", Component: AdminStudents },
            { path: "admin/courses/:courseId/editor", Component: AdminCourseEditor },
        ],
    },

    // Instructor routes
    {
        element: (
            <RequireAuth allowedRoles={["instructor"]}>
                <InstructorLayout />
            </RequireAuth>
        ),
        children: [
            { path: "instructor", Component: InstructorDashboard },
        ],
    },

    // 404 fallback
    { path: "*", Component: NotFound },
]);
