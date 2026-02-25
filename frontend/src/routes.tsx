import { createBrowserRouter, Navigate } from "react-router";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Courses from "./pages/Courses";
import LiveSession from "./pages/LiveSession";
import AdminDashboard from "./pages/AdminDashboard";
import Profile from "./pages/Profile";
import NotFound from "./pages/NotFound";
import ProtectedRoute from "./components/ProtectedRoute";

export const router = createBrowserRouter([
  {
    path: "/",
    children: [
      { index: true, element: <ProtectedRoute><Dashboard /></ProtectedRoute> },
      { path: "login", Component: Login },
      { path: "dashboard", element: <ProtectedRoute><Dashboard /></ProtectedRoute> },
      { path: "courses", element: <ProtectedRoute><Courses /></ProtectedRoute> },
      { path: "profile", element: <ProtectedRoute><Profile /></ProtectedRoute> },
      { path: "course/:courseId/lesson/:lessonId", element: <ProtectedRoute><LiveSession /></ProtectedRoute> },
      { path: "admin", element: <ProtectedRoute><AdminDashboard /></ProtectedRoute> },
      { path: "*", Component: NotFound },
    ],
  },
]);