import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { loginUser, signupUser, AuthResponse } from '../services/auth';

export interface UserData {
    id: number;
    username: string;
    email: string;
    role: string;
}

interface AuthContextType {
    user: UserData | null;
    isAuthenticated: boolean;
    login: (email: string, password: string) => Promise<AuthResponse>;
    signup: (name: string, email: string, password: string) => Promise<AuthResponse>;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const STORAGE_KEY = 'ai_tutor_user';

function loadUser(): UserData | null {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<UserData | null>(loadUser);

    useEffect(() => {
        if (user) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    }, [user]);

    const login = async (email: string, password: string) => {
        const data = await loginUser(email, password);
        setUser({ id: data.id, username: data.username, email: data.email, role: data.role });
        return data;
    };

    const signup = async (name: string, email: string, password: string) => {
        const data = await signupUser(name, email, password);
        setUser({ id: data.id, username: data.username, email: data.email, role: data.role });
        return data;
    };

    const logout = () => {
        setUser(null);
    };

    return (
        <AuthContext.Provider
            value={{ user, isAuthenticated: user !== null, login, signup, logout }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return ctx;
}
