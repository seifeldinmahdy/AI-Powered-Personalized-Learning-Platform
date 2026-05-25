import api from './api';

export interface AuthResponse {
    status: string;
    id: number;
    username: string;
    email: string;
    role: string;
    access: string;
    refresh: string;
}

export interface AuthError {
    error: string;
}

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/users/login/', {
        username: email,
        password,
    });
    return response.data;
}

export async function signupUser(
    name: string,
    email: string,
    password: string
): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/users/signup/', {
        username: name,
        email,
        password,
    });
    return response.data;
}

export async function logoutUser(): Promise<void> {
    const refreshToken = localStorage.getItem('refresh_token');
    if (refreshToken) {
        await api.post('/users/logout/', { refresh: refreshToken });
    }
}
