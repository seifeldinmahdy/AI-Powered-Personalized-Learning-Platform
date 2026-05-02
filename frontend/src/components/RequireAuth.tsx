import { Navigate, useLocation } from "react-router";
import { useAuth, type UserRole } from "../contexts/AuthContext";
import type { ReactNode } from "react";

interface RequireAuthProps {
    children: ReactNode;
    allowedRoles?: UserRole[];
}

/**
 * Route guard component.
 * - Redirects unauthenticated users → /login
 * - Redirects users without the required role → their appropriate dashboard
 */
export default function RequireAuth({ children, allowedRoles }: RequireAuthProps) {
    const { isAuthenticated, user } = useAuth();
    const location = useLocation();

    if (!isAuthenticated) {
        // Redirect to login, preserving the intended destination
        return <Navigate to="/login" state={{ from: location }} replace />;
    }

    if (allowedRoles && user && !allowedRoles.includes(user.role)) {
        // User is logged in but doesn't have the right role
        const redirectTo = user.role === "admin" ? "/admin" : user.role === "instructor" ? "/instructor" : "/dashboard";
        return <Navigate to={redirectTo} replace />;
    }

    return <>{children}</>;
}
