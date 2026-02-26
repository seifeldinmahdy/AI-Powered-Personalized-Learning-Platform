import api from './api';

export interface UserProfile {
    id: number;
    username: string;
    email: string;
    role: string;
    bio: string | null;
    created_at: string;
}

export async function getProfile(userId: number): Promise<UserProfile> {
    const response = await api.get<UserProfile>('/users/me/', {
        params: { user_id: userId },
    });
    return response.data;
}

export async function updateProfile(
    userId: number,
    data: Partial<Pick<UserProfile, 'username' | 'email' | 'bio'>>
): Promise<UserProfile> {
    const response = await api.patch<UserProfile>('/users/me/', {
        user_id: userId,
        ...data,
    });
    return response.data;
}
