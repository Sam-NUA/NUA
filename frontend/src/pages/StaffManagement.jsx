import React, { useState, useEffect } from 'react';
import {
  Users, Shield, DollarSign, Trash2, Edit2, Plus, Search,
  BarChart3, TrendingUp, PieChart
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { toast } from 'sonner';
import axios from 'axios';
import { effectiveHourlyRate, salaryTypeSuffix } from '../lib/staffPay';

const API = process.env.REACT_APP_BACKEND_URL;
const authHeader = () => ({ Authorization: `Bearer ${localStorage.getItem('nua_token')}` });

const ROLE_COLORS = {
  owner: 'bg-purple-100 text-purple-700 border-purple-300',
  manager: 'bg-blue-100 text-blue-700 border-blue-300',
  cashier: 'bg-emerald-100 text-emerald-700 border-emerald-300',
  kitchen: 'bg-amber-100 text-amber-700 border-amber-300',
};

export default function StaffManagement() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [staff, setStaff] = useState([]);
  const [laborReport, setLaborReport] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', password: 'Staff2026!', role: 'cashier', payRate: 25, salaryType: 'hourly' });
  const [tab, setTab] = useState('staff');

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [staffRes, laborRes] = await Promise.all([
        axios.get(`${API}/api/auth/staff`, { headers: authHeader() }),
        user?.role === 'owner' ? axios.get(`${API}/api/auth/reports/labor-cost`, { headers: authHeader() }) : Promise.resolve({ data: null }),
      ]);
      setStaff(staffRes.data);
      setLaborReport(laborRes.data);
    } catch (e) { toast.error('Failed to load staff data'); }
  };

  const handleAddStaff = async () => {
    try {
      // /auth/staff/add (owner-authenticated) rather than the public /auth/register:
      // register() is meant for self-signup and caps the role at cashier/kitchen, so a
      // Manager added through this dialog would otherwise get silently downgraded.
      await axios.post(`${API}/api/auth/staff/add`, form, { headers: authHeader() });
      toast.success('Staff member added');
      setShowAdd(false);
      setForm({ name: '', email: '', password: 'Staff2026!', role: 'cashier', payRate: 25, salaryType: 'hourly' });
      fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to add staff'); }
  };

  const handleDelete = async (id) => {
    try {
      await axios.delete(`${API}/api/auth/staff/${id}`, { headers: authHeader() });
      toast.success('Staff removed');
      fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  return (
    <div data-testid="staff-management-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: theme.text }}>Staff Management</h1>
          <p className="text-gray-500 mt-1">{staff.length} team members</p>
        </div>
        {user?.role === 'owner' && (
          <Button onClick={() => setShowAdd(true)} style={{ backgroundColor: theme.primary }} data-testid="add-staff-btn">
            <Plus size={18} className="mr-1" /> Add Staff
          </Button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {['staff', ...(user?.role === 'owner' ? ['financials'] : [])].map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${tab === t ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}`}
            data-testid={`tab-${t}`}>
            {t === 'staff' ? 'Team' : 'Financial Reports'}
          </button>
        ))}
      </div>

      {tab === 'staff' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {staff.map(s => (
            <Card key={s.id} className="hover:shadow-md transition-shadow" data-testid={`staff-card-${s.id}`}>
              <CardContent className="p-5">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h3 className="font-semibold">{s.name}</h3>
                    <p className="text-sm text-gray-500">{s.email}</p>
                  </div>
                  <Badge className={ROLE_COLORS[s.role] || 'bg-gray-100 text-gray-600'}>{s.role}</Badge>
                </div>
                {user?.role === 'owner' && s.payRate !== undefined && (
                  <p className="text-sm text-gray-500 mb-3">
                    <DollarSign size={14} className="inline" /> ${s.payRate}{salaryTypeSuffix(s.salaryType)}
                    {' '}&middot; ~${(effectiveHourlyRate(s.payRate, s.salaryType) * 38).toFixed(0)}/week
                  </p>
                )}
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <Badge variant="outline" className={s.status === 'active' ? 'text-green-600' : 'text-gray-400'}>
                    {s.status}
                  </Badge>
                  {user?.role === 'owner' && s.role !== 'owner' && (
                    <Button size="sm" variant="ghost" className="text-red-500" onClick={() => handleDelete(s.id)}
                      data-testid={`delete-${s.id}`}>
                      <Trash2 size={14} />
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {tab === 'financials' && laborReport && (
        <div className="space-y-6" data-testid="financial-reports">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card><CardContent className="p-4 text-center">
              <p className="text-sm text-gray-500">Revenue</p>
              <p className="text-2xl font-bold" style={{ color: theme.primary }}>${laborReport.totalRevenue.toLocaleString()}</p>
            </CardContent></Card>
            <Card><CardContent className="p-4 text-center">
              <p className="text-sm text-gray-500">COGS</p>
              <p className="text-2xl font-bold text-amber-600">${laborReport.cogs.toLocaleString()}</p>
              <p className="text-xs text-gray-400">{laborReport.cogsPct}% of revenue</p>
            </CardContent></Card>
            <Card><CardContent className="p-4 text-center">
              <p className="text-sm text-gray-500">Roster Cost</p>
              <p className="text-2xl font-bold text-blue-600">${laborReport.totalRosterCost.toLocaleString()}</p>
              <p className="text-xs text-gray-400">{laborReport.laborPct}% of revenue</p>
            </CardContent></Card>
            <Card><CardContent className="p-4 text-center">
              <p className="text-sm text-gray-500">Net Profit</p>
              <p className={`text-2xl font-bold ${laborReport.netProfit >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                ${laborReport.netProfit.toLocaleString()}
              </p>
            </CardContent></Card>
          </div>
          <Card><CardContent className="p-5">
            <h3 className="font-semibold mb-3">Staff Pay Breakdown</h3>
            <div className="space-y-2">
              {laborReport.staff.map((s, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b last:border-0">
                  <div><p className="font-medium">{s.name}</p><p className="text-xs text-gray-400">{s.role}</p></div>
                  <div className="text-right"><p className="font-bold">${s.payRate}{salaryTypeSuffix(s.salaryType)}</p><p className="text-xs text-gray-400">~${s.weeklyEstimate}/week</p></div>
                </div>
              ))}
            </div>
          </CardContent></Card>
        </div>
      )}

      {/* Add Staff Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="max-w-sm" data-testid="add-staff-dialog">
          <DialogHeader><DialogTitle>Add Staff Member</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <Input placeholder="Full name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="staff-name" />
            <Input placeholder="Email" type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} data-testid="staff-email" />
            <Input placeholder="Password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} data-testid="staff-password" />
            <select className="w-full p-2 border rounded-md" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} data-testid="staff-role">
              <option value="cashier">Cashier</option>
              <option value="kitchen">Kitchen</option>
              <option value="manager">Manager</option>
            </select>
            <div className="grid grid-cols-2 gap-2">
              <select className="p-2 border rounded-md" value={form.salaryType} onChange={e => setForm({ ...form, salaryType: e.target.value })} data-testid="staff-salary-type">
                <option value="hourly">Hourly</option>
                <option value="weekly">Weekly</option>
                <option value="annually">Annually</option>
              </select>
              <Input type="number" placeholder={`Pay rate ($${salaryTypeSuffix(form.salaryType)})`} value={form.payRate} onChange={e => setForm({ ...form, payRate: parseFloat(e.target.value) || 0 })} data-testid="staff-payrate" />
            </div>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleAddStaff} data-testid="confirm-add-staff">
              Add Staff
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
