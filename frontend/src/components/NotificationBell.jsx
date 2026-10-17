import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Bell, Sparkles, ChefHat, Award, Users, ShieldCheck, X, Check } from 'lucide-react';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const KIND_ICON = {
  loyalty: Award, kitchen: ChefHat, approval: ShieldCheck,
  marketing: Sparkles, referral: Users, ash: Sparkles, system: Bell,
};
const KIND_TONE = {
  loyalty: 'text-indigo-600 bg-indigo-50',
  kitchen: 'text-amber-600 bg-amber-50',
  approval: 'text-purple-600 bg-purple-50',
  marketing: 'text-pink-600 bg-pink-50',
  referral: 'text-emerald-600 bg-emerald-50',
  ash: 'text-blue-600 bg-blue-50',
  system: 'text-slate-600 bg-slate-50',
};

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(0);
  const [items, setItems] = useState([]);

  const fetchCount = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/notifications/unread-count`, { headers: await H() });
      setCount(r.data.count || 0);
    } catch { /* silent */ }
  }, []);

  const fetchItems = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/notifications?limit=25`, { headers: await H() });
      setItems(r.data);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchCount();
    const iv = setInterval(fetchCount, 30000);
    return () => clearInterval(iv);
  }, [fetchCount]);

  useEffect(() => { if (open) fetchItems(); }, [open, fetchItems]);

  const markRead = async (id) => {
    try {
      await axios.post(`${API}/notifications/${id}/read`, {}, { headers: await H() });
      setItems(items.map(n => n.id === id ? { ...n, readAt: new Date().toISOString() } : n));
      fetchCount();
    } catch { /* silent */ }
  };

  const markAllRead = async () => {
    try {
      await axios.post(`${API}/notifications/read-all`, {}, { headers: await H() });
      fetchItems(); fetchCount();
    } catch { /* silent */ }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-20 right-24 z-40 h-12 w-12 rounded-full bg-white shadow-lg border flex items-center justify-center hover:bg-slate-50 transition"
        data-testid="notification-bell"
        aria-label="Notifications"
      >
        <Bell size={18} className="text-slate-700" />
        {count > 0 && (
          <span className="absolute -top-1 -right-1 h-5 min-w-5 px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center animate-pulse"
            data-testid="notif-count">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 bg-black/20 z-40" onClick={() => setOpen(false)} />
          <div className="fixed right-5 top-16 bottom-5 w-96 bg-white rounded-2xl shadow-2xl z-50 flex flex-col overflow-hidden" data-testid="notif-panel">
            <div className="flex justify-between items-center px-4 py-3 border-b bg-gradient-to-r from-indigo-500 to-purple-500 text-white">
              <div className="flex items-center gap-2">
                <Bell size={18} />
                <h2 className="font-semibold">Notifications</h2>
                {count > 0 && <span className="text-xs bg-white/20 px-2 py-0.5 rounded-full">{count} new</span>}
              </div>
              <div className="flex gap-2">
                {items.some(i => !i.readAt) && (
                  <button onClick={markAllRead} className="text-xs bg-white/20 hover:bg-white/30 rounded px-2 py-1" data-testid="notif-mark-all-read">
                    <Check size={12} className="inline mr-1" /> Mark all
                  </button>
                )}
                <button onClick={() => setOpen(false)} className="hover:bg-white/20 rounded p-1" data-testid="notif-close">
                  <X size={16} />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {items.length === 0 && (
                <div className="p-12 text-center text-sm text-slate-400">
                  <Bell size={28} className="mx-auto mb-2 opacity-40" />
                  Nothing yet. NUA will ping you when something needs attention.
                </div>
              )}
              {items.map(n => {
                const Icon = KIND_ICON[n.kind] || Bell;
                const tone = KIND_TONE[n.kind] || KIND_TONE.system;
                return (
                  <div key={n.id} className={`px-4 py-3 border-b hover:bg-slate-50 ${n.readAt ? 'opacity-60' : ''}`}
                    data-testid={`notif-${n.id}`}>
                    <div className="flex gap-3">
                      <div className={`h-8 w-8 rounded-full flex items-center justify-center shrink-0 ${tone}`}>
                        <Icon size={14} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between items-start gap-2">
                          <p className="font-medium text-sm">{n.title}</p>
                          {!n.readAt && (
                            <button onClick={() => markRead(n.id)} className="text-[10px] text-slate-400 hover:text-emerald-600" data-testid={`notif-read-${n.id}`}>
                              <Check size={12} />
                            </button>
                          )}
                        </div>
                        {n.body && <p className="text-xs text-slate-600 mt-0.5 leading-relaxed">{n.body}</p>}
                        <div className="flex justify-between items-center mt-1.5">
                          <span className="text-[10px] text-slate-400">{new Date(n.createdAt).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                          {n.link && (
                            <a href={n.link} onClick={() => setOpen(false)} className="text-[10px] text-indigo-600 hover:underline" data-testid={`notif-link-${n.id}`}>
                              Open →
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </>
  );
}
