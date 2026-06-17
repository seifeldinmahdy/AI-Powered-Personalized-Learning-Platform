import { Bell } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { getNotifications, markNotificationRead, markAllNotificationsRead, type Notification } from '../services/notifications';

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
        // Skip if not authenticated
        if (!localStorage.getItem('access_token')) return;
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

    // Just toggle the dropdown — clearing is an explicit action (the "MARK ALL
    // READ" button or clicking a single notification), so the unread badge and
    // that button stay visible until the student acts.
    const handleOpen = () => setOpen((o) => !o);

    const handleMarkAllRead = async () => {
        try {
            await markAllNotificationsRead();
            setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
        } catch {
            toast.error('Failed to mark all as read');
        }
    };

    const handleClickNotification = async (n: Notification) => {
        if (n.is_read) return;
        try {
            await markNotificationRead(n.id);
            setNotifications((prev) =>
                prev.map((item) => item.id === n.id ? { ...item, is_read: true } : item)
            );
        } catch { /* ignore */ }
    };

    return (
        <div ref={ref} style={{ position: 'relative' }}>
            <button
                onClick={handleOpen}
                style={{ position: 'relative', padding: 6, borderRadius: 6, background: 'transparent', border: 'none', cursor: 'pointer', color: 'inherit', display: 'flex' }}
                title="Notifications"
            >
                <Bell size={20} />
                {unreadCount > 0 && (
                    <span className="t-mono" style={{
                        position: 'absolute', top: 0, right: 0,
                        background: 'var(--error-red)', color: '#fff',
                        borderRadius: 999, fontSize: 10, fontWeight: 700,
                        minWidth: 15, height: 15, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        padding: '0 3px', lineHeight: 1,
                    }}>
                        {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                )}
            </button>

            {open && (
                <div className="codex" style={{
                    position: 'absolute', right: 0, top: 'calc(100% + 12px)',
                    width: 340, background: 'var(--bg-primary)', border: '1px solid var(--hairline)',
                    borderRadius: 8, boxShadow: '0 16px 40px -16px rgba(26,22,17,0.3)', zIndex: 100, overflow: 'hidden',
                }}>
                    {/* Header */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderBottom: '1px solid var(--hairline)' }}>
                        <span className="t-label" style={{ color: 'var(--text-primary)' }}>NOTIFICATIONS</span>
                        {unreadCount > 0 && (
                            <button
                                onClick={handleMarkAllRead}
                                className="t-label"
                                style={{ color: 'var(--accent-primary)', background: 'none', border: 'none', cursor: 'pointer' }}
                            >
                                MARK ALL READ
                            </button>
                        )}
                    </div>

                    {/* List */}
                    <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                        {notifications.length === 0 ? (
                            <p className="t-mono steel" style={{ padding: '28px 16px', textAlign: 'center' }}>
                                NO NOTIFICATIONS YET
                            </p>
                        ) : (
                            notifications.map((n, i) => (
                                <div
                                    key={n.id}
                                    onClick={() => handleClickNotification(n)}
                                    style={{
                                        padding: '14px 16px',
                                        borderBottom: i < notifications.length - 1 ? '1px solid var(--hairline)' : 'none',
                                        borderLeft: n.is_read ? '2px solid transparent' : '2px solid var(--accent-primary)',
                                        background: n.is_read ? 'transparent' : 'rgba(37,99,235,0.05)',
                                        cursor: n.is_read ? 'default' : 'pointer',
                                        transition: 'background 0.2s',
                                    }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <p className="t-body" style={{ margin: 0, fontSize: 13.5, fontWeight: n.is_read ? 400 : 600, color: 'var(--text-primary)', lineHeight: 1.4 }}>{n.title}</p>
                                            <p className="t-body" style={{ margin: '3px 0 0', fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.45 }}>{n.body}</p>
                                        </div>
                                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, flexShrink: 0 }}>
                                            <span className="t-mono steel" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>
                                                {timeAgo(n.created_at)}
                                            </span>
                                            {!n.is_read && (
                                                <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--accent-primary)', display: 'inline-block' }} />
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
