import React, { useState, useEffect } from 'react';
import { Palette, MapPin, Users as UsersIcon, Building, GraduationCap, Plus, Edit, Trash2, Save, Receipt, Shield, ShieldCheck, Activity, DownloadCloud, Monitor, Zap, Printer, Globe, Clock, KeyRound, Target, Gift, Utensils, LayoutGrid, Percent, Mail } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { Badge } from '../components/ui/badge';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { locationsAPI, advancedAPI, staffMgmtAPI, enterpriseAPI, gamificationAPI, finalizeAPI, analyticsAPI, customersAPI } from '../services/api';
import SettingsNavigation from '../components/settings/SettingsNavigation';
import WalletCredentialsPanel from '../components/settings/WalletCredentialsPanel';
import PermissionsPanel from '../components/settings/PermissionsPanel';
import CoursingSettings from '../components/settings/CoursingSettings';
import PrinterHealthPanel from '../components/settings/PrinterHealthPanel';
import SecurityPanel from '../components/settings/SecurityPanel';
import OpsHealthPanel from '../components/settings/OpsHealthPanel';
import BackupPanel from '../components/settings/BackupPanel';
import POSLayoutSettings from '../components/settings/POSLayoutSettings';
import { toast } from 'sonner';
import axios from 'axios';
import { salaryTypeSuffix } from '../lib/staffPay';

const API = process.env.REACT_APP_BACKEND_URL;
const authHeader = () => ({ Authorization: `Bearer ${localStorage.getItem('nua_token')}` });

const Settings = () => {
  const { theme, updateTheme, resetTheme, saveThemeToServer, themeSaving, themeSavedAt } = useTheme();
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState('overview');
  const [trainingMode, setTrainingMode] = useState(false);
  const [trainingLoading, setTrainingLoading] = useState(false);
  // Locations
  const [locations, setLocations] = useState([]);
  const [showLocDialog, setShowLocDialog] = useState(false);
  const [editingLoc, setEditingLoc] = useState(null);
  const [locForm, setLocForm] = useState({ name: '', address: '', phone: '', email: '', website: '', logoUrl: '', gmbPlaceId: '', hours: {} });
  // Staff
  const [staff, setStaff] = useState([]);
  const [showStaffDialog, setShowStaffDialog] = useState(false);
  const [editingStaff, setEditingStaff] = useState(null);
  const [staffForm, setStaffForm] = useState({ name: '', email: '', password: '', role: 'cashier', payRate: '', salaryType: 'hourly', pin: '' });
  const [customRoles, setCustomRoles] = useState([]);
  const [newRole, setNewRole] = useState('');
  // Business
  const [bizForm, setBizForm] = useState({ name: 'NUA', abn: '', address: '', phone: '', email: '', taxId: '' });
  // Receipt
  const [receiptSettings, setReceiptSettings] = useState({ logoUrl: '', showPaymentQR: true, showSocialQR: true, showPromoQR: true, socialMediaUrl: '', promoText: '', businessName: 'NUA', businessAddress: '', businessPhone: '' });
  // Permissions
  const [allPerms, setAllPerms] = useState([]);
  const [selectedStaffPerms, setSelectedStaffPerms] = useState(null);
  const [editingPerms, setEditingPerms] = useState([]);
  // Surcharge
  const [surchargeSettings, setSurchargeSettings] = useState({ enabled: false, weekendSurcharge: 0, publicHolidaySurcharge: 0, publicHolidays: [], weekendDays: ['Saturday', 'Sunday'] });
  // Auto-gratuity
  const [gratuitySettings, setGratuitySettings] = useState({ enabled: false, calculateOn: 'post_discount', rates: [] });
  const [newGratuityRate, setNewGratuityRate] = useState({ label: '', percent: '', minCovers: '', maxCovers: '' });
  // Hardware
  const [printers, setPrinters] = useState([]);
  const [scanners, setScanners] = useState([]);
  // Auto reports
  const [reportConfig, setReportConfig] = useState({ enabled: false, frequency: 'daily', time: '23:00', reportTypes: ['detailed'], recipientEmail: '', includeAIInsights: true });
  // Print Routing
  const [printRouting, setPrintRouting] = useState(null);
  const [newRoute, setNewRoute] = useState({ category: '', printer: '', priority: 2 });
  // Business hours
  const [bizHours, setBizHours] = useState({ openTime: '07:00', closeTime: '23:00', onlineOpenTime: '08:00', onlineCloseTime: '22:00', googleBusinessUrl: '', googleSync: false });

  // Today home-screen targets + wallet occasion offers
  const [todayTargets, setTodayTargets] = useState({ dailySalesTarget: 0, laborPctThreshold: 32, refundRateThreshold: 5 });
  const [posSession, setPosSession] = useState({ timeoutMinutes: 0 });
  const [walletOffers, setWalletOffers] = useState({ birthdayEnabled: true, birthdayAmount: 10 });

  useEffect(() => {
    advancedAPI.getTrainingMode().then(r => setTrainingMode(r.data?.enabled || false)).catch(() => {});
    fetchLocations(); fetchStaff(); fetchBusiness();
    staffMgmtAPI.getReceiptSettings().then(r => { if (r.data && Object.keys(r.data).length) setReceiptSettings(r.data); }).catch(() => {});
    enterpriseAPI.getAllPermissions().then(r => setAllPerms(r.data)).catch(() => {});
    enterpriseAPI.getSurchargeSettings().then(r => { if (r.data) setSurchargeSettings(r.data); }).catch(() => {});
    enterpriseAPI.getGratuitySettings().then(r => { if (r.data) setGratuitySettings(r.data); }).catch(() => {});
    enterpriseAPI.getPrinters().then(r => setPrinters(r.data)).catch(() => {});
    enterpriseAPI.getScanners().then(r => setScanners(r.data)).catch(() => {});
    enterpriseAPI.getReportConfig().then(r => { if (r.data) setReportConfig(r.data); }).catch(() => {});
    gamificationAPI.getPrintRouting().then(r => {
      if (!r?.data) return;
      const cfg = { ...r.data };
      // Defensive: legacy dict-shaped routes → array so the Settings pane
      // never crashes with "routes.map is not a function".
      if (cfg.routes && !Array.isArray(cfg.routes)) {
        cfg.routes = Object.entries(cfg.routes).map(([category, printer]) => ({
          category: String(category), printer: String(printer), priority: 2,
        }));
      }
      cfg.routes = Array.isArray(cfg.routes) ? cfg.routes : [];
      setPrintRouting(cfg);
    }).catch(() => setPrintRouting({ enabled: true, routes: [], defaultPrinter: '', defaultPriority: 2 }));
    axios.get(`${API}/api/auth/roles`, { headers: authHeader() }).then(r => setCustomRoles(r.data)).catch(() => {});
    // Load business hours from business settings
    axios.get(`${API}/api/business/settings`, { headers: authHeader() }).then(r => {
      if (r.data?.hours) setBizHours(prev => ({ ...prev, ...r.data.hours }));
    }).catch(() => {});
    analyticsAPI.getTodayTargets().then(r => { if (r.data) setTodayTargets(r.data); }).catch(() => {});
    customersAPI.getWalletOffers().then(r => { if (r.data) setWalletOffers(r.data); }).catch(() => {});
    staffMgmtAPI.getPosSessionSettings().then(r => { if (r.data) setPosSession(r.data); }).catch(() => {});
  }, []);

  const fetchLocations = async () => {
    try { const r = await locationsAPI.getAll(); setLocations(r.data); } catch {}
  };
  const fetchStaff = async () => {
    try { const r = await axios.get(`${API}/api/auth/staff`, { headers: authHeader() }); setStaff(r.data); } catch {}
  };
  const fetchBusiness = async () => {
    try {
      const r = await axios.get(`${API}/api/business/settings`, { headers: authHeader() });
      if (r.data) setBizForm(prev => ({ ...prev, ...r.data }));
    } catch {}
  };

  // Location CRUD
  const openAddLoc = () => { setEditingLoc(null); setLocForm({ name: '', address: '', phone: '', email: '', website: '', logoUrl: '', gmbPlaceId: '', hours: {} }); setShowLocDialog(true); };
  const openEditLoc = (loc) => { setEditingLoc(loc); setLocForm({ name: loc.name, address: loc.address, phone: loc.phone, email: loc.email || '', website: loc.website || '', logoUrl: loc.logoUrl || '', gmbPlaceId: loc.gmbPlaceId || '', hours: loc.hours || {} }); setShowLocDialog(true); };
  const saveLoc = async () => {
    try {
      if (editingLoc) { await locationsAPI.update(editingLoc.id, locForm); toast.success('Location updated'); }
      else { await locationsAPI.create(locForm); toast.success('Location created'); }
      setShowLocDialog(false); fetchLocations();
    } catch (e) { toast.error('Failed to save location'); }
  };
  const deleteLoc = async (id) => {
    if (!window.confirm('Delete this location?')) return;
    try { await locationsAPI.delete(id); toast.success('Location deleted'); fetchLocations(); } catch { toast.error('Failed to delete'); }
  };

  // Staff CRUD
  const openAddStaff = () => { setEditingStaff(null); setStaffForm({ name: '', email: '', password: '', role: 'cashier', payRate: '', salaryType: 'hourly', pin: '' }); setShowStaffDialog(true); };
  const openEditStaff = (s) => { setEditingStaff(s); setStaffForm({ name: s.name, email: s.email, password: '', role: s.role, payRate: s.payRate || '', salaryType: s.salaryType || 'hourly', pin: s.pin || '' }); setShowStaffDialog(true); };
  const saveStaff = async () => {
    if (!staffForm.name) { toast.error('Name is required'); return; }
    try {
      if (editingStaff) {
        const data = { name: staffForm.name, role: staffForm.role, payRate: parseFloat(staffForm.payRate) || 0, salaryType: staffForm.salaryType, pin: staffForm.pin };
        await axios.put(`${API}/api/auth/staff/${editingStaff.id}`, data, { headers: authHeader() });
        toast.success('Staff updated');
      } else {
        await axios.post(`${API}/api/auth/staff/add`, {
          name: staffForm.name, email: staffForm.email || '', password: staffForm.password || '',
          role: staffForm.role, payRate: parseFloat(staffForm.payRate) || 0,
          salaryType: staffForm.salaryType, pin: staffForm.pin,
        }, { headers: authHeader() });
        toast.success('Staff member added');
      }
      setShowStaffDialog(false); fetchStaff();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save staff'); }
  };
  const deleteStaff = async (id) => {
    if (!window.confirm('Delete this staff member?')) return;
    try { await axios.delete(`${API}/api/auth/staff/${id}`, { headers: authHeader() }); toast.success('Staff deleted'); fetchStaff(); } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  // Business save
  const saveBusiness = async () => {
    try {
      await axios.post(`${API}/api/business/settings`, bizForm, { headers: authHeader() });
      toast.success('Business settings saved');
    } catch { toast.error('Failed to save'); }
  };

  return (
    <div className="space-y-6 min-w-0" data-testid="settings-page">
      <div><h1 className="text-3xl font-bold" style={{ color: theme.text }}>Settings</h1><p className="text-gray-500 mt-1">Your venue, team and POS preferences, organised in one place</p></div>

      <SettingsNavigation activeTab={activeTab} onSelect={setActiveTab} role={user?.role}>
      {/* Permissions */}
      {activeTab === 'permissions' && user?.role === 'owner' && (
        <PermissionsPanel staff={staff} />
      )}

      {/* Surcharges */}
      {activeTab === 'surcharge' && user?.role === 'owner' && (
        <Card><CardHeader><CardTitle>Auto Surcharging</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-gray-500">Automatically apply surcharges on weekends and public holidays.</p>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={surchargeSettings.enabled} onChange={e => setSurchargeSettings({ ...surchargeSettings, enabled: e.target.checked })} data-testid="surcharge-enabled" />
            Enable Auto Surcharging
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><label className="text-sm font-medium mb-1 block">Weekend Surcharge %</label><Input type="number" step="0.5" value={surchargeSettings.weekendSurcharge} onChange={e => setSurchargeSettings({ ...surchargeSettings, weekendSurcharge: parseFloat(e.target.value) || 0 })} data-testid="weekend-surcharge" /></div>
            <div><label className="text-sm font-medium mb-1 block">Public Holiday Surcharge %</label><Input type="number" step="0.5" value={surchargeSettings.publicHolidaySurcharge} onChange={e => setSurchargeSettings({ ...surchargeSettings, publicHolidaySurcharge: parseFloat(e.target.value) || 0 })} data-testid="holiday-surcharge" /></div>
          </div>
          <div><label className="text-sm font-medium mb-1 block">Weekend Days</label>
            <div className="flex flex-wrap gap-1.5">
              {['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map(d => (
                <button key={d} type="button" onClick={() => {
                  const days = surchargeSettings.weekendDays.includes(d) ? surchargeSettings.weekendDays.filter(x => x !== d) : [...surchargeSettings.weekendDays, d];
                  setSurchargeSettings({ ...surchargeSettings, weekendDays: days });
                }} className={`px-2.5 py-1 text-xs rounded-full font-medium ${surchargeSettings.weekendDays.includes(d) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}`}>{d.slice(0,3)}</button>
              ))}
            </div>
          </div>
          <div><label className="text-sm font-medium mb-1 block">Public Holidays (YYYY-MM-DD, comma separated)</label>
            <Input placeholder="2026-01-01, 2026-01-26, 2026-04-25" value={(surchargeSettings.publicHolidays || []).join(', ')} onChange={e => setSurchargeSettings({ ...surchargeSettings, publicHolidays: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })} data-testid="public-holidays" />
          </div>
          <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
            try { await enterpriseAPI.saveSurchargeSettings(surchargeSettings); toast.success('Surcharge settings saved'); } catch { toast.error('Failed'); }
          }} data-testid="save-surcharge-btn"><Save size={16} className="mr-1" /> Save Surcharge Settings</Button>
        </CardContent></Card>
      )}

      {/* Auto-Gratuity */}
      {activeTab === 'gratuity' && user?.role === 'owner' && (
        <Card><CardHeader><CardTitle>Auto-Gratuity</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-gray-500">Automatically add a service charge at checkout — different rates can apply by party size (e.g. 18% for tables of 6+).</p>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={gratuitySettings.enabled} onChange={e => setGratuitySettings({ ...gratuitySettings, enabled: e.target.checked })} data-testid="gratuity-enabled" />
            Enable Auto-Gratuity
          </label>
          <div>
            <label className="text-sm font-medium mb-1 block">Calculate on</label>
            <div className="flex gap-3">
              <label className="flex items-center gap-1.5 text-sm">
                <input type="radio" name="gratuity-calc-on" checked={gratuitySettings.calculateOn === 'pre_discount'}
                  onChange={() => setGratuitySettings({ ...gratuitySettings, calculateOn: 'pre_discount' })} data-testid="gratuity-pre-discount" />
                Pre-discount subtotal
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="radio" name="gratuity-calc-on" checked={gratuitySettings.calculateOn !== 'pre_discount'}
                  onChange={() => setGratuitySettings({ ...gratuitySettings, calculateOn: 'post_discount' })} data-testid="gratuity-post-discount" />
                Discounted total
              </label>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium mb-1 block">Rates</label>
            <div className="space-y-1.5">
              {(gratuitySettings.rates || []).map((r, i) => (
                <div key={i} className="flex items-center gap-2 text-sm bg-gray-50 rounded px-3 py-2" data-testid={`gratuity-rate-${i}`}>
                  <span className="flex-1">{r.label || 'Rate'}</span>
                  <Badge variant="outline">{r.percent}%</Badge>
                  <span className="text-xs text-gray-500">
                    {r.minCovers || r.maxCovers ? `covers ${r.minCovers ?? '0'}–${r.maxCovers ?? '∞'}` : 'default (any party size)'}
                  </span>
                  <button className="text-red-400 text-xs" onClick={() => setGratuitySettings({ ...gratuitySettings, rates: gratuitySettings.rates.filter((_, j) => j !== i) })}>&times;</button>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-5 gap-2 mt-2">
              <Input placeholder="Label" className="col-span-2" value={newGratuityRate.label} onChange={e => setNewGratuityRate({ ...newGratuityRate, label: e.target.value })} data-testid="new-gratuity-label" />
              <Input type="number" step="0.5" placeholder="%" value={newGratuityRate.percent} onChange={e => setNewGratuityRate({ ...newGratuityRate, percent: e.target.value })} data-testid="new-gratuity-percent" />
              <Input type="number" placeholder="Min covers" value={newGratuityRate.minCovers} onChange={e => setNewGratuityRate({ ...newGratuityRate, minCovers: e.target.value })} data-testid="new-gratuity-min-covers" />
              <Input type="number" placeholder="Max covers" value={newGratuityRate.maxCovers} onChange={e => setNewGratuityRate({ ...newGratuityRate, maxCovers: e.target.value })} data-testid="new-gratuity-max-covers" />
            </div>
            <Button size="sm" variant="outline" className="mt-2" onClick={() => {
              if (!newGratuityRate.label || !newGratuityRate.percent) return;
              setGratuitySettings({
                ...gratuitySettings,
                rates: [...(gratuitySettings.rates || []), {
                  id: `GRAT-${Date.now()}`,
                  label: newGratuityRate.label,
                  percent: parseFloat(newGratuityRate.percent) || 0,
                  minCovers: newGratuityRate.minCovers ? parseInt(newGratuityRate.minCovers, 10) : null,
                  maxCovers: newGratuityRate.maxCovers ? parseInt(newGratuityRate.maxCovers, 10) : null,
                }],
              });
              setNewGratuityRate({ label: '', percent: '', minCovers: '', maxCovers: '' });
            }} data-testid="add-gratuity-rate-btn"><Plus size={14} className="mr-1" /> Add Rate</Button>
            <p className="text-[11px] text-gray-400 mt-1">Leave covers blank on one rate to use it as the default for parties that don't match a sized rule. The most specific covers range wins.</p>
          </div>
          <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
            try { await enterpriseAPI.saveGratuitySettings(gratuitySettings); toast.success('Gratuity settings saved'); } catch { toast.error('Failed'); }
          }} data-testid="save-gratuity-btn"><Save size={16} className="mr-1" /> Save Gratuity Settings</Button>
        </CardContent></Card>
      )}

      {/* Automated Reports — backend (GET/POST /reports/automated-config) has
          existed for a while but this page only ever read the config into
          state on load, with no form and no way to actually save a change. */}
      {activeTab === 'reports' && user?.role === 'owner' && (
        <Card><CardHeader><CardTitle>Automated Reports</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-gray-500">Email a sales report automatically on a schedule.</p>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={reportConfig.enabled} onChange={e => setReportConfig({ ...reportConfig, enabled: e.target.checked })} data-testid="report-enabled" />
            Enable Automated Reports
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><label className="text-sm font-medium mb-1 block">Frequency</label>
              <select className="w-full border rounded-md px-3 py-2 text-sm" value={reportConfig.frequency}
                onChange={e => setReportConfig({ ...reportConfig, frequency: e.target.value })} data-testid="report-frequency">
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
            <div><label className="text-sm font-medium mb-1 block">Send Time</label>
              <Input type="time" value={reportConfig.time} onChange={e => setReportConfig({ ...reportConfig, time: e.target.value })} data-testid="report-time" />
            </div>
          </div>
          <div><label className="text-sm font-medium mb-1 block">Recipient Email</label>
            <Input type="email" placeholder="owner@yourrestaurant.com" value={reportConfig.recipientEmail}
              onChange={e => setReportConfig({ ...reportConfig, recipientEmail: e.target.value })} data-testid="report-recipient" />
          </div>
          <div><label className="text-sm font-medium mb-1 block">Report Types</label>
            <div className="flex flex-wrap gap-1.5">
              {['itemised', 'category', 'detailed'].map(t => (
                <button key={t} type="button" onClick={() => {
                  const types = reportConfig.reportTypes.includes(t)
                    ? reportConfig.reportTypes.filter(x => x !== t) : [...reportConfig.reportTypes, t];
                  setReportConfig({ ...reportConfig, reportTypes: types });
                }} className={`px-2.5 py-1 text-xs rounded-full font-medium capitalize ${reportConfig.reportTypes.includes(t) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}`}>{t}</button>
              ))}
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={reportConfig.includeAIInsights} onChange={e => setReportConfig({ ...reportConfig, includeAIInsights: e.target.checked })} data-testid="report-ai-insights" />
            Include NUA AI Insights
          </label>
          <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
            try { await enterpriseAPI.saveReportConfig(reportConfig); toast.success('Report settings saved'); } catch { toast.error('Failed to save report settings'); }
          }} data-testid="save-report-config-btn"><Save size={16} className="mr-1" /> Save Report Settings</Button>
        </CardContent></Card>
      )}

      {/* Today home screen targets + wallet occasion offers */}
      {activeTab === 'targets' && (user?.role === 'owner' || user?.role === 'manager') && (
        <div className="space-y-4">
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><Target size={18} /> Today Home Screen Targets</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-gray-500">Drives the progress bar and exception alerts on the Today home screen.</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div><label className="text-sm font-medium mb-1 block">Daily Sales Target ($)</label>
                <Input type="number" min="0" step="50" value={todayTargets.dailySalesTarget}
                  onChange={e => setTodayTargets({ ...todayTargets, dailySalesTarget: parseFloat(e.target.value) || 0 })}
                  placeholder="0 = no target shown" data-testid="today-sales-target" /></div>
              <div><label className="text-sm font-medium mb-1 block">Labor % Alert Threshold</label>
                <Input type="number" min="1" step="1" value={todayTargets.laborPctThreshold}
                  onChange={e => setTodayTargets({ ...todayTargets, laborPctThreshold: parseFloat(e.target.value) || 32 })}
                  data-testid="today-labor-threshold" /></div>
              <div><label className="text-sm font-medium mb-1 block">Refund Rate Alert %</label>
                <Input type="number" min="0" step="0.5" value={todayTargets.refundRateThreshold}
                  onChange={e => setTodayTargets({ ...todayTargets, refundRateThreshold: parseFloat(e.target.value) || 0 })}
                  data-testid="today-refund-threshold" /></div>
            </div>
            <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
              try { await analyticsAPI.saveTodayTargets(todayTargets); toast.success('Today targets saved'); }
              catch { toast.error('Failed to save'); }
            }} data-testid="save-today-targets-btn"><Save size={16} className="mr-1" /> Save Targets</Button>
          </CardContent></Card>

          <Card><CardHeader><CardTitle className="flex items-center gap-2"><Gift size={18} /> Wallet Occasion Offers</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-gray-500">
              Auto-issued straight to a customer's wallet — no manual codes. Birthday-month
              vouchers are issued once per customer per year, the first time their wallet is opened
              or the loyalty agent runs during their birthday month.
            </p>
            <label className="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" checked={walletOffers.birthdayEnabled}
                onChange={e => setWalletOffers({ ...walletOffers, birthdayEnabled: e.target.checked })}
                data-testid="birthday-offer-enabled" />
              Enable Birthday Month offer
            </label>
            <div className="w-48"><label className="text-sm font-medium mb-1 block">Voucher Amount ($)</label>
              <Input type="number" min="0" step="1" value={walletOffers.birthdayAmount}
                disabled={!walletOffers.birthdayEnabled}
                onChange={e => setWalletOffers({ ...walletOffers, birthdayAmount: parseFloat(e.target.value) || 0 })}
                data-testid="birthday-offer-amount" /></div>
            <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
              try { await customersAPI.saveWalletOffers(walletOffers); toast.success('Wallet offers saved'); }
              catch { toast.error('Failed to save'); }
            }} data-testid="save-wallet-offers-btn"><Save size={16} className="mr-1" /> Save Offers</Button>
          </CardContent></Card>

        </div>
      )}

      {activeTab === 'session' && (user?.role === 'owner' || user?.role === 'manager') && (
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><Clock size={18} /> POS Session</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-gray-500">
              How long a POS screen stays signed in after a PIN login or after finishing an order,
              before it auto-logs-out and waits for the next PIN. Any interaction resets the clock —
              this only fires on real inactivity.
            </p>
            <div className="flex flex-wrap gap-2">
              {[{ v: 0, label: 'Stay logged in' }, { v: 2, label: '2 min' }, { v: 5, label: '5 min' }, { v: 10, label: '10 min' }].map(opt => (
                <button key={opt.v} onClick={() => setPosSession({ timeoutMinutes: opt.v })}
                  data-testid={`pos-session-${opt.v}`}
                  className={`px-4 py-2 text-sm rounded-lg font-medium border transition-colors ${posSession.timeoutMinutes === opt.v ? 'text-white border-transparent' : 'text-gray-600 border-gray-200 hover:border-gray-300'}`}
                  style={posSession.timeoutMinutes === opt.v ? { backgroundColor: theme.primary } : {}}>
                  {opt.label}
                </button>
              ))}
            </div>
            <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
              try { await staffMgmtAPI.savePosSessionSettings(posSession); toast.success('POS session setting saved'); }
              catch { toast.error('Failed to save'); }
            }} data-testid="save-pos-session-btn"><Save size={16} className="mr-1" /> Save</Button>
          </CardContent></Card>
      )}

      {/* Hardware */}
      {activeTab === 'hardware' && (
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Printer Configuration</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {printers.map(p => (
              <div key={p.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div><p className="font-medium text-sm">{p.name}</p><p className="text-xs text-gray-500">{p.type} — {p.connectionType} {p.ipAddress ? `(${p.ipAddress})` : ''}</p></div>
                <Button variant="ghost" size="sm" className="text-red-500" onClick={async () => { await enterpriseAPI.deletePrinter(p.id); const r = await enterpriseAPI.getPrinters(); setPrinters(r.data); }}><Trash2 size={14} /></Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={async () => {
              const name = prompt('Printer name:');
              if (!name) return;
              const type = prompt('Type (receipt/kitchen/label):') || 'receipt';
              const conn = prompt('Connection (usb/network/bluetooth):') || 'network';
              const ip = conn === 'network' ? prompt('IP Address:') || '' : '';
              await enterpriseAPI.addPrinter({ name, type, connectionType: conn, ipAddress: ip });
              const r = await enterpriseAPI.getPrinters(); setPrinters(r.data);
              toast.success('Printer added');
            }} data-testid="add-printer-btn"><Plus size={14} className="mr-1" /> Add Printer</Button>
          </CardContent></Card>

          <Card><CardHeader><CardTitle>Scanner Configuration</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {scanners.map(s => (
              <div key={s.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div><p className="font-medium text-sm">{s.name}</p><p className="text-xs text-gray-500">{s.type} — {s.connectionType}</p></div>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={async () => {
              const name = prompt('Scanner name:');
              if (!name) return;
              const type = prompt('Type (barcode/qr):') || 'barcode';
              await enterpriseAPI.addScanner({ name, type, connectionType: 'usb' });
              const r = await enterpriseAPI.getScanners(); setScanners(r.data);
              toast.success('Scanner added');
            }} data-testid="add-scanner-btn"><Plus size={14} className="mr-1" /> Add Scanner</Button>
          </CardContent></Card>
        </div>
      )}


      {/* Training Mode */}
      {activeTab === 'training' && (
        <Card><CardHeader><CardTitle>Training Mode</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-gray-500">When enabled, POS transactions are simulated — no real charges are processed.</p>
          <div className="flex items-center justify-between p-4 rounded-lg border">
            <div>
              <p className="font-semibold">{trainingMode ? 'Training Mode is ON' : 'Training Mode is OFF'}</p>
              <p className="text-sm text-gray-500">{trainingMode ? 'All POS transactions are simulated' : 'POS is processing real transactions'}</p>
            </div>
            <Button data-testid="toggle-training-mode" disabled={trainingLoading} onClick={async () => {
              setTrainingLoading(true);
              try { const r = await advancedAPI.setTrainingMode(!trainingMode); setTrainingMode(r.data.enabled); toast.success(r.data.message); } catch { toast.error('Failed'); }
              setTrainingLoading(false);
            }} style={{ backgroundColor: trainingMode ? '#ef4444' : theme.primary }} className="text-white">
              {trainingMode ? 'Disable' : 'Enable'}
            </Button>
          </div>
        </CardContent></Card>
      )}

      {/* Receipt Settings */}
      {activeTab === 'receipt' && (
        <Card><CardHeader><CardTitle>Receipt Customization</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-gray-500">Configure what appears on printed receipts.</p>
          <div><label className="text-sm font-medium mb-1 block">Business Logo URL</label><Input placeholder="https://..." value={receiptSettings.logoUrl} onChange={e => setReceiptSettings({ ...receiptSettings, logoUrl: e.target.value })} data-testid="receipt-logo-url" /></div>
          <div><label className="text-sm font-medium mb-1 block">Business Name on Receipt</label><Input value={receiptSettings.businessName} onChange={e => setReceiptSettings({ ...receiptSettings, businessName: e.target.value })} /></div>
          <div><label className="text-sm font-medium mb-1 block">Business Address</label><Input value={receiptSettings.businessAddress} onChange={e => setReceiptSettings({ ...receiptSettings, businessAddress: e.target.value })} /></div>
          <div><label className="text-sm font-medium mb-1 block">Business Phone</label><Input value={receiptSettings.businessPhone} onChange={e => setReceiptSettings({ ...receiptSettings, businessPhone: e.target.value })} /></div>
          <hr />
          <h4 className="font-semibold text-sm">QR Codes on Receipt</h4>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={receiptSettings.showPaymentQR} onChange={e => setReceiptSettings({ ...receiptSettings, showPaymentQR: e.target.checked })} data-testid="receipt-payment-qr" /> Show Payment QR Code</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={receiptSettings.showSocialQR} onChange={e => setReceiptSettings({ ...receiptSettings, showSocialQR: e.target.checked })} data-testid="receipt-social-qr" /> Show Social Media QR Code</label>
          {receiptSettings.showSocialQR && <Input placeholder="Social media URL (for QR)" value={receiptSettings.socialMediaUrl} onChange={e => setReceiptSettings({ ...receiptSettings, socialMediaUrl: e.target.value })} data-testid="receipt-social-url" />}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={receiptSettings.showPromoQR} onChange={e => setReceiptSettings({ ...receiptSettings, showPromoQR: e.target.checked })} data-testid="receipt-promo-qr" /> Show Promotion QR Code</label>
          {receiptSettings.showPromoQR && <Input placeholder="Promotion text or URL" value={receiptSettings.promoText} onChange={e => setReceiptSettings({ ...receiptSettings, promoText: e.target.value })} data-testid="receipt-promo-text" />}
          <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
            try { await staffMgmtAPI.saveReceiptSettings(receiptSettings); toast.success('Receipt settings saved'); } catch { toast.error('Failed'); }
          }} data-testid="save-receipt-btn"><Save size={16} className="mr-1" /> Save Receipt Settings</Button>
        </CardContent></Card>
      )}


      {/* Theme */}
      {activeTab === 'theme' && (
        <Card><CardHeader><CardTitle>Color Customization</CardTitle></CardHeader>
        <CardContent className="space-y-6">
          <p className="text-sm text-gray-500 -mt-2">
            Changes preview instantly on this screen. Click <strong>Save</strong> to push the brand
            colors to every terminal — until then, they only apply to this browser.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {[{ key: 'primary', label: 'Primary Color' }, { key: 'secondary', label: 'Secondary Color' }, { key: 'accent', label: 'Accent Color' }, { key: 'sidebar', label: 'Sidebar Background' }, { key: 'background', label: 'POS Background Color' }].map(c => (
              <div key={c.key} className="space-y-2">
                <label className="font-medium text-sm">{c.label}</label>
                <div className="flex items-center gap-3">
                  <input type="color" value={theme[c.key]} onChange={e => updateTheme({ [c.key]: e.target.value })} className="w-20 h-10 rounded border cursor-pointer" data-testid={`theme-color-${c.key}`} />
                  <Input value={theme[c.key]} onChange={e => updateTheme({ [c.key]: e.target.value })} className="flex-1 font-mono text-sm" data-testid={`theme-color-input-${c.key}`} />
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <Button style={{ backgroundColor: theme.primary }} disabled={themeSaving}
              onClick={async () => {
                try { await saveThemeToServer(); toast.success('Saved — every terminal will pick this up'); }
                catch { toast.error('Failed to save theme'); }
              }} data-testid="save-theme-btn">
              <Save size={16} className="mr-1" /> {themeSaving ? 'Saving…' : 'Save to all terminals'}
            </Button>
            <Button variant="outline" onClick={resetTheme} data-testid="reset-theme-btn">Reset to Default</Button>
            {themeSavedAt && <span className="text-xs text-gray-400">Saved {new Date(themeSavedAt).toLocaleTimeString()}</span>}
          </div>
        </CardContent></Card>
      )}

      {/* Locations */}
      {activeTab === 'locations' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-bold">Store Locations</h2>
            <Button style={{ backgroundColor: theme.primary }} onClick={openAddLoc} data-testid="add-location-btn"><Plus size={16} className="mr-1" /> Add Location</Button>
          </div>
          {locations.map(loc => (
            <Card key={loc.id} data-testid={`location-card-${loc.id}`}><CardContent className="p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  {loc.logoUrl && (
                    <img src={loc.logoUrl} alt="" className="w-14 h-14 rounded-lg border object-contain bg-white flex-shrink-0" onError={(e) => { e.target.style.display = 'none'; }} data-testid={`loc-logo-${loc.id}`} />
                  )}
                  <div className="min-w-0">
                    <h3 className="text-lg font-bold" style={{ color: theme.text }}>{loc.name}</h3>
                    <p className="text-sm text-gray-600">{loc.address}</p>
                    <p className="text-sm text-gray-600">{loc.phone}{loc.email ? ` · ${loc.email}` : ''}</p>
                    {loc.website && (
                      <a href={loc.website} target="_blank" rel="noreferrer" className="text-sm text-blue-600 hover:underline">{loc.website}</a>
                    )}
                    <div className="flex flex-wrap gap-2 mt-2">
                      <Badge className={`${loc.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>{(loc.status || 'active').toUpperCase()}</Badge>
                      {loc.gmbPlaceId && (
                        <Badge className="bg-blue-100 text-blue-800" data-testid={`loc-gmb-badge-${loc.id}`}>
                          GMB · {loc.gmbLastSyncAt ? `synced ${new Date(loc.gmbLastSyncAt).toLocaleDateString()}` : 'not synced'}
                        </Badge>
                      )}
                      {loc.hours && Object.keys(loc.hours).length > 0 && (
                        <Badge className="bg-gray-100 text-gray-700">Hours set</Badge>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  {loc.gmbPlaceId && (
                    <Button variant="outline" size="sm" onClick={async () => {
                      try { await finalizeAPI.gmbSync(loc.id); toast.success('GMB sync queued'); fetchLocations(); }
                      catch (e) { toast.error(e?.response?.data?.detail || 'Sync failed'); }
                    }} data-testid={`gmb-sync-${loc.id}`}>Sync GMB</Button>
                  )}
                  <Button variant="outline" size="sm" onClick={() => openEditLoc(loc)} data-testid={`edit-loc-${loc.id}`}><Edit size={14} /></Button>
                  <Button variant="outline" size="sm" className="text-red-500" onClick={() => deleteLoc(loc.id)} data-testid={`delete-loc-${loc.id}`}><Trash2 size={14} /></Button>
                </div>
              </div>
            </CardContent></Card>
          ))}
          {locations.length === 0 && <Card className="border-dashed"><CardContent className="p-12 text-center"><MapPin size={40} className="mx-auto mb-3 text-gray-300" /><p className="text-gray-500">No locations yet. Add your first location.</p></CardContent></Card>}
        </div>
      )}

      {/* Staff */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-bold">Team Members</h2>
            {user?.role === 'owner' && <Button style={{ backgroundColor: theme.primary }} onClick={openAddStaff} data-testid="add-staff-btn"><Plus size={16} className="mr-1" /> Add Staff</Button>}
          </div>
          <Card><CardContent className="p-0"><div className="overflow-x-auto"><table className="w-full" data-testid="staff-table">
            <thead className="bg-gray-50"><tr>
              <th className="text-left p-4 text-sm font-medium text-gray-500">Name</th>
              <th className="text-left p-4 text-sm font-medium text-gray-500">Email</th>
              <th className="text-left p-4 text-sm font-medium text-gray-500">Role</th>
              {user?.role === 'owner' && <th className="text-center p-4 text-sm font-medium text-gray-500">PIN</th>}
              <th className="text-center p-4 text-sm font-medium text-gray-500">Status</th>
              {user?.role === 'owner' && <th className="text-right p-4 text-sm font-medium text-gray-500">Pay Rate</th>}
              {user?.role === 'owner' && <th className="text-center p-4 text-sm font-medium text-gray-500">Actions</th>}
            </tr></thead>
            <tbody>
              {staff.map(s => (
                <tr key={s.id} className="border-t hover:bg-gray-50" data-testid={`staff-row-${s.id}`}>
                  <td className="p-4 font-medium">{s.name}</td>
                  <td className="p-4 text-sm text-gray-600">{s.email}</td>
                  <td className="p-4"><Badge variant="outline" className="capitalize">{s.role}</Badge></td>
                  {user?.role === 'owner' && <td className="p-4 text-center">
                    {s.pin ? <span className="font-mono text-sm bg-gray-100 px-2 py-0.5 rounded">{s.pin}</span> : (
                      <Button variant="ghost" size="sm" className="text-xs" onClick={async () => {
                        const pin = prompt('Set 2-4 digit PIN for ' + s.name + ':');
                        if (pin && /^\d{2,4}$/.test(pin)) {
                          try { await staffMgmtAPI.setPin(s.id, pin); toast.success('PIN set'); fetchStaff(); } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
                        } else if (pin) toast.error('PIN must be 2-4 digits');
                      }} data-testid={`set-pin-${s.id}`}>Set PIN</Button>
                    )}
                  </td>}
                  <td className="p-4 text-center">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${s.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                      {(s.status || 'active').toUpperCase()}
                    </span>
                  </td>
                  {user?.role === 'owner' && <td className="p-4 text-right font-mono text-sm">${s.payRate || 0}<span className="text-gray-400 text-[10px] ml-0.5">{salaryTypeSuffix(s.salaryType)}</span></td>}
                  {user?.role === 'owner' && <td className="p-4 text-center">
                    <div className="flex justify-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => openEditStaff(s)} data-testid={`edit-staff-${s.id}`}><Edit size={14} /></Button>
                      <Button variant="outline" size="sm" className="text-red-500" onClick={() => deleteStaff(s.id)} data-testid={`delete-staff-${s.id}`}><Trash2 size={14} /></Button>
                    </div>
                  </td>}
                </tr>
              ))}
            </tbody>
          </table></div></CardContent></Card>

          {/* Custom Roles */}
          {user?.role === 'owner' && (
            <Card><CardContent className="p-4">
              <h3 className="font-semibold text-sm mb-3">Custom Roles</h3>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {customRoles.map(r => (
                  <span key={r} className="inline-flex items-center gap-1 px-2.5 py-1 bg-gray-100 rounded-full text-xs font-medium capitalize">
                    {r}
                    <button onClick={() => { const updated = customRoles.filter(x => x !== r); setCustomRoles(updated); axios.post(`${API}/api/auth/roles`, { roles: updated }, { headers: authHeader() }).then(() => toast.success('Role removed')); }} className="text-gray-400 hover:text-red-500 ml-0.5">&times;</button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <Input placeholder="New role name" className="h-8 text-sm" value={newRole} onChange={e => setNewRole(e.target.value)} data-testid="new-role-input" />
                <Button size="sm" variant="outline" className="h-8" onClick={() => {
                  if (!newRole.trim()) return;
                  const role = newRole.trim().toLowerCase();
                  if (customRoles.includes(role)) { toast.error('Role exists'); return; }
                  const updated = [...customRoles, role];
                  setCustomRoles(updated); setNewRole('');
                  axios.post(`${API}/api/auth/roles`, { roles: updated }, { headers: authHeader() }).then(() => toast.success('Role added'));
                }} data-testid="add-role-btn"><Plus size={14} /></Button>
              </div>
            </CardContent></Card>
          )}
        </div>
      )}

      {/* Courses & Firing */}
      {activeTab === 'coursing' && (
        <CoursingSettings
          theme={theme}
          canEdit={['owner', 'manager'].includes(user?.role)}
        />
      )}

      {/* Business Info */}
      {/* Print Routing */}
      {activeTab === 'print-routing' && printRouting && (
        <Card><CardHeader><CardTitle>Category Print Routing</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-gray-500">Route order items to Kitchen, Bar, or Pizza printers by category.</p>
          {(printRouting.routes || []).map((r, i) => (
            <div key={i} className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg">
              <Badge variant="outline" className="text-xs">{r.category}</Badge>
              <span className="text-gray-400">→</span>
              <span className="text-sm font-medium flex-1">{r.printer}</span>
              <Badge className={`text-[10px] ${r.priority === 1 ? 'bg-red-100 text-red-700' : r.priority === 2 ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'}`}>P{r.priority}</Badge>
              <Button variant="ghost" size="sm" className="text-red-500 h-7 w-7 p-0" onClick={() => {
                const routes = [...printRouting.routes]; routes.splice(i, 1); setPrintRouting({ ...printRouting, routes });
              }}><Trash2 size={12} /></Button>
            </div>
          ))}
          <div className="flex gap-2 pt-2 border-t">
            <Input placeholder="Category" className="flex-1 h-8 text-sm" value={newRoute.category} onChange={e => setNewRoute({ ...newRoute, category: e.target.value })} data-testid="new-pr-category" />
            <Input placeholder="Printer" className="flex-1 h-8 text-sm" value={newRoute.printer} onChange={e => setNewRoute({ ...newRoute, printer: e.target.value })} data-testid="new-pr-printer" />
            <select className="h-8 text-sm border rounded px-2" value={newRoute.priority} onChange={e => setNewRoute({ ...newRoute, priority: parseInt(e.target.value) })}>
              <option value={1}>P1</option><option value={2}>P2</option><option value={3}>P3</option>
            </select>
            <Button size="sm" variant="outline" className="h-8" onClick={() => { if (!newRoute.category || !newRoute.printer) return; setPrintRouting({ ...printRouting, routes: [...(printRouting.routes || []), { ...newRoute }] }); setNewRoute({ category: '', printer: '', priority: 2 }); }} data-testid="add-pr-route-btn"><Plus size={14} /></Button>
          </div>
          <div><label className="text-xs font-medium text-gray-500">Default Printer</label><Input className="h-8 text-sm mt-1" value={printRouting.defaultPrinter || ''} onChange={e => setPrintRouting({ ...printRouting, defaultPrinter: e.target.value })} /></div>
          <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
            try { await gamificationAPI.savePrintRouting(printRouting); toast.success('Print routing saved'); } catch { toast.error('Failed'); }
          }} data-testid="save-pr-btn"><Save size={16} className="mr-1" /> Save Print Routing</Button>
        </CardContent></Card>
      )}

      {/* Sits with print routing because it answers the same question from
          the other side: the routes are right, but is the device actually on? */}
      {activeTab === 'print-routing' && <PrinterHealthPanel />}

      {activeTab === 'security' && <SecurityPanel />}

      {activeTab === 'ops' && <OpsHealthPanel />}

      {activeTab === 'backup' && <BackupPanel />}

      {activeTab === 'pos-layout' && <POSLayoutSettings />}

      {activeTab === 'wallet' && (
        <WalletCredentialsPanel theme={theme} />
      )}


      {activeTab === 'business' && (
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Business Information</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div><label className="text-sm font-medium mb-1 block">Business Name</label><Input value={bizForm.name} onChange={e => setBizForm({ ...bizForm, name: e.target.value })} data-testid="biz-name" /></div>
            <div><label className="text-sm font-medium mb-1 block">ABN</label><Input placeholder="12 345 678 901" value={bizForm.abn} onChange={e => setBizForm({ ...bizForm, abn: e.target.value })} /></div>
            <div><label className="text-sm font-medium mb-1 block">Business Address</label><Input value={bizForm.address} onChange={e => setBizForm({ ...bizForm, address: e.target.value })} /></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="text-sm font-medium mb-1 block">Phone</label><Input value={bizForm.phone} onChange={e => setBizForm({ ...bizForm, phone: e.target.value })} /></div>
              <div><label className="text-sm font-medium mb-1 block">Email</label><Input value={bizForm.email} onChange={e => setBizForm({ ...bizForm, email: e.target.value })} /></div>
            </div>
            <div><label className="text-sm font-medium mb-1 block">Tax Registration</label><Input value={bizForm.taxId} onChange={e => setBizForm({ ...bizForm, taxId: e.target.value })} /></div>
            <Button style={{ backgroundColor: theme.primary }} onClick={saveBusiness} data-testid="save-biz-btn"><Save size={16} className="mr-1" /> Save Changes</Button>
          </CardContent></Card>

          <Card><CardHeader><CardTitle>Business Hours</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="text-sm font-medium mb-1 block">Opening Time</label><Input type="time" value={bizHours.openTime} onChange={e => setBizHours({ ...bizHours, openTime: e.target.value })} data-testid="biz-open-time" /></div>
              <div><label className="text-sm font-medium mb-1 block">Closing Time</label><Input type="time" value={bizHours.closeTime} onChange={e => setBizHours({ ...bizHours, closeTime: e.target.value })} data-testid="biz-close-time" /></div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="text-sm font-medium mb-1 block">Online Ordering Opens</label><Input type="time" value={bizHours.onlineOpenTime} onChange={e => setBizHours({ ...bizHours, onlineOpenTime: e.target.value })} data-testid="biz-online-open" /></div>
              <div><label className="text-sm font-medium mb-1 block">Online Ordering Closes</label><Input type="time" value={bizHours.onlineCloseTime} onChange={e => setBizHours({ ...bizHours, onlineCloseTime: e.target.value })} data-testid="biz-online-close" /></div>
            </div>
            <hr />
            <h4 className="font-semibold text-sm flex items-center gap-2"><Globe size={16} /> Google Business Sync</h4>
            <div><label className="text-sm font-medium mb-1 block">Google Business Profile URL</label><Input placeholder="https://business.google.com/..." value={bizHours.googleBusinessUrl} onChange={e => setBizHours({ ...bizHours, googleBusinessUrl: e.target.value })} data-testid="google-biz-url" /></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={bizHours.googleSync} onChange={e => setBizHours({ ...bizHours, googleSync: e.target.checked })} data-testid="google-sync" /> Sync hours with Google Business</label>
            <Button style={{ backgroundColor: theme.primary }} onClick={async () => {
              try { await axios.post(`${API}/api/business/settings`, { ...bizForm, hours: bizHours }, { headers: authHeader() }); toast.success('Business hours & Google sync saved'); } catch { toast.error('Failed'); }
            }} data-testid="save-hours-btn"><Save size={16} className="mr-1" /> Save Hours & Sync</Button>
          </CardContent></Card>
        </div>
      )}

      </SettingsNavigation>

      {/* Location Dialog */}
      <Dialog open={showLocDialog} onOpenChange={setShowLocDialog}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="location-dialog">
          <DialogHeader><DialogTitle>{editingLoc ? 'Edit Location' : 'Add Location'}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-2">
              <Input placeholder="Location name" value={locForm.name} onChange={e => setLocForm({ ...locForm, name: e.target.value })} data-testid="loc-name-input" />
              <Input placeholder="Phone" value={locForm.phone} onChange={e => setLocForm({ ...locForm, phone: e.target.value })} data-testid="loc-phone-input" />
            </div>
            <Input placeholder="Address" value={locForm.address} onChange={e => setLocForm({ ...locForm, address: e.target.value })} data-testid="loc-address-input" />
            <div className="grid grid-cols-2 gap-2">
              <Input placeholder="Email" type="email" value={locForm.email} onChange={e => setLocForm({ ...locForm, email: e.target.value })} data-testid="loc-email-input" />
              <Input placeholder="Website URL" value={locForm.website} onChange={e => setLocForm({ ...locForm, website: e.target.value })} data-testid="loc-website-input" />
            </div>
            <Input placeholder="Logo URL (https://…)" value={locForm.logoUrl} onChange={e => setLocForm({ ...locForm, logoUrl: e.target.value })} data-testid="loc-logo-input" />
            {locForm.logoUrl && (
              <img src={locForm.logoUrl} alt="" className="h-12 rounded border object-contain bg-white" onError={(e) => { e.target.style.display = 'none'; }} data-testid="loc-logo-preview" />
            )}
            <Input placeholder="Google My Business Place ID" value={locForm.gmbPlaceId} onChange={e => setLocForm({ ...locForm, gmbPlaceId: e.target.value })} data-testid="loc-gmb-input" />

            <div className="border rounded-lg p-3 bg-gray-50/50">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Opening hours</p>
              <div className="space-y-1.5">
                {['mon','tue','wed','thu','fri','sat','sun'].map(d => {
                  const h = (locForm.hours && locForm.hours[d]) || { open: '09:00', close: '22:00', closed: false };
                  return (
                    <div key={d} className="flex items-center gap-2 text-sm">
                      <span className="w-10 uppercase text-xs font-medium text-gray-500">{d}</span>
                      <Input type="time" value={h.open} onChange={e => setLocForm({ ...locForm, hours: { ...locForm.hours, [d]: { ...h, open: e.target.value } } })} className="w-24 h-8" data-testid={`loc-hours-${d}-open`} disabled={h.closed} />
                      <span className="text-gray-400">–</span>
                      <Input type="time" value={h.close} onChange={e => setLocForm({ ...locForm, hours: { ...locForm.hours, [d]: { ...h, close: e.target.value } } })} className="w-24 h-8" data-testid={`loc-hours-${d}-close`} disabled={h.closed} />
                      <label className="flex items-center gap-1 text-xs text-gray-500 cursor-pointer">
                        <input type="checkbox" checked={!!h.closed} onChange={e => setLocForm({ ...locForm, hours: { ...locForm.hours, [d]: { ...h, closed: e.target.checked } } })} data-testid={`loc-hours-${d}-closed`} />
                        Closed
                      </label>
                    </div>
                  );
                })}
              </div>
            </div>

            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={saveLoc} data-testid="save-loc-btn">{editingLoc ? 'Update' : 'Create'} Location</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Staff Dialog */}
      <Dialog open={showStaffDialog} onOpenChange={setShowStaffDialog}>
        <DialogContent className="max-w-sm" data-testid="staff-dialog">
          <DialogHeader><DialogTitle>{editingStaff ? 'Edit Staff' : 'Add Staff Member'}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2 max-h-[65vh] overflow-y-auto">
            <Input placeholder="Full name *" value={staffForm.name} onChange={e => setStaffForm({ ...staffForm, name: e.target.value })} data-testid="staff-name-input" />
            <Input placeholder="Email (optional)" value={staffForm.email} onChange={e => setStaffForm({ ...staffForm, email: e.target.value })} data-testid="staff-email-input" />
            {!editingStaff && <Input type="password" placeholder="Password (optional — use PIN instead)" value={staffForm.password} onChange={e => setStaffForm({ ...staffForm, password: e.target.value })} data-testid="staff-password-input" />}
            <Input placeholder="PIN code (2-4 digits)" maxLength={4} value={staffForm.pin} onChange={e => setStaffForm({ ...staffForm, pin: e.target.value.replace(/\D/g, '').slice(0, 4) })} data-testid="staff-pin-input" />
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Role</label>
              <div className="flex gap-2">
                <select className="flex-1 p-2 border rounded-md text-sm" value={staffForm.role} onChange={e => setStaffForm({ ...staffForm, role: e.target.value })} data-testid="staff-role-select">
                  <option value="owner">Owner</option>
                  <option value="manager">Manager</option>
                  {customRoles.map(r => <option key={r} value={r} className="capitalize">{r}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Salary Type</label>
                <select className="w-full p-2 border rounded-md text-sm" value={staffForm.salaryType} onChange={e => setStaffForm({ ...staffForm, salaryType: e.target.value })} data-testid="staff-salary-type">
                  <option value="hourly">Hourly</option>
                  <option value="weekly">Weekly</option>
                  <option value="annually">Annually</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Pay Rate ($)</label>
                <Input type="number" step="0.01" placeholder="0.00" value={staffForm.payRate} onChange={e => setStaffForm({ ...staffForm, payRate: e.target.value })} data-testid="staff-payrate-input" />
              </div>
            </div>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={saveStaff} data-testid="save-staff-btn">{editingStaff ? 'Update' : 'Add'} Staff</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Settings;
