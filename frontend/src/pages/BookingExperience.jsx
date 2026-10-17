import React, { useState, useEffect } from 'react';
import { Sparkles, Plus, Edit, Trash2, Save, Calendar } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { reservationFeaturesAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

const DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

export default function BookingExperience() {
  const { theme } = useTheme();
  const [experiences, setExperiences] = useState([]);
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: '', description: '', days: [], startDate: '', endDate: '', pricePerPerson: '', maxBookings: 50, active: true });

  useEffect(() => { fetchData(); }, []);
  const fetchData = async () => { try { const r = await reservationFeaturesAPI.getExperiences(); setExperiences(r.data); } catch {} };

  const openAdd = () => { setEditing(null); setForm({ name: '', description: '', days: [], startDate: '', endDate: '', pricePerPerson: '', maxBookings: 50, active: true }); setShowDialog(true); };
  const openEdit = (e) => { setEditing(e); setForm({ name: e.name, description: e.description, days: e.days || [], startDate: e.startDate || '', endDate: e.endDate || '', pricePerPerson: e.pricePerPerson || '', maxBookings: e.maxBookings || 50, active: e.active }); setShowDialog(true); };

  const handleSave = async () => {
    const data = { ...form, pricePerPerson: parseFloat(form.pricePerPerson) || 0, maxBookings: parseInt(form.maxBookings) || 50 };
    try {
      if (editing) { await reservationFeaturesAPI.updateExperience(editing.id, data); toast.success('Experience updated'); }
      else { await reservationFeaturesAPI.createExperience(data); toast.success('Experience created'); }
      setShowDialog(false); fetchData();
    } catch { toast.error('Failed'); }
  };

  const handleDelete = async (id) => {
    if (!await DialogService.confirm('Delete this experience?')) return;
    try { await reservationFeaturesAPI.deleteExperience(id); toast.success('Deleted'); fetchData(); } catch {}
  };

  return (
    <div className="space-y-6" data-testid="experience-page">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold" style={{ color: theme.text }}>Booking Experiences</h1><p className="text-sm text-gray-500">Create special dining experiences for bookings</p></div>
        <Button style={{ backgroundColor: theme.primary }} onClick={openAdd} data-testid="add-experience-btn"><Plus size={16} className="mr-1" /> New Experience</Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {experiences.map(exp => (
          <Card key={exp.id} data-testid={`exp-${exp.id}`}>
            <CardContent className="p-5">
              <div className="flex items-start justify-between mb-3">
                <div><h3 className="font-bold text-lg">{exp.name}</h3><p className="text-sm text-gray-500">{exp.description}</p></div>
                <Badge className={exp.active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>{exp.active ? 'Active' : 'Inactive'}</Badge>
              </div>
              <div className="grid grid-cols-3 gap-2 text-sm mb-3">
                <div><p className="text-gray-500">Price</p><p className="font-bold">${exp.pricePerPerson}/pp</p></div>
                <div><p className="text-gray-500">Max Bookings</p><p className="font-bold">{exp.maxBookings}</p></div>
                <div><p className="text-gray-500">Days</p><p className="font-bold text-xs">{(exp.days || []).map(d => d.slice(0,3)).join(', ') || 'All'}</p></div>
              </div>
              {(exp.startDate || exp.endDate) && <p className="text-xs text-gray-400">{exp.startDate} → {exp.endDate}</p>}
              <div className="flex gap-2 mt-3"><Button variant="outline" size="sm" onClick={() => openEdit(exp)}><Edit size={14} /></Button><Button variant="outline" size="sm" className="text-red-500" onClick={() => handleDelete(exp.id)}><Trash2 size={14} /></Button></div>
            </CardContent>
          </Card>
        ))}
        {experiences.length === 0 && <Card className="col-span-2 border-dashed"><CardContent className="p-12 text-center"><Sparkles size={40} className="mx-auto mb-3 text-gray-300" /><p className="text-gray-500">No experiences yet</p></CardContent></Card>}
      </div>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-w-md" data-testid="experience-dialog">
          <DialogHeader><DialogTitle>{editing ? 'Edit Experience' : 'New Experience'}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2 max-h-[60vh] overflow-y-auto">
            <Input placeholder="Experience name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="exp-name" />
            <textarea className="w-full min-h-[60px] p-2 border rounded-md text-sm" placeholder="Description..." value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
            <div className="grid grid-cols-2 gap-2">
              <Input type="number" step="0.01" placeholder="Price per person" value={form.pricePerPerson} onChange={e => setForm({ ...form, pricePerPerson: e.target.value })} data-testid="exp-price" />
              <Input type="number" placeholder="Max bookings" value={form.maxBookings} onChange={e => setForm({ ...form, maxBookings: e.target.value })} />
            </div>
            <div><label className="text-xs font-medium text-gray-500 mb-1 block">Available Days</label>
              <div className="flex flex-wrap gap-1.5">{DAYS.map(d => (
                <button key={d} type="button" onClick={() => { const days = form.days.includes(d) ? form.days.filter(x => x !== d) : [...form.days, d]; setForm({ ...form, days }); }}
                  className={`px-2.5 py-1 text-xs rounded-full font-medium ${form.days.includes(d) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}`}>{d.slice(0,3)}</button>
              ))}</div>
            </div>
            <div className="grid grid-cols-2 gap-2"><Input type="date" value={form.startDate} onChange={e => setForm({ ...form, startDate: e.target.value })} /><Input type="date" value={form.endDate} onChange={e => setForm({ ...form, endDate: e.target.value })} /></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={e => setForm({ ...form, active: e.target.checked })} /> Active</label>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleSave} data-testid="save-exp-btn">{editing ? 'Update' : 'Create'} Experience</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
