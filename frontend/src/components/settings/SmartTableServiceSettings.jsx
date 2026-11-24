import React, { useEffect, useState } from 'react';
import { AlertTriangle, BellRing, Clock, Save, X } from 'lucide-react';
import { toast } from 'sonner';
import { tableServiceAPI } from '../../services/api';

const NAMES = {
  no_order: 'No order after seating',
  after_drinks: 'Drinks served, no food order',
  mains_held: 'Entrée served, mains not fired',
  mains_delayed: 'Mains fired, kitchen delayed',
  ready_waiting: 'Food ready, not collected',
  post_mains: 'Mains served, no guest follow-up',
  bill_waiting: 'Bill requested, not handled',
};
const ruleOrder = Object.keys(NAMES);

export default function SmartTableServiceSettings({ open, onClose, isOwner }) {
  const [config, setConfig] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    let active = true;
    setConfig(null);
    setError('');
    tableServiceAPI.getSettings()
      .then(res => { if (active) setConfig(res.data); })
      .catch(() => { if (active) setError('Unable to load service alert settings'); });
    return () => { active = false; };
  }, [open]);

  if (!open) return null;

  const patch = (key, value) => setConfig(s => ({ ...s, [key]: value }));
  const patchRule = (key, field, value) =>
    setConfig(s => ({ ...s, rules: {
      ...s.rules, [key]: { ...s.rules[key], [field]: value },
    }}));
  const save = async () => {
    if (!isOwner || !config) return;
    for (const item of Object.values(config.rules || {})) {
      const warn = Number(item.warningMinutes);
      const urgent = Number(item.escalateMinutes);
      if (!Number.isInteger(warn) || warn < 1 || warn > 240 ||
          !Number.isInteger(urgent) || urgent < warn || urgent > 360) {
        toast.error('Set a warning between 1–240 min and an escalation at or after it (up to 360 min)');
        return;
      }
    }
    setBusy(true);
    try {
      await tableServiceAPI.updateSettings(config);
      toast.success('Service alert rules saved');
      onClose();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Unable to save service alert rules');
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-[80] bg-black/45 flex items-center justify-center p-3"
      data-testid="smart-service-settings-overlay">
      <section role="dialog" aria-modal="true" aria-label="Smart Table Service settings"
        className="bg-white text-slate-900 rounded-xl shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col">
        <div className="p-4 border-b flex items-center gap-2">
          <BellRing size={20} className="text-orange-600" />
          <h2 className="text-lg font-semibold flex-1">Smart Table Service</h2>
          <button type="button" onClick={onClose} aria-label="Close settings"><X size={20}/></button>
        </div>
        <div className="overflow-y-auto p-4 space-y-4">
          {error && <p role="alert" className="text-red-600">{error}</p>}
          {!config && !error && <p>Loading service rules...</p>}
          {config && <>
            <label className="flex gap-3 items-start rounded-lg border p-3 text-sm">
              <input type="checkbox" checked={config.enabled} disabled={!isOwner || busy}
                onChange={e => patch('enabled', e.target.checked)} />
              <span><strong>Enable automatic service reminders</strong>
                <span className="block text-xs text-slate-500">
                  Off until the owner enables it. Reminders never automatically fire kitchen courses.
                </span>
              </span>
            </label>
            <label className="flex gap-3 items-center text-sm">
              <input type="checkbox" checked={config.popupEnabled} disabled={!isOwner || busy}
                onChange={e => patch('popupEnabled', e.target.checked)} />
              Show on-screen floor-staff pop-ups
            </label>
            <p className="text-xs text-slate-500">
              Each rule starts from an actual seating, kitchen or staff-recorded event.
              Staff can acknowledge, snooze or resolve reminders. Escalated alerts return
              if the underlying problem is still outstanding.
            </p>
            <div className="space-y-2">
              {ruleOrder.map(key => {
                const rule = config.rules?.[key];
                if (!rule) return null;
                return <div key={key} className="rounded-lg border p-3 grid grid-cols-1 sm:grid-cols-[1fr_95px_95px] gap-3 items-center">
                  <label className="flex items-center gap-2 text-sm font-medium">
                    <input type="checkbox" disabled={!isOwner || busy} checked={rule.enabled}
                      onChange={e => patchRule(key, 'enabled', e.target.checked)}/>
                    {NAMES[key]}
                  </label>
                  <label className="text-xs text-slate-500 flex flex-col gap-1">
                    <span><Clock size={12} className="inline" /> Warn (min)</span>
                    <input aria-label={NAMES[key] + ' warning minutes'} type="number" min="1" max="240"
                      disabled={!isOwner || busy || !rule.enabled} value={rule.warningMinutes}
                      onChange={e => patchRule(key, 'warningMinutes', Number(e.target.value))}
                      className="rounded border px-2 py-1 text-slate-900"/>
                  </label>
                  <label className="text-xs text-slate-500 flex flex-col gap-1">
                    <span><AlertTriangle size={12} className="inline" /> Escalate</span>
                    <input aria-label={NAMES[key] + ' escalation minutes'} type="number" min="1" max="360"
                      disabled={!isOwner || busy || !rule.enabled} value={rule.escalateMinutes}
                      onChange={e => patchRule(key, 'escalateMinutes', Number(e.target.value))}
                      className="rounded border px-2 py-1 text-slate-900"/>
                  </label>
                </div>;
              })}
            </div>
          </>}
        </div>
        <div className="p-4 border-t flex justify-end gap-2">
          <button type="button" onClick={onClose} className="border rounded px-4 py-2 text-sm">Close</button>
          {isOwner && <button type="button" disabled={!config || busy} onClick={save}
            className="bg-slate-900 text-white rounded px-4 py-2 text-sm flex items-center gap-2">
            <Save size={14}/> Save rules
          </button>}
        </div>
      </section>
    </div>
  );
}
