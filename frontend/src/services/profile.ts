import api from './api';

export interface UserProfile {
    id: number;
    username: string;
    email: string;
    role: string;
    bio: string | null;
    created_at: string;
}

export interface StudentProfile {
    id: number;
    bio: string;
    location: string;
    timezone: string;
    avatar_url: string;
    level: number;
    current_xp: number;
    current_streak: number;
    longest_streak: number;
    total_minutes_learned: number;
    daily_goal_minutes: number;
    days_active: number;
    messages_count: number;
}

export interface UserPreferences {
    id: number;
    email_notifications: boolean;
    ai_tutor_voice_enabled: boolean;
    study_reminders: boolean;
}

export async function getProfile(): Promise<UserProfile> {
    const response = await api.get<UserProfile>('/users/me/');
    return response.data;
}

export async function updateProfile(
    data: Partial<Pick<UserProfile, 'username' | 'email' | 'bio'>>
): Promise<UserProfile> {
    const response = await api.patch<UserProfile>('/users/me/', data);
    return response.data;
}

export async function getStudentProfile(): Promise<StudentProfile> {
    const response = await api.get<StudentProfile>('/users/student-profile/');
    return response.data;
}

export async function updateStudentProfile(
    data: Partial<Pick<StudentProfile, 'bio' | 'location' | 'timezone' | 'avatar_url' | 'daily_goal_minutes'>>
): Promise<StudentProfile> {
    const response = await api.patch<StudentProfile>('/users/student-profile/', data);
    return response.data;
}

export async function getPreferences(): Promise<UserPreferences> {
    const response = await api.get<UserPreferences>('/users/preferences/');
    return response.data;
}

export async function updatePreferences(
    data: Partial<Omit<UserPreferences, 'id'>>
): Promise<UserPreferences> {
    const response = await api.patch<UserPreferences>('/users/preferences/', data);
    return response.data;
}
