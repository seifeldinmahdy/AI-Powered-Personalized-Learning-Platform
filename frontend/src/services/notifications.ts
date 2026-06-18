import api from './api';

export interface Notification {
    id: number;
    type: 'achievement' | 'streak' | 'course';
    title: string;
    body: string;
    is_read: boolean;
    created_at: string;
}

export async function getNotifications(): Promise<Notification[]> {
    const response = await api.get<Notification[] | { results: Notification[] }>('/gamification/notifications/');
    const data = response.data;
    return Array.isArray(data) ? data : data.results ?? [];
}

export async function markNotificationRead(id: number): Promise<Notification> {
    const response = await api.post<Notification>(`/gamification/notifications/${id}/read/`);
    return response.data;
}

export async function markAllNotificationsRead(): Promise<void> {
    // DRF registers the `read_all` action at `read_all/` (method name verbatim),
    // not `read-all/`.
    await api.post('/gamification/notifications/read_all/');
}
