import { createBrowserRouter, Navigate } from "react-router";
import Login from "./pages/auth/Login";
import Dashboard from "./pages/student/Dashboard";
import LiveSession from "./pages/student/LiveSession";
import CodingLab from "./pages/student/CodingLab";
import PracticeArea from "./pages/student/PracticeArea";
import Leaderboard from "./pages/student/Leaderboard";
import SurveyPage from "./pages/student/SurveyPage";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminStudents from "./pages/admin/AdminStudents";
import AdminCourseEditor from "./pages/admin/AdminCourseEditor";
import AdminCapstoneEditor from "./pages/admin/AdminCapstoneEditor";
import CapstonePage from "./pages/student/CapstonePage";
import CapstoneWorkspace from "./pages/student/CapstoneWorkspace";
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
            { path: "course/:courseId/lesson/:lessonId/lab", Component: CodingLab },
            {
                path: "course/:courseId/lesson/:lessonId/problem-set",
                lazy: () => import("./pages/student/ProblemSet").then(m => ({ Component: m.default })),
            },
            { path: "leaderboard", Component: Leaderboard },
            { path: "profile", Component: Profile },
            { path: "survey/:courseId", Component: SurveyPage },
            { path: "course/:courseId/capstone", Component: CapstonePage },
            { path: "course/:courseId/capstone/workspace", Component: CapstoneWorkspace },
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
            { path: "admin/courses/:courseId/capstone", Component: AdminCapstoneEditor },
        ],
    },

    // 404 fallback
    { path: "*", Component: NotFound },
]);
