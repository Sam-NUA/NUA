import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BellRing, Clock, Settings2, X, Check, PauseCircle, RefreshCw } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useLocation, useNavigate } from 'react-router-dom';
import { usePOS } from '../contexts/POSContext';
import { tableServiceAPI } from '../services/api';
import { toast } from 'sonner';

const RULE_NAMES = {
  seated_no_order: 'Take order',
  drinks_no_food: 'Check food order',
  mains_not_fired: 'Fire mains reminder',
  kitchen_delayed: 'Kitchen taking too long',
  food_waiting: 'Collect ready food',
  post_mains_check: 'Check on guests',
  bill_waiting: 'Deliver bill',
};
const initial = { enabled: false, rules: {} };

// Globally mounted inside the authenticated POS shell. No new dependency,
// no blocking prompts, and no dangerous automatic Fire action.
export default function TableServiceAlerts() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { currentUser } = usePOS();
  const sessionKey = user ? [user.businessId, user.id || user.email, user.role].join(':') : '';
  const currentSessionRef = useRef(sessionKey);
  currentSessionRef.current = sessionKey;
  const responseSequence = useRef(0);
  const staffKey = currentUser?.id || currentUser?.email || currentUser?.name || '';
  const [alerts, setAlerts] = useState([]);
  const [nextCheckAt, setNextCheckAt] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [acting, setActing] = useState(null);
  // A dismissed normal reminder must reappear if it later escalates to urgent.
  const dismissed = useRef(new Set());
  const dismissKey = alert => `${alert.id}:${alert.priority}`;
  const isManager = ['owner', 'manager'].includes(user?.role);

  const refresh = useCallback(async () => {
    if (!sessionKey) return;
    const sequence = ++responseSequence.current;
    try {
      const response = await tableServiceAPI.listAlerts();
      // Ignore a previous staff member's response after a terminal login
      // switch, or an older response arriving after a newer one.
      if (currentSessionRef.current !== sessionKey || sequence !== responseSequence.current) return;
      setAlerts(response.data?.alerts || []);
      setEnabled(!!response.data?.enabled);
      setNextCheckAt(response.data?.nextCheckAt || null);
    } catch {
      // Never interrupt checkout or kitchen firing if the terminal is offline.
    }
  }, [sessionKey]);

  useEffect(() => {
    dismissed.current.clear();
    setAlerts([]);
    setEnabled(false);
    setNextCheckAt(null);
    if (!sessionKey) return undefined;
    refresh(); // Checks immediately after login, including a shared POS terminal.
    const interval = setInterval(refresh, 15000); // Safety poll if a push/event is missed.
    const onFocus = () => refresh();
    const onVisible = () => { if (document.visibilityState === 'visible') refresh(); };
    window.addEventListener('focus', onFocus);
    window.addEventListener('pageshow', onFocus);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('pageshow', onFocus);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [refresh, sessionKey]);

  // Entering POS, opening another order, or switching the active floor-staff
  // identity must prompt a fresh evaluation without waiting for the poll.
  useEffect(() => { if (sessionKey) refresh(); }, [location.pathname, location.search, staffKey, refresh, sessionKey]);

  useEffect(() => {
    if (!sessionKey) return undefined;
    let lastActivityRefresh = 0;
    const onTerminalActivity = (event) => {
      const inPOS = location.pathname.startsWith('/pos');
      if (event.type === 'keydown' && (!inPOS || !['Enter', 'Tab', 'Escape'].includes(event.key))) return;
      if (!inPOS) {
        // Bills, order recall and table checks can be opened from screens
        // outside /pos too. Only observe relevant buttons in those screens.
        if (event.type !== 'pointerdown') return;
        const control = event.target?.closest?.('button, [role="button"], [data-testid]');
        const label = [control?.getAttribute('data-testid'), control?.getAttribute('aria-label'),
          (control?.textContent || '').slice(0, 100)].filter(Boolean).join(' ');
        if (!/\b(bill|print|receipt|table|order)\b/i.test(label)) return;
      }
      const now = Date.now();
      // Refresh without blocking the staff's original tap or checkout action.
      if (now - lastActivityRefresh < 8000) return;
      lastActivityRefresh = now;
      refresh();
    };
    document.addEventListener('pointerdown', onTerminalActivity, true);
    document.addEventListener('keydown', onTerminalActivity, true);
    return () => {
      document.removeEventListener('pointerdown', onTerminalActivity, true);
      document.removeEventListener('keydown', onTerminalActivity, true);
    };
  }, [sessionKey, location.pathname, refresh]);

  useEffect(() => {
    if (!sessionKey || !nextCheckAt) return undefined;
    const due = Date.parse(nextCheckAt);
    if (!Number.isFinite(due)) return undefined;
    // Server-computed first-warning and escalation deadlines. A bounded
    // safety poll remains active if the terminal clock or network drifts.
    const delay = Math.max(300, Math.min(15_000, due - Date.now() + 300));
    const timeout = setTimeout(refresh, delay);
    return () => clearTimeout(timeout);
  }, [sessionKey, nextCheckAt, refresh]);

  const active = useMemo(() => alerts.filter(a => a.status === 'open'), [alerts]);
  const incoming = active.find(a => !dismissed.current.has(dismissKey(a)));
  const openSettings = async () => {
    try {
      const response = await tableServiceAPI.getSettings();
      setSettings(response.data);
      setSettingsOpen(true);
    } catch { toast.error('Could not load service alert settings'); }
  };

  const takeAction = async (alert, action, minutes = 3) => {
    setActing(alert.id);
    try {
      await tableServiceAPI.action(alert.id, action, minutes);
      if (action === 'snooze') dismissed.current.delete(dismissKey(alert));
      else dismissed.current.add(dismissKey(alert));
      await refresh();
      toast.success(action === 'snooze' ? 'Reminder snoozed' :
        action === 'resolve' ? 'Reminder resolved' : 'Reminder acknowledged');
    } catch { toast.error('Could not update reminder'); }
    finally { setActing(null); }
  };

  const saveSettings = async () => {
    setBusy(true);
    try {
      await tableServiceAPI.saveSettings(settings);
      toast.success('Table service rules saved');
      setSettingsOpen(false);
      await refresh();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not save service settings');
    } finally { setBusy(false); }
  };

  const gotoTable = (alert) => {
    dismissed.current.add(dismissKey(alert));
    setPanelOpen(false);
    navigate(alert.category === 'kitchen' && user?.role === 'kitchen' ? '/kitchen' : '/floor-plan?tableId=' + encodeURIComponent(alert.tableId));
  };

  if (!user) return null;
  return (
    <>
      {(enabled || isManager) && (
        <button type="button" onClick={() => setPanelOpen(true)}
          className="fixed top-20 right-5 z-40 flex items-center gap-2 rounded-full border bg-white px-4 py-3 shadow-xl text-slate-800"
          aria-label="Table service attention queue" data-testid="table-service-attention-button">
          <BellRing size={18} />
          <span className="text-xs font-semibold">Table attention</span>
          {active.length > 0 && (
            <span className="rounded-full bg-rose-600 px-2 py-0.5 text-xs font-bold text-white">{active.length}</span>
          )}
        </button>
      )}

      {incoming && !panelOpen && !settingsOpen && (
        <section role="alertdialog" aria-labelledby="service-alert-title" aria-describedby="service-alert-message"
          className="fixed top-36 left-5 right-5 sm:left-auto sm:right-5 sm:w-96 z-[90] rounded-2xl border-2 border-orange-500 bg-white p-4 shadow-2xl text-slate-900"
          data-testid="smart-table-popup">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <BellRing className="text-orange-600" size={20} />
              <strong id="service-alert-title">Table {incoming.tableNumber} — {incoming.title}</strong>
            </div>
            <button type="button" className="p-1" aria-label="Dismiss pop-up" onClick={() => {
              dismissed.current.add(dismissKey(incoming));
              setAlerts(v => [...v]);
            }}><X size={18} /></button>
          </div>
          <p id="service-alert-message" className="mt-2 text-sm">{incoming.message}</p>
          <p className="mt-1 flex items-center gap-1 text-xs text-slate-500">
            <Clock size={13} /> {incoming.elapsedMinutes} minutes
            {incoming.priority === 'urgent' && <span className="ml-2 font-bold text-rose-600">ESCALATED</span>}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => gotoTable(incoming)}
              className="rounded-lg bg-[#6B1738] px-3 py-2 text-xs font-semibold text-white">Open table</button>
            <button type="button" disabled={acting === incoming.id}
              onClick={() => takeAction(incoming, 'acknowledge')}
              className="rounded-lg border px-3 py-2 text-xs font-semibold">Acknowledge</button>
            <button type="button" disabled={acting === incoming.id}
              onClick={() => takeAction(incoming, 'snooze', 3)}
              className="rounded-lg border px-3 py-2 text-xs font-semibold">Snooze 3m</button>
          </div>
        </section>
      )}

      {panelOpen && (
        <div className="fixed inset-0 z-[85] bg-black/40" role="presentation" onClick={() => setPanelOpen(false)}>
          <aside role="dialog" aria-label="Table attention queue" aria-modal="true"
            className="absolute right-0 top-0 bottom-0 w-full max-w-md overflow-y-auto bg-white text-slate-900 shadow-2xl"
            onClick={(e) => e.stopPropagation()}>
            <header className="sticky top-0 flex items-center justify-between gap-2 border-b bg-white p-4">
              <div><h2 className="font-bold text-lg">Table attention queue</h2>
                <p className="text-xs text-slate-500">{active.length} active · Checks at alert deadlines and on terminal activity</p></div>
              <div className="flex items-center gap-1">
                <button type="button" className="p-2" onClick={refresh} aria-label="Refresh alerts"><RefreshCw size={19}/></button>
                {isManager && <button type="button" className="p-2" onClick={openSettings} aria-label="Configure alert timings"><Settings2 size={19}/></button>}
                <button type="button" className="p-2" onClick={() => setPanelOpen(false)} aria-label="Close attention queue"><X size={19}/></button>
              </div>
            </header>
            <div className="p-4 space-y-3">
              {alerts.length === 0 && <p className="rounded-xl bg-slate-50 p-4 text-sm">All tables are on track.</p>}
              {alerts.map(alert => (
                <article key={alert.id} className={'rounded-xl border-l-4 p-3 shadow-sm ' +
                  (alert.priority === 'urgent' ? 'border-rose-600 bg-rose-50' : 'border-amber-500 bg-amber-50')}>
                  <div className="flex items-start justify-between gap-3">
                    <strong>Table {alert.tableNumber} · {alert.title}</strong>
                    <span className="text-xs whitespace-nowrap">{alert.elapsedMinutes} min</span>
                  </div>
                  <p className="my-2 text-sm">{alert.message}</p>
                  <p className="mb-2 text-xs text-slate-500">{alert.status === 'acknowledged' ? 'Acknowledged · ' : ''}{alert.category === 'kitchen' ? 'Kitchen' : 'Floor service'}</p>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="rounded-lg bg-[#6B1738] px-3 py-2 text-xs text-white" onClick={() => gotoTable(alert)}>Open table</button>
                    {alert.status === 'open' && <button type="button" className="rounded-lg border bg-white px-2 py-1 text-xs" onClick={() => takeAction(alert, 'acknowledge')} disabled={!!acting}><Check size={14} className="inline"/> Ack</button>}
                    <button type="button" className="rounded-lg border bg-white px-2 py-1 text-xs" onClick={() => takeAction(alert, 'snooze')} disabled={!!acting}><PauseCircle size={14} className="inline"/> Snooze</button>
                    <button type="button" className="rounded-lg border bg-white px-2 py-1 text-xs" onClick={() => takeAction(alert, 'resolve')} disabled={!!acting}>Resolve</button>
                  </div>
                </article>
              ))}
            </div>
          </aside>
        </div>
      )}

      {isManager && settingsOpen && (
        <div className="fixed inset-0 z-[95] flex items-center justify-center bg-black/50 p-3">
          <section role="dialog" aria-modal="true" aria-label="Service alert settings"
            className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-5 text-slate-900 shadow-2xl">
            <div className="flex justify-between items-center">
              <h2 className="text-lg font-bold">Smart Table Service timings</h2>
              <button type="button" onClick={() => setSettingsOpen(false)} aria-label="Close settings"><X size={20}/></button>
            </div>
            <p className="mt-1 mb-4 text-xs text-slate-500">Alerts never fire food automatically. Configure each stage for your venue.</p>
            <label className="flex items-center gap-3 rounded-xl bg-slate-50 p-3">
              <input type="checkbox" checked={!!settings.enabled}
                onChange={e => setSettings(v => ({...v, enabled: e.target.checked}))}
                data-testid="table-service-enabled"/>
              <span className="font-medium">Enable automatic service reminders for this business</span>
            </label>
            <div className="mt-4 space-y-3">
              {Object.entries(settings.rules || {}).map(([key, rule]) => (
                <div key={key} className="rounded-xl border p-3" data-testid={'service-rule-' + key}>
                  <label className="flex items-center gap-2 text-sm font-semibold">
                    <input type="checkbox" checked={!!rule.enabled}
                      onChange={e => setSettings(v => ({...v, rules: {...v.rules, [key]: {...v.rules[key], enabled: e.target.checked}}}))}/>
                    {RULE_NAMES[key] || key}
                  </label>
                  <div className="mt-2 grid grid-cols-2 gap-3">
                    {[
                      {field:'minutes', label:'First warning (min)'},
                      {field:'escalateMinutes', label:'Escalate after (min)'},
                    ].map(({field,label})=> (
                      <label key={field} className="text-xs text-slate-600">
                        {label}
                        <input type="number" min="1" max={field === 'minutes' ? 240 : 480}
                          value={rule[field]}
                          onChange={e => setSettings(v => ({...v, rules: {...v.rules, [key]: {...v.rules[key], [field]: Number(e.target.value)}}}))}
                          className="mt-1 block w-full rounded-lg border px-3 py-2 text-base text-slate-900"/>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="rounded-lg border px-4 py-2" onClick={() => setSettingsOpen(false)}>Cancel</button>
              <button type="button" disabled={busy} className="rounded-lg bg-[#6B1738] px-4 py-2 font-semibold text-white" onClick={saveSettings}>Save settings</button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
