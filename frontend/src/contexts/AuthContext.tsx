import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { loginUser, signupUser, type AuthResponse } from "../services/auth";

// --------------- Types ---------------
export type UserRole = "student" | "admin";

export interface User {
    id: number;
    username: string;
    email: string;
    full_name: string;
    role: UserRole;
}

interface AuthContextType {
    user: User | null;
    isAuthenticated: boolean;
    isAdmin: boolean;
    isStudent: boolean;
    login: (email: string, password: string) => Promise<AuthResponse>;
    signup: (name: string, email: string, password: string) => Promise<AuthResponse>;
    logout: () => void;
}

// --------------- Context ---------------
const AuthContext = createContext<AuthContextType | undefined>(undefined);

const STORAGE_KEY = "auth_user";

// --------------- Provider ---------------
interface AuthProviderProps {
    children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
    const [user, setUser] = useState<User | null>(() => {
        const stored = localStorage.getItem(STORAGE_KEY);
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

    useEffect(() => {
        if (user) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    }, [user]);

    const login = useCallback(async (email: string, password: string) => {
        const data = await loginUser(email, password);
        const loggedInUser: User = {
            id: data.id,
            username: data.username,
            email: data.email,
            full_name: data.username,
            role: (data.role as UserRole) || "student",
        };
        localStorage.setItem("token", data.token);
        setUser(loggedInUser);
        return data;
    }, []);

    const signup = useCallback(async (name: string, email: string, password: string) => {
        const data = await signupUser(name, email, password);
        const newUser: User = {
            id: data.id,
            username: data.username,
            email: data.email,
            full_name: name,
            role: (data.role as UserRole) || "student",
        };
        localStorage.setItem("token", data.token);
        setUser(newUser);
        return data;
    }, []);

    const logout = useCallback(() => {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem("token");
        setUser(null);
    }, []);

    return (
        <AuthContext.Provider
            value={{ user, isAuthenticated, isAdmin, isStudent, login, signup, logout }}
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
