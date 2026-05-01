import { Bell } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { getNotifications, markAllNotificationsRead, type Notification } from '../services/notifications';

function timeAgo(dateStr: string): string {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

export function NotificationBell() {
    const [notifications, setNotifications] = useState<Notification[]>([]);
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    const unreadCount = notifications.filter((n) => !n.is_read).length;

    const fetchNotifications = async () => {
        try {
            const data = await getNotifications();
            setNotifications(data.slice(0, 10));
        } catch { /* ignore */ }
    };

    useEffect(() => {
        fetchNotifications();
        const interval = setInterval(fetchNotifications, 60000);
        return () => clearInterval(interval);
    }, []);

    // Close on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const handleMarkAllRead = async () => {
        try {
            await markAllNotificationsRead();
            setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
        } catch { /* ignore */ }
    };

    return (
        <div ref={ref} style={{ position: 'relative' }}>
            <button
                onClick={() => setOpen((o) => !o)}
                style={{ position: 'relative', padding: '6px', borderRadius: '8px', background: 'transparent', border: 'none', cursor: 'pointer', color: 'inherit' }}
                title="Notifications"
            >
                <Bell size={20} />
                {unreadCount > 0 && (
                    <span style={{
                        position: 'absolute', top: 2, right: 2,
                        background: '#ef4444', color: '#fff',
                        borderRadius: '999px', fontSize: '10px', fontWeight: 700,
                        minWidth: 16, height: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        padding: '0 3px', lineHeight: 1,
                    }}>
                        {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                )}
            </button>

            {open && (
                <div style={{
                    position: 'absolute', right: 0, top: 'calc(100% + 8px)',
                    width: 320, background: 'var(--card)', border: '1px solid var(--border)',
                    borderRadius: 16, boxShadow: '0 8px 32px rgba(0,0,0,0.12)', zIndex: 100, overflow: 'hidden',
                }}>
                    {/* Header */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>Notifications</span>
                        {unreadCount > 0 && (
                            <button
                                onClick={handleMarkAllRead}
                                style={{ fontSize: '0.75rem', color: 'var(--secondary)', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 500 }}
                            >
                                Mark all read
                            </button>
                        )}
                    </div>

                    {/* List */}
                    <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                        {notifications.length === 0 ? (
                            <p style={{ padding: '24px 16px', textAlign: 'center', fontSize: '0.8125rem', color: 'var(--muted-foreground)' }}>
                                No notifications yet.
                            </p>
                        ) : (
                            notifications.map((n) => (
                                <div key={n.id} style={{
                                    padding: '12px 16px',
                                    borderBottom: '1px solid var(--border)',
                                    background: n.is_read ? 'transparent' : 'var(--primary, #6366f1)10',
                                    opacity: n.is_read ? 0.75 : 1,
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                                        <div style={{ flex: 1 }}>
                                            <p style={{ margin: 0, fontSize: '0.8125rem', fontWeight: 600, color: 'var(--foreground)' }}>{n.title}</p>
                                            <p style={{ margin: '2px 0 0', fontSize: '0.75rem', color: 'var(--muted-foreground)', lineHeight: 1.4 }}>{n.body}</p>
                                        </div>
                                        <span style={{ fontSize: '0.7rem', color: 'var(--muted-foreground)', whiteSpace: 'nowrap', marginTop: 2 }}>
                                            {timeAgo(n.created_at)}
                                        </span>
                                    </div>
                                    {!n.is_read && (
                                        <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: 'var(--secondary, #6366f1)', marginTop: 6 }} />
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
