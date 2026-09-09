import { useEffect, useState } from 'react';
import { BadgeAlert, Bell, Calendar, CheckCheck, FileText, ShieldAlert, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { apiClearNotifications, apiListNotifications, apiMarkAllNotificationsRead, apiSetNotificationRead } from '../services/api';
import { useStore } from '../store/useStore';
import type { TaskNotification } from '../types';

export default function Notifications() {
  const { authToken } = useStore();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<TaskNotification[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (!authToken) return;
    apiListNotifications(authToken).then(setNotifications).catch((error) => setFeedback(error instanceof Error ? error.message : 'Unable to load notifications.'));
  }, [authToken]);

  const handleToggleRead = async (notification: TaskNotification) => {
    if (!authToken) return;
    try {
      const updated = await apiSetNotificationRead(notification.id, !notification.is_read, authToken);
      setNotifications((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'Unable to update notification.');
    }
  };

  const handleMarkAllRead = async () => {
    if (!authToken) return;
    await apiMarkAllNotificationsRead(authToken);
    setNotifications((current) => current.map((item) => ({ ...item, is_read: true })));
  };

  const handleClearAll = async () => {
    if (!authToken) return;
    await apiClearNotifications(authToken);
    setNotifications([]);
  };

  const icon = (type: string) => type === 'success' ? <CheckCheck className="text-success" size={16} /> : type === 'alert' ? <BadgeAlert className="text-warning" size={16} /> : type === 'comment' ? <ShieldAlert className="text-danger" size={16} /> : <FileText className="text-blue-500" size={16} />;
  const unreadCount = notifications.filter((item) => !item.is_read).length;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-col gap-4 border-b border-border pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div><h1 className="flex items-center gap-2 text-2xl font-bold text-ink"><Bell size={24} className="text-blue-600" />Notifications Center{unreadCount > 0 && <span className="rounded-full bg-danger px-2 py-0.5 text-xs text-white">{unreadCount} new</span>}</h1><p className="mt-1 text-sm text-ink-soft">Persistent task assignments and workflow updates for your login.</p></div>
        {notifications.length > 0 && <div className="flex gap-2"><button onClick={() => void handleMarkAllRead()} className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-600">Mark all read</button><button onClick={() => void handleClearAll()} className="flex items-center gap-1 rounded-lg border border-border bg-surface-alt px-3 py-1.5 text-xs font-semibold text-ink-soft"><Trash2 size={12} /> Clear all</button></div>}
      </div>
      {feedback && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{feedback}</div>}
      <div className="space-y-3">
        {notifications.length === 0 ? <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-surface py-20 text-sm text-ink-faint"><Bell size={36} className="text-border" /><p>You are all caught up.</p></div> : notifications.map((notification) => (
          <div key={notification.id} className={`flex items-start justify-between gap-4 rounded-xl border bg-surface p-4 shadow-sm ${notification.is_read ? 'border-border opacity-75' : 'border-l-4 border-l-blue-600'}`}>
            <button className="flex flex-1 gap-3 text-left" onClick={() => notification.task_id && navigate('/tasks')}><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-alt">{icon(notification.notification_type)}</span><span><strong className="block text-sm text-ink">{notification.title}</strong><span className="mt-1 block text-xs leading-relaxed text-ink-soft">{notification.message}</span><span className="mt-1 flex items-center gap-1 font-mono text-[10px] text-ink-faint"><Calendar size={10} />{new Date(notification.created_at).toLocaleString()}</span></span></button>
            <button onClick={() => void handleToggleRead(notification)} className="rounded border border-border px-2 py-0.5 text-[10px] font-bold text-blue-600">{notification.is_read ? 'Mark unread' : 'Dismiss'}</button>
          </div>
        ))}
      </div>
    </div>
  );
}
