import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, BellRing, Check, ChevronRight, Clock3, X } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';
import { tableServiceAPI } from '../services/api';

const ROLES = new Set(['owner', 'manager', 'cashier', 'server', 'kitchen']);
const shortAge = value => {
  const diff = Date.now() - new Date(value).getTime();
  return Number.isFinite(diff) && diff > 0 ? Math.floor(diff / 60000) + ' min ago' : 'Just now';
};

/** Non-blocking, role-scoped overlay available on every NUA POS staff screen.
 * The owner has to opt into the feature before any popup is shown.
 * Actions modify server state and never trigger a kitchen fire automatically.
 */
export default function SmartTableAlerts() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const businessId = user?.businessId;
  const role = user?.role;
  const [alerts, setAlerts] = useState([]);
  const [enabled, setEnabled] = useState(false);
  const [popupEnabled, setPopupEnabled] = useState(true);
  const [queueOpen, setQueueOpen] = useState(false);
  const [dismissed, setDismissed] = useState({});
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState('');
  const requestSerial = useRef(0);
  const canSee = ROLES.has(role) && businessId && !businessId.startsWith('nb_') && !businessId.startsWith('nl_');

  const refresh = useCallback(async () => {
    if (!canSee) return;
    const serial = ++requestSerial.current;
    try {
      const response = await tableServiceAPI.getAlerts();
      if (serial !== requestSerial.current) return;
      setAlerts(response.data?.alerts || []);
      setEnabled(response.data?.enabled === true);
      setPopupEnabled(response.data?.popupEnabled !== false);
      setError('');
    } catch (e) {
      if (serial !== requestSerial.current) return;
      // Fail closed when API isn't deployed, credentials change, or offline.
      setAlerts([]);
      setEnabled(false);
      setError('Live service reminders unavailable. Check connection.');
    }
  }, [businessId, canSee]);

  useEffect(() => {
    requestSerial.current += 1;
    setAlerts([]); setEnabled(false); setDismissed({}); setQueueOpen(false);
    if (!canSee) return undefined;
    refresh();
    const interval = window.setInterval(refresh, 15000);
    const whenVisible = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', whenVisible);
    return () => {
      requestSerial.current += 1;
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', whenVisible);
    };
  }, [canSee, refresh]);

  const actionable = useMemo(() => alerts.filter(a => a.status === 'open'), [alerts]);
  const popup = enabled && popupEnabled && !queueOpen
    ? actionable.find(a => !dismissed[a.id + ':' + a.level]) : null;
  const act = async (alert, action, data) => {
    setBusy(alert.id);
    try {
      if (action === 'acknowledge') await tableServiceAPI.acknowledge(alert.id);
      if (action === 'resolve') await tableServiceAPI.resolve(alert.id);
      if (action === 'snooze') await tableServiceAPI.snooze(alert.id, Number(data || 3));
      setDismissed(prev => ({ ...prev, [alert.id + ':' + alert.level]: true }));
      await refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Service alert could not be updated');
    } finally { setBusy(null); }
  };
  const openTable = alert => {
    setDismissed(prev => ({ ...prev, [alert.id + ':' + alert.level]: true }));
    setQueueOpen(false);
    navigate('/floor-plan?tableId=' + encodeURIComponent(alert.tableId));
  };

  if (!canSee || !enabled) return null;
  const urgent = actionable.filter(a => a.level === 'urgent').length;
  return <>
    <button type="button" data-testid="smart-alerts-open-queue" onClick={() => setQueueOpen(v => !v)}
      className="fixed bottom-24 left-5 z-40 bg-slate-900 text-white shadow-lg rounded-full px-4 py-3 flex gap-2 items-center text-sm border border-white/20"
      aria-label={'Table service attention queue, ' + actionable.length + ' active alerts'}>
      <BellRing size={18} className={urgent ? 'text-red-400' : 'text-amber-300'} />
      Attention {actionable.length}
      {urgent > 0 && <span className="bg-red-500 rounded-full px-2">{urgent} urgent</span>}
    </button>

    {popup && <section role="alert" aria-label="Table service reminder"
      data-testid="smart-service-popup" className="fixed bottom-40 right-4 z-[65] w-[min(92vw,390px)] rounded-xl bg-white text-slate-900 border-2 border-amber-400 shadow-2xl p-4 space-y-3">
      <div className="flex items-start gap-2">
        <AlertTriangle size={20} className={popup.level === 'urgent' ? 'text-red-600' : 'text-amber-600'} />
        <div className="flex-1">
          <strong>Table {popup.tableNumber} — {popup.title}</strong>
          <p className="text-xs text-slate-500 mt-1">{popup.level === 'urgent' ? 'Escalated service attention' : 'Service attention required'}</p>
        </div>
        <button type="button" aria-label="Dismiss popup" onClick={() => setDismissed(d => ({...d, [popup.id + ':' + popup.level]: true}))}>
          <X size={18}/>
        </button>
      </div>
      <p className="text-sm">{popup.message}</p>
      <p className="text-xs text-slate-500"><Clock3 size={13} className="inline" /> {shortAge(popup.eventAt)}</p>
      <div className="flex flex-wrap gap-2 text-xs">
        <button type="button" onClick={() => openTable(popup)} className="bg-slate-900 text-white rounded px-3 py-2">Review table</button>
        <button type="button" disabled={busy === popup.id} onClick={() => act(popup, 'acknowledge')}
          className="border rounded px-3 py-2">Acknowledge</button>
        <button type="button" disabled={busy === popup.id} onClick={() => act(popup, 'snooze', 3)}
          className="border rounded px-3 py-2">Snooze 3 min</button>
      </div>
    </section>}

    {queueOpen && <div className="fixed inset-0 z-[70]" data-testid="smart-service-attention-queue">
      <button type="button" aria-label="Close attention queue" className="absolute inset-0 bg-black/30"
        onClick={() => setQueueOpen(false)}/>
      <aside className="absolute right-0 inset-y-0 w-full sm:max-w-md bg-white text-slate-900 shadow-2xl flex flex-col" aria-label="Table attention queue">
        <div className="flex items-center gap-2 border-b p-4">
          <BellRing size={20} className="text-amber-600"/>
          <h2 className="font-semibold text-lg flex-1">Tables needing attention</h2>
          <button type="button" onClick={() => setQueueOpen(false)} aria-label="Close queue"><X size={20}/></button>
        </div>
        <div className="overflow-y-auto p-3 space-y-3">
          {error && <p className="text-xs text-amber-800">{error}</p>}
          {!alerts.length && <p className="p-6 text-slate-500 text-sm text-center">No active table service alerts.</p>}
          {alerts.map(alert => <div key={alert.id}
            className={'border rounded-xl p-3 space-y-2 ' + (alert.level === 'urgent' ? 'border-red-300' : 'border-slate-200')}>
            <div className="flex items-center gap-2">
              <strong className="flex-1">Table {alert.tableNumber}: {alert.title}</strong>
              <span className={'text-xs uppercase font-semibold ' + (alert.level === 'urgent' ? 'text-red-700' : 'text-amber-700')}>
                {alert.level}
              </span>
            </div>
            <p className="text-sm">{alert.message}</p>
            <p className="text-xs text-slate-500">
              {shortAge(alert.eventAt)} · {alert.status}
            </p>
            <div className="flex flex-wrap gap-2 text-xs">
              <button type="button" onClick={() => openTable(alert)} className="bg-slate-900 text-white px-2 py-1.5 rounded flex items-center gap-1">
                Open table <ChevronRight size={13}/>
              </button>
              {alert.status === 'open' && <button type="button" disabled={busy === alert.id} onClick={() => act(alert, 'acknowledge')}
                className="border rounded px-2 py-1.5 flex items-center gap-1"><Check size={13}/> Acknowledge</button>}
              {alert.status !== 'snoozed' && <button type="button" disabled={busy === alert.id} onClick={() => act(alert, 'snooze', 3)}
                className="border rounded px-2 py-1.5">Snooze</button>}
              <button type="button" disabled={busy === alert.id} onClick={() => act(alert, 'resolve')}
                className="border rounded px-2 py-1.5">Resolve</button>
            </div>
          </div>)}
        </div>
      </aside>
    </div>}
  </>;
}
