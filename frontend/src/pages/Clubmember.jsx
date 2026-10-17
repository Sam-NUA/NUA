import React, { useState, useEffect } from 'react';
import { Tag, Plus, Edit, Trash2, Clock, Users, Percent, Link2, Unlink } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { reservationFeaturesAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

export default function Clubmember() {
  const { theme } = useTheme();
  const [offers, setOffers] = useState([]);
  const [socialAccounts, setSocialAccounts] = useState([]);
  const [showDialog, setShowDialog] = useState(false);
  const [showSocialDialog, setShowSocialDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ title: '', description: '', discount: 20, startDate: '', startTime: '00:00', endDate: '', endTime: '23:59', totalSlots: 10, active: true, socialPlatforms: ['instagram', 'facebook'] });
  const [socialForm, setSocialForm] = useState({ platform: 'instagram', accountName: '', accessToken: '' });

  useEffect(() => { fetchData(); }, []);
  const fetchData = async () => {
    const [offersRes, accountsRes] = await Promise.allSettled([
      reservationFeaturesAPI.getClubOffers(),
      reservationFeaturesAPI.getSocialAccounts(),
    ]);
    if (offersRes.status === 'fulfilled') setOffers(offersRes.value.data);
    if (accountsRes.status === 'fulfilled') setSocialAccounts(accountsRes.value.data);
  };

  const openAdd = () => { setEditing(null); setForm({ title: '', description: '', discount: 20, startDate: '', startTime: '00:00', endDate: '', endTime: '23:59', totalSlots: 10, active: true, socialPlatforms: ['instagram', 'facebook'] }); setShowDialog(true); };
  const openEdit = (o) => { setEditing(o); setForm({ title: o.title, description: o.description, discount: o.discount, startDate: o.startDate || '', startTime: o.startTime || '00:00', endDate: o.endDate || '', endTime: o.endTime || '23:59', totalSlots: o.totalSlots, active: o.active, socialPlatforms: o.socialPlatforms || [] }); setShowDialog(true); };

  const handleSave = async () => {
    if (!form.title) { toast.error('Title required'); return; }
    const data = { ...form, discount: parseInt(form.discount), totalSlots: parseInt(form.totalSlots) };
    try {
      if (editing) { await reservationFeaturesAPI.updateClubOffer(editing.id, data); toast.success('Offer updated'); }
      else { await reservationFeaturesAPI.createClubOffer(data); toast.success('Offer created'); }
      setShowDialog(false); fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const handleDelete = async (id) => {
    if (!await DialogService.confirm('Delete this offer?')) return;
    try { await reservationFeaturesAPI.deleteClubOffer(id); toast.success('Deleted'); fetchData(); } catch {}
  };

  const platforms = ['instagram', 'facebook', 'tiktok', 'twitter', 'google'];

  return (
    <div className="space-y-6" data-testid="clubmember-page">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold" style={{ color: theme.text }}>Clubmember Offers</h1><p className="text-sm text-gray-500">Social media booking rewards (EatClub-style). 20-50% discounts with limited slots.</p></div>
        <Button style={{ backgroundColor: theme.primary }} onClick={openAdd} data-testid="add-offer-btn"><Plus size={16} className="mr-1" /> New Offer</Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {offers.map(offer => {
          const remaining = offer.totalSlots - (offer.claimedSlots || 0);
          return (
            <Card key={offer.id} className={`${!offer.active ? 'opacity-60' : ''}`} data-testid={`offer-${offer.id}`}>
              <CardContent className="p-5">
                <div className="flex items-start justify-between mb-3">
                  <Badge className="bg-red-100 text-red-700 text-lg font-bold">{offer.discount}% OFF</Badge>
                  <Badge className={offer.active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}>{offer.active ? 'Live' : 'Paused'}</Badge>
                </div>
                <h3 className="font-bold text-lg mb-1">{offer.title}</h3>
                <p className="text-sm text-gray-500 mb-3">{offer.description}</p>
                <div className="grid grid-cols-2 gap-2 text-sm mb-3">
                  <div className="flex items-center gap-1 text-gray-600"><Clock size={13} /><span>{offer.startDate || 'Open'} → {offer.endDate || 'Ongoing'}</span></div>
                  <div className="flex items-center gap-1 text-gray-600"><Users size={13} /><span>{remaining}/{offer.totalSlots} left</span></div>
                </div>
                <div className="w-full h-2 bg-gray-200 rounded-full mb-3">
                  <div className="h-full rounded-full bg-red-500" style={{ width: `${((offer.claimedSlots || 0) / Math.max(offer.totalSlots, 1)) * 100}%` }} />
                </div>
                <div className="flex flex-wrap gap-1 mb-3">
                  {(offer.socialPlatforms || []).map(p => <Badge key={p} variant="outline" className="text-[10px] capitalize">{p}</Badge>)}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => openEdit(offer)} data-testid={`edit-offer-${offer.id}`}><Edit size={14} /></Button>
                  <Button variant="outline" size="sm" className="text-red-500" onClick={() => handleDelete(offer.id)}><Trash2 size={14} /></Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
        {offers.length === 0 && <Card className="col-span-3 border-dashed"><CardContent className="p-12 text-center"><Tag size={40} className="mx-auto mb-3 text-gray-300" /><p className="text-gray-500">No club offers yet. Create your first social media reward!</p></CardContent></Card>}
      </div>


      {/* Social Media Accounts */}
      <Card><CardHeader><CardTitle className="text-sm flex items-center justify-between">
        <span className="flex items-center gap-2"><Link2 size={16} /> Connected Social Accounts</span>
        <Button size="sm" variant="outline" onClick={() => setShowSocialDialog(true)} data-testid="add-social-btn"><Plus size={14} className="mr-1" /> Connect Account</Button>
      </CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {socialAccounts.map(acc => (
          <div key={acc.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg" data-testid={`social-${acc.id}`}>
            <div className="flex items-center gap-3">
              <Badge className="capitalize">{acc.platform}</Badge>
              <span className="text-sm font-medium">{acc.accountName}</span>
              <Badge className="bg-green-100 text-green-700 text-[10px]">Connected</Badge>
            </div>
            <Button variant="ghost" size="sm" className="text-red-500" onClick={async () => {
              await reservationFeaturesAPI.removeSocialAccount(acc.id); fetchData(); toast.success('Disconnected');
            }}><Unlink size={14} /></Button>
          </div>
        ))}
        {socialAccounts.length === 0 && <p className="text-gray-400 text-sm text-center py-4">No accounts connected. Connect your social media to auto-post offers.</p>}
      </CardContent></Card>

      {/* Social Account Dialog */}
      <Dialog open={showSocialDialog} onOpenChange={setShowSocialDialog}>
        <DialogContent className="max-w-sm" data-testid="social-account-dialog">
          <DialogHeader><DialogTitle>Connect Social Account</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <select className="w-full p-2 border rounded-md text-sm" value={socialForm.platform} onChange={e => setSocialForm({ ...socialForm, platform: e.target.value })} data-testid="social-platform">
              <option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="tiktok">TikTok</option><option value="twitter">Twitter/X</option><option value="google">Google Business</option>
            </select>
            <Input placeholder="Account name / handle" value={socialForm.accountName} onChange={e => setSocialForm({ ...socialForm, accountName: e.target.value })} data-testid="social-account-name" />
            <Input type="password" placeholder="Access token / API key" value={socialForm.accessToken} onChange={e => setSocialForm({ ...socialForm, accessToken: e.target.value })} data-testid="social-token" />
            <p className="text-xs text-gray-400">Token is used for auto-posting offers to your social platforms.</p>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={async () => {
              if (!socialForm.accountName) { toast.error('Account name required'); return; }
              try { await reservationFeaturesAPI.addSocialAccount(socialForm); toast.success('Account connected'); setShowSocialDialog(false); setSocialForm({ platform: 'instagram', accountName: '', accessToken: '' }); fetchData(); } catch { toast.error('Failed'); }
            }} data-testid="connect-social-btn">Connect Account</Button>
          </div>
        </DialogContent>
      </Dialog>


      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-w-md" data-testid="offer-dialog">
          <DialogHeader><DialogTitle>{editing ? 'Edit Offer' : 'New Club Offer'}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2 max-h-[60vh] overflow-y-auto">
            <Input placeholder="Offer title" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} data-testid="offer-title" />
            <textarea className="w-full min-h-[50px] p-2 border rounded-md text-sm" placeholder="Description..." value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Discount (20-50%)</label>
              <div className="flex items-center gap-2">
                <input type="range" min="20" max="50" step="5" value={form.discount} onChange={e => setForm({ ...form, discount: e.target.value })} className="flex-1" data-testid="offer-discount" />
                <span className="text-lg font-bold" style={{ color: theme.primary }}>{form.discount}%</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div><label className="text-xs text-gray-500">Start Date</label><Input type="date" value={form.startDate} onChange={e => setForm({ ...form, startDate: e.target.value })} data-testid="offer-start-date" /></div>
              <div><label className="text-xs text-gray-500">Start Time</label><Input type="time" value={form.startTime} onChange={e => setForm({ ...form, startTime: e.target.value })} /></div>
              <div><label className="text-xs text-gray-500">End Date</label><Input type="date" value={form.endDate} onChange={e => setForm({ ...form, endDate: e.target.value })} data-testid="offer-end-date" /></div>
              <div><label className="text-xs text-gray-500">End Time</label><Input type="time" value={form.endTime} onChange={e => setForm({ ...form, endTime: e.target.value })} /></div>
            </div>
            <Input type="number" placeholder="Total slots available" value={form.totalSlots} onChange={e => setForm({ ...form, totalSlots: e.target.value })} data-testid="offer-slots" />
            <div><label className="text-xs font-medium text-gray-500 mb-1 block">Social Platforms</label>
              <div className="flex flex-wrap gap-1.5">{platforms.map(p => (
                <button key={p} type="button" onClick={() => { const sp = form.socialPlatforms.includes(p) ? form.socialPlatforms.filter(x => x !== p) : [...form.socialPlatforms, p]; setForm({ ...form, socialPlatforms: sp }); }}
                  className={`px-2.5 py-1 text-xs rounded-full font-medium capitalize ${form.socialPlatforms.includes(p) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}`}>{p}</button>
              ))}</div>
            </div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={e => setForm({ ...form, active: e.target.checked })} /> Active</label>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleSave} data-testid="save-offer-btn">{editing ? 'Update' : 'Create'} Offer</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
