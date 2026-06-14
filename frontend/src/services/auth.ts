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

/**
 * Exchange an OAuth authorization code (from a social provider redirect) for
 * our own JWT pair. The backend verifies the code with the provider, then
 * finds-or-creates the matching user.
 */
export async function oauthExchange(
    provider: string,
    code: string,
    redirectUri: string,
): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/users/oauth/', {
        provider,
        code,
        redirect_uri: redirectUri,
    });
    return response.data;
}
