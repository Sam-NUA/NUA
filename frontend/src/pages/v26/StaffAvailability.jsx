import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { useToast } from '../../hooks/use-toast';
import { useTheme } from '../../contexts/ThemeContext';
import { v26API } from '../../services/api';
import { SecureStorageService } from '../../platform';
import { Users2, Plus, Save } from 'lucide-react';

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export default function StaffAvailability() {
  const { theme } = useTheme(); const { toast } = useToast();
  const [staff, setStaff] = useState([]);
  const [selected, setSelected] = useState(null);
  const [data, setData] = useState({ weeklyAvailable: [], blackoutDates: [] });

  useEffect(() => {
    (async () => {
      const token = await SecureStorageService.getToken();
      fetch(`${process.env.REACT_APP_BACKEND_URL}/api/auth/staff`, { headers: { Authorization: `Bearer ${token}` } })
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then(d => setStaff(Array.isArray(d) ? d : []))
        .catch(() => { setStaff([]); toast({ title: 'Failed to load staff list', variant: 'destructive' }); });
    })();
  }, [toast]);

  const load = async (s) => {
    setSelected(s);
    const r = await v26API.getAvailability(s.id);
    setData({ weeklyAvailable: r.data.weeklyAvailable || [], blackoutDates: r.data.blackoutDates || [] });
  };

  const toggleDay = (d) => {
    setData(prev => ({ ...prev, weeklyAvailable: prev.weeklyAvailable.includes(d)
      ? prev.weeklyAvailable.filter(x => x !== d) : [...prev.weeklyAvailable, d] }));
  };

  const addBlackout = () => {
    const from = prompt('Blackout FROM (YYYY-MM-DD)?'); if (!from) return;
    const to = prompt('Blackout TO (YYYY-MM-DD)?') || from;
    const reason = prompt('Reason?') || 'unavailable';
    setData(prev => ({ ...prev, blackoutDates: [...prev.blackoutDates, { from, to, reason }] }));
  };

  const save = async () => {
    try { await v26API.setAvailability(selected.id, data); toast({ title: 'Saved' }); }
    catch (e) { toast({ title: 'Failed', variant: 'destructive' }); }
  };

  return (
    <div className="space-y-6" data-testid="staff-availability-page">
      <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
        <Users2 className="text-indigo-600" /> Staff Availability
      </h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card><CardContent className="p-0">
          <div className="px-4 py-3 border-b font-bold text-sm">Staff</div>
          <div className="max-h-[60vh] overflow-y-auto">
            {staff.filter(s => ['cashier','barista','kitchen','manager'].includes(s.role)).map(s => (
              <button key={s.id} onClick={() => load(s)} className={`w-full text-left px-4 py-2 text-sm border-b hover:bg-gray-50 ${selected?.id === s.id ? 'bg-amber-50' : ''}`} data-testid={`staff-${s.id}`}>
                <p className="font-medium">{s.name}</p>
                <p className="text-xs text-gray-500">{s.role}</p>
              </button>
            ))}
          </div>
        </CardContent></Card>
        <Card className="md:col-span-2"><CardContent className="p-5">
          {!selected ? <p className="text-center py-12 text-gray-400">Pick a staff member</p> : (
            <div className="space-y-4">
              <h2 className="font-bold">{selected.name}</h2>
              <div>
                <p className="text-xs uppercase text-gray-500 mb-2">Weekly Available</p>
                <div className="flex gap-2 flex-wrap">
                  {DOW.map(d => (
                    <button key={d} onClick={() => toggleDay(d)}
                      className={`px-3 py-1.5 rounded-lg border transition ${data.weeklyAvailable.includes(d) ? 'text-white border-transparent' : 'bg-white border-gray-300 hover:border-gray-400'}`}
                      style={data.weeklyAvailable.includes(d) ? { background: theme.primary } : {}}
                      data-testid={`day-${d}`}>{d}</button>
                  ))}
                </div>
              </div>
              <div>
                <div className="flex justify-between items-center mb-2">
                  <p className="text-xs uppercase text-gray-500">Blackout Dates / Holidays</p>
                  <Button size="sm" variant="outline" onClick={addBlackout} data-testid="add-blackout"><Plus size={12} className="mr-1" /> Add</Button>
                </div>
                <div className="space-y-1">
                  {data.blackoutDates.length === 0 ? <p className="text-xs text-gray-400">None</p> :
                    data.blackoutDates.map((b, i) => (
                      <div key={i} className="flex justify-between items-center p-2 border rounded text-sm">
                        <span>{b.from} → {b.to} <span className="text-gray-500">({b.reason})</span></span>
                        <button onClick={() => setData(prev => ({ ...prev, blackoutDates: prev.blackoutDates.filter((_, x) => x !== i) }))} className="text-red-500">×</button>
                      </div>
                    ))}
                </div>
              </div>
              <Button onClick={save} style={{ background: theme.primary }} data-testid="save-availability"><Save size={14} className="mr-1.5" /> Save</Button>
            </div>
          )}
        </CardContent></Card>
      </div>
    </div>
  );
}
