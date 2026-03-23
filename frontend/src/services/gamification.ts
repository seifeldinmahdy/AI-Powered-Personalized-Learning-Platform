import api from './api';

// ---------- Types ----------

export interface Achievement {
    id: number;
    name: string;
    description: string;
    xp_reward: number;
    icon_url: string;
}

export interface UserAchievement {
    id: number;
    user: number;
    achievement: Achievement;
    earned_at: string;
}

export interface DailyStudyStats {
    id: number;
    user: number;
    study_date: string;
    hours_spent: string;
}

// ---------- Achievements ----------

export async function getAchievements(): Promise<Achievement[]> {
    const response = await api.get<Achievement[]>('/gamification/achievements/');
    return response.data;
}

export async function getMyAchievements(): Promise<UserAchievement[]> {
    const response = await api.get<UserAchievement[] | { results: UserAchievement[] }>('/gamification/achievements/mine/');
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

// ---------- Daily Study Stats ----------

export async function getDailyStats(): Promise<DailyStudyStats[]> {
    const response = await api.get<DailyStudyStats[] | { results: DailyStudyStats[] }>('/gamification/daily-stats/');
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function logStudyTime(data: {
    study_date: string;
    hours_spent: number;
}): Promise<DailyStudyStats> {
    const response = await api.post<DailyStudyStats>('/gamification/daily-stats/', data);
    return response.data;
}
