import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, Mail, Phone, Award, Star, Calendar, Clock,
  Tag, Heart, AlertCircle, ChevronRight, ArrowLeft, Shield,
  UtensilsCrossed, MessageSquare, Edit2, X, DollarSign, Users, Wallet
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from '../components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '../components/ui/select';
import { useTheme } from '../contexts/ThemeContext';
import { customersAPI, feedbackAPI } from '../services/api';
import { toast } from 'sonner';
import GuestWalletDialog from '../components/customers/GuestWalletDialog';
import CustomerWalletPanel from '../components/customers/CustomerWalletPanel';

const TIER_CONFIG = {
  Platinum: { color: '#818CF8', bg: '#EEF2FF' },
  Gold: { color: '#F59E0B', bg: '#FFFBEB' },
  Silver: { color: '#6B7280', bg: '#F3F4F6' },
  Bronze: { color: '#B45309', bg: '#FEF3C7' },
};

const DIETARY_OPTIONS = ['Gluten-Free', 'Vegan', 'Vegetarian', 'Dairy-Free', 'Nut-Free', 'Halal', 'Kosher', 'Keto', 'Low-Sodium'];
const ALLERGY_OPTIONS = ['Peanuts', 'Tree Nuts', 'Shellfish', 'Fish', 'Eggs', 'Milk', 'Soy', 'Wheat', 'Sesame'];
const TAG_OPTIONS = ['VIP', 'Corporate', 'Influencer', 'Regular', 'Birthday Month', 'High Spender', 'Reviewer', 'Family'];

const emptyCustomerForm = {
  name: '', email: '', phone: '', membershipTier: 'Bronze',
  birthday: '', company: '', seatingPreference: '',
  dietaryRestrictions: [], allergies: [], tags: [], isVip: false, notes: '',
};

const Customers = () => {
  const { theme } = useTheme();
  const [searchTerm, setSearchTerm] = useState('');
  const [customers, setCustomers] = useState([]);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [profile, setProfile] = useState(null);
  const [profileTab, setProfileTab] = useState('overview');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [form, setForm] = useState({ ...emptyCustomerForm });
  const [feedbackDialog, setFeedbackDialog] = useState(false);
  const [walletDialog, setWalletDialog] = useState(false);
  const [feedbackForm, setFeedbackForm] = useState({ rating: 5, foodRating: 5, serviceRating: 5, ambienceRating: 5, comment: '' });
  const [tagFilter, setTagFilter] = useState('all');

  const fetchCustomers = useCallback(async () => {
    try {
      const res = await customersAPI.getAll();
      setCustomers(res.data);
    } catch (e) { console.error(e); toast.error('Could not load customers'); }
  }, []);

  useEffect(() => { fetchCustomers(); }, [fetchCustomers]);

  const fetchProfile = async (id) => {
    try {
      const res = await customersAPI.getProfile(id);
      setProfile(res.data);
      setSelectedCustomer(id);
    } catch (e) { toast.error('Failed to load profile'); }
  };

  const filtered = customers.filter(c => {
    const matchSearch = !searchTerm ||
      c.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (c.email && c.email.toLowerCase().includes(searchTerm.toLowerCase())) ||
      (c.phone && c.phone.includes(searchTerm));
    const matchTag = tagFilter === 'all' || (c.tags && c.tags.includes(tagFilter)) ||
      (tagFilter === 'vip' && c.isVip);
    return matchSearch && matchTag;
  });

  const openNew = () => { setEditMode(false); setForm({ ...emptyCustomerForm }); setDialogOpen(true); };
  const openEdit = (c) => {
    setEditMode(true);
    setForm({
      name: c.name, email: c.email, phone: c.phone, membershipTier: c.membershipTier || 'Bronze',
      birthday: c.birthday || '', company: c.company || '', seatingPreference: c.seatingPreference || '',
      dietaryRestrictions: c.dietaryRestrictions || [], allergies: c.allergies || [],
      tags: c.tags || [], isVip: c.isVip || false, notes: c.notes || '',
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name || !form.email) { toast.error('Name and email required'); return; }
    try {
      if (editMode && selectedCustomer) {
        await customersAPI.update(selectedCustomer, form);
        toast.success('Customer updated');
        fetchProfile(selectedCustomer);
      } else {
        await customersAPI.create(form);
        toast.success('Customer created');
      }
      setDialogOpen(false);
      fetchCustomers();
    } catch (e) { toast.error('Failed to save'); }
  };

  const handleFeedback = async () => {
    try {
      await feedbackAPI.create({
        customerId: selectedCustomer,
        guestName: profile?.name || '',
        ...feedbackForm,
      });
      toast.success('Feedback recorded');
      setFeedbackDialog(false);
      fetchProfile(selectedCustomer);
    } catch (e) { toast.error('Failed'); }
  };

  const toggleArrayItem = (field, item) => {
    setForm(f => ({
      ...f,
      [field]: f[field].includes(item) ? f[field].filter(i => i !== item) : [...f[field], item]
    }));
  };

  // Stats
  const stats = {
    total: customers.length,
    vips: customers.filter(c => c.isVip).length,
    avgRating: customers.length > 0 ? (customers.reduce((s, c) => s + (c.feedbackRating || 0), 0) / customers.filter(c => c.feedbackRating > 0).length || 0).toFixed(1) : '0',
    noShows: customers.reduce((s, c) => s + (c.noShowCount || 0), 0),
  };

  // Profile View
  if (selectedCustomer && profile) {
    const tc = TIER_CONFIG[profile.membershipTier] || TIER_CONFIG.Bronze;
    return (
      <div className="space-y-6" data-testid="customer-profile-view">
        {/* Back button + header */}
        <div className="flex items-center gap-4">
          <Button variant="ghost" onClick={() => { setSelectedCustomer(null); setProfile(null); }} data-testid="back-to-list-btn">
            <ArrowLeft size={18} className="mr-1" /> Back
          </Button>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <div className="w-14 h-14 rounded-full flex items-center justify-center text-white font-bold text-xl"
                style={{ background: theme.primary }}>
                {profile.name.split(' ').map(n => n[0]).join('').slice(0, 2)}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-2xl font-bold" style={{ color: theme.text }}>{profile.name}</h1>
                  {profile.isVip && <Badge className="bg-amber-100 text-amber-700 text-xs">VIP</Badge>}
                  <Badge style={{ background: tc.bg, color: tc.color }}>{profile.membershipTier}</Badge>
                </div>
                <div className="flex items-center gap-4 text-sm text-gray-500 mt-1">
                  <span className="flex items-center gap-1"><Mail size={12} />{profile.email}</span>
                  <span className="flex items-center gap-1"><Phone size={12} />{profile.phone}</span>
                  {profile.company && <span className="flex items-center gap-1"><Shield size={12} />{profile.company}</span>}
                </div>
              </div>
            </div>
          </div>
          <Button variant="outline" onClick={() => openEdit(profile)} data-testid="edit-profile-btn">
            <Edit2 size={14} className="mr-1" /> Edit
          </Button>
          <Button variant="outline" onClick={() => setFeedbackDialog(true)} data-testid="add-feedback-btn">
            <MessageSquare size={14} className="mr-1" /> Add Feedback
          </Button>
          <Button variant="outline" onClick={() => setWalletDialog(true)} data-testid="wallet-btn">
            <Wallet size={14} className="mr-1" /> Wallet
          </Button>
        </div>

        {/* Quick stats */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
          {[
            { label: 'Total Spent', val: `$${(profile.totalSpent || 0).toFixed(0)}`, icon: DollarSign, color: theme.primary },
            { label: 'Visits', val: profile.visits || 0, icon: Calendar, color: '#10B981' },
            { label: 'Avg Spend', val: `$${(profile.avgSpendPerVisit || 0).toFixed(0)}`, icon: DollarSign, color: '#3B82F6' },
            { label: 'Points', val: profile.points || 0, icon: Award, color: '#F59E0B' },
            { label: 'Rating', val: profile.feedbackRating ? `${profile.feedbackRating}/5` : 'N/A', icon: Star, color: '#EC4899' },
            { label: 'No Shows', val: profile.noShowCount || 0, icon: AlertCircle, color: profile.noShowCount > 2 ? '#EF4444' : '#6B7280' },
          ].map((s, i) => (
            <Card key={i} className="border-0 shadow-sm">
              <CardContent className="p-3 flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${s.color}15` }}>
                  <s.icon size={16} style={{ color: s.color }} />
                </div>
                <div>
                  <p className="text-lg font-bold" style={{ color: theme.text }}>{s.val}</p>
                  <p className="text-[10px] text-gray-500">{s.label}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Tabs value={profileTab} onValueChange={setProfileTab}>
          <TabsList>
            <TabsTrigger value="overview" data-testid="tab-overview">Overview</TabsTrigger>
            <TabsTrigger value="reservations" data-testid="tab-reservations">Reservations</TabsTrigger>
            <TabsTrigger value="feedback" data-testid="tab-feedback">Feedback</TabsTrigger>
            <TabsTrigger value="transactions" data-testid="tab-transactions">Transactions</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4 mt-4">
            <div className="grid grid-cols-2 gap-4">
              {/* Preferences */}
              <Card className="border-0 shadow-sm">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Guest Preferences</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Seating Preference</p>
                    <p className="text-sm font-medium capitalize">{profile.seatingPreference || 'No preference'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Favorite Dishes</p>
                    <div className="flex flex-wrap gap-1">
                      {(profile.favoriteDishes || []).length > 0 ? profile.favoriteDishes.map((d, i) => (
                        <Badge key={i} variant="outline" className="text-xs">{d}</Badge>
                      )) : <span className="text-xs text-gray-400">None recorded</span>}
                    </div>
                  </div>
                  {profile.birthday && <div>
                    <p className="text-xs text-gray-500 mb-1">Birthday</p>
                    <p className="text-sm font-medium">{profile.birthday}</p>
                  </div>}
                </CardContent>
              </Card>
              {/* Dietary & Allergies */}
              <Card className="border-0 shadow-sm">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Dietary & Allergies</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Dietary Restrictions</p>
                    <div className="flex flex-wrap gap-1">
                      {(profile.dietaryRestrictions || []).length > 0 ? profile.dietaryRestrictions.map((d, i) => (
                        <Badge key={i} className="bg-green-50 text-green-700 text-xs">{d}</Badge>
                      )) : <span className="text-xs text-gray-400">None</span>}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Allergies</p>
                    <div className="flex flex-wrap gap-1">
                      {(profile.allergies || []).length > 0 ? profile.allergies.map((a, i) => (
                        <Badge key={i} className="bg-red-50 text-red-700 text-xs">{a}</Badge>
                      )) : <span className="text-xs text-gray-400">None</span>}
                    </div>
                  </div>
                </CardContent>
              </Card>
              {/* Tags */}
              <Card className="border-0 shadow-sm">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Tags</CardTitle></CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {(profile.tags || []).length > 0 ? profile.tags.map((t, i) => (
                      <Badge key={i} style={{ background: `${theme.primary}15`, color: theme.primary }}>{t}</Badge>
                    )) : <span className="text-xs text-gray-400">No tags</span>}
                  </div>
                </CardContent>
              </Card>
              {/* Notes */}
              <Card className="border-0 shadow-sm">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Staff Notes</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-sm text-gray-600">{profile.notes || 'No notes yet.'}</p>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="reservations" className="mt-4">
            <Card className="border-0 shadow-sm">
              <CardContent className="p-0">
                <table className="w-full text-sm" data-testid="profile-reservations-table">
                  <thead><tr className="border-b bg-gray-50/80">
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Date</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Time</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Party</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Table</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Status</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Notes</th>
                  </tr></thead>
                  <tbody>
                    {(profile.reservationHistory || []).length === 0 ? (
                      <tr><td colSpan={6} className="py-8 text-center text-gray-400">No reservation history</td></tr>
                    ) : profile.reservationHistory.map(r => (
                      <tr key={r.id} className="border-b hover:bg-gray-50/50">
                        <td className="px-4 py-2 font-medium">{r.date}</td>
                        <td className="px-4 py-2">{r.time}</td>
                        <td className="px-4 py-2">{r.partySize}</td>
                        <td className="px-4 py-2">{r.tableNumber || '—'}</td>
                        <td className="px-4 py-2 capitalize">{r.status?.replace('_', ' ')}</td>
                        <td className="px-4 py-2 text-xs text-gray-500 truncate max-w-[200px]">{r.specialRequests || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="feedback" className="mt-4 space-y-3">
            {(profile.feedbackHistory || []).length === 0 ? (
              <Card className="border-0 shadow-sm"><CardContent className="py-8 text-center text-gray-400">No feedback yet</CardContent></Card>
            ) : profile.feedbackHistory.map(fb => (
              <Card key={fb.id} className="border-0 shadow-sm">
                <CardContent className="p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <div className="flex gap-0.5">
                        {[1, 2, 3, 4, 5].map(s => (
                          <Star key={s} size={14} fill={s <= fb.rating ? '#F59E0B' : 'none'} stroke={s <= fb.rating ? '#F59E0B' : '#D1D5DB'} />
                        ))}
                      </div>
                      <span className="text-sm font-medium">{fb.rating}/5</span>
                    </div>
                    <span className="text-xs text-gray-400">{new Date(fb.createdAt).toLocaleDateString()}</span>
                  </div>
                  {fb.comment && <p className="text-sm text-gray-600 mt-2">{fb.comment}</p>}
                  <div className="flex gap-4 mt-2 text-xs text-gray-500">
                    {fb.foodRating && <span>Food: {fb.foodRating}/5</span>}
                    {fb.serviceRating && <span>Service: {fb.serviceRating}/5</span>}
                    {fb.ambienceRating && <span>Ambience: {fb.ambienceRating}/5</span>}
                  </div>
                  {fb.response && <div className="mt-2 p-2 bg-blue-50 rounded text-xs text-blue-700">Response: {fb.response}</div>}
                </CardContent>
              </Card>
            ))}
          </TabsContent>

          <TabsContent value="transactions" className="mt-4">
            <Card className="border-0 shadow-sm">
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead><tr className="border-b bg-gray-50/80">
                    <th className="text-left px-4 py-3 font-medium text-gray-500">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Date</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Items</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-500">Total</th>
                  </tr></thead>
                  <tbody>
                    {(profile.transactionHistory || []).length === 0 ? (
                      <tr><td colSpan={4} className="py-8 text-center text-gray-400">No transaction history</td></tr>
                    ) : profile.transactionHistory.map(t => (
                      <tr key={t.id} className="border-b hover:bg-gray-50/50">
                        <td className="px-4 py-2 font-mono text-xs">{t.id}</td>
                        <td className="px-4 py-2">{new Date(t.timestamp).toLocaleDateString()}</td>
                        <td className="px-4 py-2">{(t.items || []).length} items</td>
                        <td className="px-4 py-2 text-right font-medium">${(t.total || 0).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {/* Feedback Dialog */}
        <Dialog open={feedbackDialog} onOpenChange={setFeedbackDialog}>
          <DialogContent className="max-w-md" data-testid="feedback-dialog">
            <DialogHeader><DialogTitle>Add Guest Feedback</DialogTitle></DialogHeader>
            <div className="space-y-4">
              {[
                { label: 'Overall Rating', field: 'rating' },
                { label: 'Food', field: 'foodRating' },
                { label: 'Service', field: 'serviceRating' },
                { label: 'Ambience', field: 'ambienceRating' },
              ].map(({ label, field }) => (
                <div key={field}>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">{label}</label>
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map(s => (
                      <button key={s} onClick={() => setFeedbackForm(f => ({ ...f, [field]: s }))}
                        className="p-1 hover:scale-110 transition-transform">
                        <Star size={20} fill={s <= feedbackForm[field] ? '#F59E0B' : 'none'}
                          stroke={s <= feedbackForm[field] ? '#F59E0B' : '#D1D5DB'} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Comment</label>
                <Input data-testid="feedback-comment" value={feedbackForm.comment}
                  onChange={e => setFeedbackForm(f => ({ ...f, comment: e.target.value }))}
                  placeholder="Guest feedback..." />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setFeedbackDialog(false)}>Cancel</Button>
              <Button onClick={handleFeedback} style={{ background: theme.primary }} data-testid="submit-feedback-btn">Submit</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Customer Edit Dialog (shared) */}
        {renderCustomerDialog()}

        {/* Unified Wallet + Journey + Loyalty + AI Recs */}
        <CustomerWalletPanel customer={profile} theme={theme} onRefresh={() => fetchAll?.()} />

        {/* Digital Wallet Dialog */}
        <GuestWalletDialog open={walletDialog} onOpenChange={setWalletDialog} customer={profile} />
      </div>
    );
  }

  function renderCustomerDialog() {
    return (
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto" data-testid="customer-dialog">
          <DialogHeader>
            <DialogTitle>{editMode ? 'Edit Guest Profile' : 'New Guest'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-xs font-medium text-gray-500 mb-1 block">Name *</label>
                <Input data-testid="cust-name" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Email *</label>
                <Input data-testid="cust-email" type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Phone</label>
                <Input data-testid="cust-phone" value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Birthday</label>
                <Input type="date" value={form.birthday} onChange={e => setForm(f => ({ ...f, birthday: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Company</label>
                <Input value={form.company} onChange={e => setForm(f => ({ ...f, company: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Tier</label>
                <Select value={form.membershipTier} onValueChange={v => setForm(f => ({ ...f, membershipTier: v }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {['Bronze', 'Silver', 'Gold', 'Platinum'].map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Seating Preference</label>
                <Select value={form.seatingPreference || 'none'} onValueChange={v => setForm(f => ({ ...f, seatingPreference: v === 'none' ? '' : v }))}>
                  <SelectTrigger><SelectValue placeholder="Any" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Any</SelectItem>
                    {['indoor', 'outdoor', 'bar', 'window', 'booth'].map(s => <SelectItem key={s} value={s} className="capitalize">{s}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-2 block">Dietary Restrictions</label>
              <div className="flex flex-wrap gap-1.5">
                {DIETARY_OPTIONS.map(d => (
                  <Badge key={d} variant={form.dietaryRestrictions.includes(d) ? 'default' : 'outline'}
                    className="cursor-pointer text-xs" onClick={() => toggleArrayItem('dietaryRestrictions', d)}
                    style={form.dietaryRestrictions.includes(d) ? { background: '#10B981' } : {}}>
                    {d}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-2 block">Allergies</label>
              <div className="flex flex-wrap gap-1.5">
                {ALLERGY_OPTIONS.map(a => (
                  <Badge key={a} variant={form.allergies.includes(a) ? 'default' : 'outline'}
                    className="cursor-pointer text-xs" onClick={() => toggleArrayItem('allergies', a)}
                    style={form.allergies.includes(a) ? { background: '#EF4444' } : {}}>
                    {a}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-2 block">Tags</label>
              <div className="flex flex-wrap gap-1.5">
                {TAG_OPTIONS.map(t => (
                  <Badge key={t} variant={form.tags.includes(t) ? 'default' : 'outline'}
                    className="cursor-pointer text-xs" onClick={() => toggleArrayItem('tags', t)}
                    style={form.tags.includes(t) ? { background: theme.primary } : {}}>
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input type="checkbox" checked={form.isVip} onChange={e => setForm(f => ({ ...f, isVip: e.target.checked }))} />
              <label className="text-sm font-medium">VIP Guest</label>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Notes</label>
              <Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Internal notes about this guest..." />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} style={{ background: theme.primary }} data-testid="save-customer-btn">{editMode ? 'Update' : 'Create'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  // List View
  return (
    <div className="space-y-6" data-testid="customers-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Guest CRM</h1>
          <p className="text-sm text-gray-500 mt-1">360-degree guest profiles, preferences & history</p>
        </div>
        <Button onClick={openNew} style={{ background: theme.primary }} data-testid="add-customer-btn">
          <Plus size={16} className="mr-2" /> Add Guest
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Guests', val: stats.total, icon: Users, color: theme.primary },
          { label: 'VIP Guests', val: stats.vips, icon: Award, color: '#F59E0B' },
          { label: 'Avg Rating', val: stats.avgRating, icon: Star, color: '#EC4899' },
          { label: 'Total No-Shows', val: stats.noShows, icon: AlertCircle, color: '#EF4444' },
        ].map((s, i) => (
          <Card key={i} className="border-0 shadow-sm">
            <CardContent className="p-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: `${s.color}15` }}>
                <s.icon size={20} style={{ color: s.color }} />
              </div>
              <div>
                <p className="text-2xl font-bold" style={{ color: theme.text }}>{s.val}</p>
                <p className="text-xs text-gray-500">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <Input placeholder="Search by name, email, or phone..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
            className="pl-9" data-testid="search-customers" />
        </div>
        <Select value={tagFilter} onValueChange={setTagFilter}>
          <SelectTrigger className="w-40" data-testid="tag-filter">
            <Tag size={14} className="mr-2" /><SelectValue placeholder="All Tags" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Tags</SelectItem>
            <SelectItem value="vip">VIP</SelectItem>
            {TAG_OPTIONS.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {/* Customer Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map(customer => {
          const tc = TIER_CONFIG[customer.membershipTier] || TIER_CONFIG.Bronze;
          return (
            <Card key={customer.id} className="border-0 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
              onClick={() => fetchProfile(customer.id)} data-testid={`customer-card-${customer.id}`}>
              <CardContent className="p-5">
                <div className="flex items-start gap-3">
                  <div className="w-12 h-12 rounded-full flex items-center justify-center text-white font-bold"
                    style={{ background: theme.primary }}>
                    {customer.name.split(' ').map(n => n[0]).join('').slice(0, 2)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold truncate" style={{ color: theme.text }}>{customer.name}</h3>
                      {customer.isVip && <Badge className="bg-amber-100 text-amber-700 text-[10px] shrink-0">VIP</Badge>}
                    </div>
                    <p className="text-xs text-gray-500 truncate">{customer.email}</p>
                    <div className="flex items-center gap-2 mt-2">
                      <Badge style={{ background: tc.bg, color: tc.color }} className="text-[10px]">{customer.membershipTier}</Badge>
                      {(customer.tags || []).slice(0, 2).map((t, i) => (
                        <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
                      ))}
                    </div>
                  </div>
                  <ChevronRight size={16} className="text-gray-300 shrink-0 mt-3" />
                </div>
                <div className="grid grid-cols-3 gap-3 mt-4 pt-3 border-t">
                  <div>
                    <p className="text-[10px] text-gray-500">Spent</p>
                    <p className="text-sm font-bold" style={{ color: theme.primary }}>${(customer.totalSpent || 0).toFixed(0)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-500">Visits</p>
                    <p className="text-sm font-bold">{customer.visits || 0}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-500">Points</p>
                    <p className="text-sm font-bold" style={{ color: theme.accent }}>{customer.points || 0}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {renderCustomerDialog()}
    </div>
  );
};

export default Customers;
