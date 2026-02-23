import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

// --------------- Types ---------------
export type UserRole = "student" | "admin";

export interface User {
    id: number;
    email: string;
    full_name: string;
    role: UserRole;
}

interface AuthContextType {
    user: User | null;
    isAuthenticated: boolean;
    isAdmin: boolean;
    isStudent: boolean;
    login: (email: string, password: string) => void;
    logout: () => void;
}

// --------------- Context ---------------
const AuthContext = createContext<AuthContextType | undefined>(undefined);

// --------------- Provider ---------------
interface AuthProviderProps {
    children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
    const [user, setUser] = useState<User | null>(() => {
        // Check localStorage for persisted user session
        const stored = localStorage.getItem("auth_user");
        if (stored) {
            try {
                return JSON.parse(stored) as User;
            } catch {
                return null;
            }
        }
        return null;
    });

    const isAuthenticated = user !== null;
    const isAdmin = user?.role === "admin";
    const isStudent = user?.role === "student";

    const login = useCallback((email: string, _password: string) => {
        // Demo login: determine role from email
        // In production, this would call the API and get the role from the server
        const role: UserRole = email.toLowerCase().includes("admin")
            ? "admin"
            : "student";

        const demoUser: User = {
            id: 1,
            email,
            full_name: role === "admin" ? "Admin User" : "Alex Chen",
            role,
        };

        localStorage.setItem("auth_user", JSON.stringify(demoUser));
        localStorage.setItem("token", "demo-token");
        setUser(demoUser);
    }, []);

    const logout = useCallback(() => {
        localStorage.removeItem("auth_user");
        localStorage.removeItem("token");
        setUser(null);
    }, []);

    return (
        <AuthContext.Provider
            value={{ user, isAuthenticated, isAdmin, isStudent, login, logout }}
        >
            {children}
        </AuthContext.Provider>
    );
}

// --------------- Hook ---------------
export function useAuth(): AuthContextType {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error("useAuth must be used within an AuthProvider");
    }
    return context;
}
