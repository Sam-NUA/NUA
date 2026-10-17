import React, { useState, useEffect } from 'react';
import {
  Mail, Send, Plus, Users, Trash2, Clock, CheckCircle, Edit2, Sparkles, Ticket, Wand2, LayoutTemplate, Filter, Save, Pencil, List, X, Repeat, PlayCircle
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { toast } from 'sonner';
import { advancedAPI } from '../services/api';
import axios from 'axios';
import { SecureStorageService } from '../platform';

const API = process.env.REACT_APP_BACKEND_URL;
const authHeader = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const EMPTY_FORM = {
  name: '', subject: '', body: '', targetTier: '',
  voucherEnabled: false, voucherValueType: 'percent', voucherValue: 15,
  voucherExpiresInDays: 30, voucherMinSpend: 0,
  recurringEnabled: false, recurringIntervalDays: 7,
};

const EMPTY_SEGMENT_RULES = { minSpend: '', minVisits: '', inactiveForDays: '', spendInLastDays: '', minSpendInWindow: '' };

export default function EmailMarketing() {
  const { theme } = useTheme();
  const [campaigns, setCampaigns] = useState([]);
  const [memberStats, setMemberStats] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [brief, setBrief] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [improving, setImproving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [audienceMode, setAudienceMode] = useState('tier'); // 'tier' | 'segment'
  const [segments, setSegments] = useState([]);
  const [segmentId, setSegmentId] = useState('');
  const [segmentRules, setSegmentRules] = useState(EMPTY_SEGMENT_RULES);
  const [segmentPreview, setSegmentPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [segmentName, setSegmentName] = useState('');
  const [savingSegment, setSavingSegment] = useState(false);
  const [editingSegmentId, setEditingSegmentId] = useState(null);
  const [fullListSegment, setFullListSegment] = useState(null);
  const [fullList, setFullList] = useState(null);
  const [loadingFullList, setLoadingFullList] = useState(false);

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [camp, stats, segs] = await Promise.all([
        advancedAPI.getCampaigns(),
        axios.get(`${API}/api/members/stats`, { headers: await authHeader() }).catch(() => ({ data: null })),
        advancedAPI.getSegments().catch(() => ({ data: [] })),
      ]);
      setCampaigns(camp.data);
      setMemberStats(stats.data);
      setSegments(segs.data || []);
    } catch {}
  };

  const openCreate = async () => {
    setForm(EMPTY_FORM);
    setBrief('');
    setAudienceMode('tier');
    setSegmentId('');
    setSegmentRules(EMPTY_SEGMENT_RULES);
    setSegmentPreview(null);
    setSegmentName('');
    setEditingSegmentId(null);
    setShowCreate(true);
    if (templates.length === 0) {
      try {
        const r = await advancedAPI.getCampaignTemplates();
        setTemplates(r.data || []);
      } catch {}
    }
    if (segments.length === 0) {
      try {
        const r = await advancedAPI.getSegments();
        setSegments(r.data || []);
      } catch {}
    }
  };

  const rulesPayload = () => {
    const r = {};
    if (segmentRules.minSpend !== '') r.minSpend = Number(segmentRules.minSpend);
    if (segmentRules.minVisits !== '') r.minVisits = Number(segmentRules.minVisits);
    if (segmentRules.inactiveForDays !== '') r.inactiveForDays = Number(segmentRules.inactiveForDays);
    if (segmentRules.spendInLastDays !== '') r.spendInLastDays = Number(segmentRules.spendInLastDays);
    if (segmentRules.minSpendInWindow !== '') r.minSpendInWindow = Number(segmentRules.minSpendInWindow);
    return r;
  };

  const previewCustomSegment = async () => {
    setPreviewing(true);
    try {
      const r = await advancedAPI.previewSegment(rulesPayload());
      setSegmentPreview(r.data);
    } catch { toast.error('Could not preview segment'); }
    finally { setPreviewing(false); }
  };

  const startEditingSegment = (segment) => {
    setEditingSegmentId(segment.id);
    setSegmentId('');
    setSegmentName(segment.name);
    setSegmentRules({ ...EMPTY_SEGMENT_RULES, ...segment.rules });
    setSegmentPreview(null);
  };

  const cancelEditingSegment = () => {
    setEditingSegmentId(null);
    setSegmentName('');
    setSegmentRules(EMPTY_SEGMENT_RULES);
    setSegmentPreview(null);
  };

  const saveSegment = async () => {
    if (!segmentName.trim()) return toast.error('Give the segment a name to save it');
    setSavingSegment(true);
    try {
      const r = editingSegmentId
        ? await advancedAPI.updateSegment(editingSegmentId, { name: segmentName.trim(), rules: rulesPayload() })
        : await advancedAPI.createSegment({ name: segmentName.trim(), rules: rulesPayload() });
      toast.success(editingSegmentId ? 'Segment updated' : 'Segment saved');
      setSegments(s => editingSegmentId ? s.map(x => x.id === r.data.id ? r.data : x) : [r.data, ...s]);
      setSegmentId(r.data.id);
      setSegmentName('');
      setEditingSegmentId(null);
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save segment'); }
    finally { setSavingSegment(false); }
  };

  const viewFullList = async (segment) => {
    setFullListSegment(segment);
    setFullList(null);
    setLoadingFullList(true);
    try {
      const r = await advancedAPI.getSegmentCustomers(segment.id);
      setFullList(r.data);
    } catch { toast.error('Could not load the full segment list'); }
    finally { setLoadingFullList(false); }
  };

  const applyTemplate = (t) => {
    setForm(f => ({ ...f, name: t.label, subject: t.subject, body: t.body, targetTier: t.targetTier || f.targetTier }));
  };

  const handleAiDraft = async () => {
    setDrafting(true);
    try {
      const r = await advancedAPI.draftCampaign({ brief, targetTier: form.targetTier });
      setForm(f => ({ ...f, name: r.data.name || f.name, subject: r.data.subject || f.subject, body: r.data.body || f.body }));
      toast.success('AI draft ready — review and tweak before sending');
    } catch { toast.error('Could not generate a draft'); }
    finally { setDrafting(false); }
  };

  const handleImproveWording = async () => {
    if (!form.body) { toast.error('Write or generate a draft first'); return; }
    setImproving(true);
    try {
      const r = await advancedAPI.improveCampaignCopy({ subject: form.subject, body: form.body });
      setForm(f => ({ ...f, subject: r.data.subject || f.subject, body: r.data.body || f.body }));
      toast.success('Wording improved');
    } catch { toast.error('Could not improve wording'); }
    finally { setImproving(false); }
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      await advancedAPI.createCampaign({
        name: form.name, subject: form.subject, body: form.body,
        targetTier: audienceMode === 'tier' ? form.targetTier : '',
        segmentId: audienceMode === 'segment' && segmentId ? segmentId : undefined,
        segmentRules: audienceMode === 'segment' && !segmentId ? rulesPayload() : undefined,
        voucher: form.voucherEnabled ? {
          enabled: true, valueType: form.voucherValueType, value: Number(form.voucherValue) || 0,
          expiresInDays: Number(form.voucherExpiresInDays) || 30, minSpend: Number(form.voucherMinSpend) || 0,
        } : undefined,
        recurring: form.recurringEnabled ? {
          enabled: true, intervalDays: Number(form.recurringIntervalDays) || 7,
        } : undefined,
      });
      toast.success(form.recurringEnabled ? 'Recurring campaign created — it will run on its schedule' : 'Campaign created');
      setShowCreate(false);
      setForm(EMPTY_FORM);
      fetchData();
    } catch (e) { toast.error('Failed to create campaign'); }
    finally { setCreating(false); }
  };

  const handleSend = async (id) => {
    try {
      const res = await advancedAPI.sendCampaign(id);
      toast.success(res.data.message);
      fetchData();
    } catch { toast.error('Failed to send'); }
  };

  const handleRunNow = async (id) => {
    try {
      const res = await advancedAPI.runCampaignNow(id);
      toast.success(res.data.message);
      fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to run'); }
  };

  const [runningDue, setRunningDue] = useState(false);
  const handleRunDue = async () => {
    setRunningDue(true);
    try {
      const res = await advancedAPI.runDueCampaigns();
      toast.success(res.data.ran > 0 ? `Ran ${res.data.ran} due campaign(s)` : 'No campaigns due right now');
      fetchData();
    } catch { toast.error('Failed to run due campaigns'); }
    finally { setRunningDue(false); }
  };

  const handleDelete = async (id) => {
    try {
      await advancedAPI.deleteCampaign(id);
      toast.success('Campaign deleted');
      fetchData();
    } catch {}
  };

  return (
    <div data-testid="email-marketing-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: theme.text }}>Email Marketing</h1>
          <p className="text-gray-500 mt-1">
            {memberStats?.totalMembers || 0} members &middot; {campaigns.length} campaigns
          </p>
        </div>
        <div className="flex gap-2">
          {campaigns.some(c => c.status === 'recurring') && (
            <Button variant="outline" onClick={handleRunDue} disabled={runningDue} data-testid="run-due-campaigns-btn">
              <PlayCircle size={16} className="mr-1" /> {runningDue ? 'Running…' : 'Run due campaigns'}
            </Button>
          )}
          <Button onClick={openCreate} style={{ backgroundColor: theme.primary }}
            data-testid="create-campaign-btn">
            <Plus size={18} className="mr-1" /> New Campaign
          </Button>
        </div>
      </div>

      {/* Stats */}
      {memberStats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Card><CardContent className="p-4 text-center">
            <p className="text-sm text-gray-500">Total Members</p>
            <p className="text-2xl font-bold" style={{ color: theme.primary }}>{memberStats.totalMembers}</p>
          </CardContent></Card>
          <Card><CardContent className="p-4 text-center">
            <p className="text-sm text-gray-500">Avg Spend</p>
            <p className="text-2xl font-bold text-emerald-600">${memberStats.avgSpend}</p>
          </CardContent></Card>
          <Card><CardContent className="p-4 text-center">
            <p className="text-sm text-gray-500">Campaigns Sent</p>
            <p className="text-2xl font-bold text-blue-600">{campaigns.filter(c => c.status === 'sent').length}</p>
          </CardContent></Card>
          <Card><CardContent className="p-4 text-center">
            <p className="text-sm text-gray-500">Total Spent</p>
            <p className="text-2xl font-bold text-amber-600">${memberStats.totalSpent}</p>
          </CardContent></Card>
        </div>
      )}

      {/* Campaigns List */}
      <div className="space-y-3">
        {campaigns.map(c => (
          <Card key={c.id} data-testid={`campaign-${c.id}`}>
            <CardContent className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold">{c.name}</h3>
                    <Badge className={
                      c.status === 'recurring' ? 'bg-violet-100 text-violet-700'
                        : c.status === 'sent' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                    }>
                      {c.status === 'recurring' ? <><Repeat size={12} className="mr-0.5" /> Recurring</>
                        : c.status === 'sent' ? <><CheckCircle size={12} className="mr-0.5" /> Sent</>
                        : <><Edit2 size={12} className="mr-0.5" /> Draft</>}
                    </Badge>
                    {c.targetTier && <Badge variant="outline">{c.targetTier} tier</Badge>}
                    {c.segmentId && (
                      <Badge variant="outline" className="text-violet-700 border-violet-300">
                        <Filter size={10} className="mr-1" /> {segments.find(s => s.id === c.segmentId)?.name || 'Segment'}
                      </Badge>
                    )}
                    {!c.segmentId && c.segmentRules && (
                      <Badge variant="outline" className="text-violet-700 border-violet-300">
                        <Filter size={10} className="mr-1" /> Custom segment
                      </Badge>
                    )}
                    {c.voucherCode && (
                      <Badge className="bg-amber-100 text-amber-700" data-testid={`campaign-voucher-${c.id}`}>
                        <Ticket size={12} className="mr-1" /> {c.voucherCode}
                      </Badge>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mt-1">Subject: {c.subject}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    <Users size={12} className="inline mr-1" />{c.recipientCount} recipients
                    {c.sentAt && <> &middot; <Clock size={12} className="inline mx-1" />Sent {new Date(c.sentAt).toLocaleDateString()}</>}
                    {c.status === 'recurring' && (
                      <> &middot; every {c.recurring?.intervalDays || 7}d
                        {c.runCount > 0 && <> &middot; ran {c.runCount}× (last {new Date(c.lastRunAt).toLocaleDateString()})</>}
                        {c.nextRunAt && <> &middot; next {new Date(c.nextRunAt).toLocaleDateString()}</>}
                      </>
                    )}
                  </p>
                </div>
                <div className="flex gap-2">
                  {c.status === 'draft' && (
                    <Button size="sm" onClick={() => handleSend(c.id)} style={{ backgroundColor: theme.primary }}
                      data-testid={`send-${c.id}`}>
                      <Send size={14} className="mr-1" /> Send
                    </Button>
                  )}
                  {c.status === 'recurring' && (
                    <Button size="sm" variant="outline" onClick={() => handleRunNow(c.id)}
                      data-testid={`run-now-${c.id}`}>
                      <PlayCircle size={14} className="mr-1" /> Run now
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" className="text-red-500" onClick={() => handleDelete(c.id)}>
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
        {campaigns.length === 0 && (
          <Card className="border-dashed"><CardContent className="p-12 text-center">
            <Mail size={48} className="mx-auto mb-4 text-gray-300" />
            <h3 className="font-semibold text-gray-700">No campaigns yet</h3>
            <p className="text-sm text-gray-500 mt-1">Create your first email campaign to engage members</p>
          </CardContent></Card>
        )}
      </div>

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="create-campaign-dialog">
          <DialogHeader><DialogTitle>New Email Campaign</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">

            {/* Predrafted templates */}
            {templates.length > 0 && (
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-1.5 flex items-center gap-1">
                  <LayoutTemplate size={12} /> Start from a template
                </p>
                <div className="flex gap-1.5 overflow-x-auto pb-1" data-testid="campaign-templates">
                  {templates.map(t => (
                    <button key={t.key} onClick={() => applyTemplate(t)} data-testid={`template-${t.key}`}
                      className="shrink-0 text-xs px-2.5 py-1.5 rounded-full border hover:bg-amber-50 hover:border-amber-300 transition whitespace-nowrap">
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* AI draft-from-brief */}
            <div className="rounded-lg border border-violet-200 bg-violet-50/60 p-3 space-y-2">
              <p className="text-xs font-bold uppercase tracking-wider text-violet-700 flex items-center gap-1">
                <Sparkles size={12} /> AI draft
              </p>
              <div className="flex gap-2">
                <Input value={brief} onChange={e => setBrief(e.target.value)}
                  placeholder="e.g. promote our new summer menu to Gold members" className="text-sm" data-testid="campaign-brief" />
                <Button size="sm" onClick={handleAiDraft} disabled={drafting} className="bg-violet-600 hover:bg-violet-700 text-white shrink-0" data-testid="ai-draft-btn">
                  {drafting ? '…' : 'Generate'}
                </Button>
              </div>
              <p className="text-[11px] text-violet-600/80">Describe the offer in plain English, or just pick a template above — NUA writes the subject + body for you.</p>
            </div>

            <Input placeholder="Campaign name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="campaign-name" />
            <Input placeholder="Email subject line" value={form.subject} onChange={e => setForm({ ...form, subject: e.target.value })} data-testid="campaign-subject" />

            <div>
              <textarea className="w-full min-h-[140px] p-3 border rounded-md text-sm resize-none" placeholder="Email body (supports HTML)..."
                value={form.body} onChange={e => setForm({ ...form, body: e.target.value })} data-testid="campaign-body" />
              <Button size="sm" variant="outline" className="mt-1.5" onClick={handleImproveWording} disabled={improving || !form.body} data-testid="improve-wording-btn">
                <Wand2 size={14} className="mr-1" /> {improving ? 'Improving…' : 'Improve wording with AI'}
              </Button>
            </div>

            <div className="rounded-lg border p-3 space-y-2">
              <p className="text-xs font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1">
                <Filter size={12} /> Audience
              </p>
              <div className="flex gap-1">
                <Button type="button" size="sm" variant={audienceMode === 'tier' ? 'default' : 'outline'}
                  onClick={() => setAudienceMode('tier')} data-testid="audience-mode-tier">Loyalty tier</Button>
                <Button type="button" size="sm" variant={audienceMode === 'segment' ? 'default' : 'outline'}
                  onClick={() => setAudienceMode('segment')} data-testid="audience-mode-segment">Custom segment</Button>
              </div>

              {audienceMode === 'tier' ? (
                <select className="w-full p-2 border rounded-md text-sm" value={form.targetTier}
                  onChange={e => setForm({ ...form, targetTier: e.target.value })} data-testid="campaign-tier">
                  <option value="">All Customers</option>
                  <option value="Bronze">Bronze Only</option>
                  <option value="Silver">Silver Only</option>
                  <option value="Gold">Gold Only</option>
                  <option value="Platinum">Platinum Only</option>
                </select>
              ) : (
                <div className="space-y-2">
                  {segments.length > 0 && (
                    <div className="flex gap-1 items-center">
                      <select className="flex-1 p-2 border rounded-md text-sm" value={segmentId}
                        onChange={e => { setSegmentId(e.target.value); setEditingSegmentId(null); setSegmentPreview(null); }} data-testid="segment-select">
                        <option value="">— Build a new segment below —</option>
                        {segments.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                      {segmentId && (
                        <>
                          <Button type="button" size="icon" variant="ghost"
                            onClick={() => startEditingSegment(segments.find(s => s.id === segmentId))}
                            data-testid="segment-edit-btn" title="Edit this segment">
                            <Pencil size={14} />
                          </Button>
                          <Button type="button" size="icon" variant="ghost"
                            onClick={() => viewFullList(segments.find(s => s.id === segmentId))}
                            data-testid="segment-list-btn" title="View full matching list">
                            <List size={14} />
                          </Button>
                        </>
                      )}
                    </div>
                  )}
                  {(!segmentId || editingSegmentId) && (
                    <>
                      {editingSegmentId && (
                        <div className="flex items-center justify-between text-xs text-violet-700 bg-violet-50 rounded px-2 py-1">
                          <span>Editing "{segments.find(s => s.id === editingSegmentId)?.name}"</span>
                          <button type="button" onClick={cancelEditingSegment} data-testid="segment-cancel-edit">
                            <X size={12} />
                          </button>
                        </div>
                      )}
                      <div className="grid grid-cols-3 gap-2">
                        <Input type="number" placeholder="Min spend ($)" value={segmentRules.minSpend}
                          onChange={e => { setSegmentRules({ ...segmentRules, minSpend: e.target.value }); setSegmentPreview(null); }}
                          data-testid="segment-min-spend" />
                        <Input type="number" placeholder="Min visits" value={segmentRules.minVisits}
                          onChange={e => { setSegmentRules({ ...segmentRules, minVisits: e.target.value }); setSegmentPreview(null); }}
                          data-testid="segment-min-visits" />
                        <Input type="number" placeholder="Inactive for (days)" value={segmentRules.inactiveForDays}
                          onChange={e => { setSegmentRules({ ...segmentRules, inactiveForDays: e.target.value }); setSegmentPreview(null); }}
                          data-testid="segment-inactive-days" />
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <Input type="number" placeholder="Spent ≥ $ ..." value={segmentRules.minSpendInWindow}
                          onChange={e => { setSegmentRules({ ...segmentRules, minSpendInWindow: e.target.value }); setSegmentPreview(null); }}
                          data-testid="segment-min-spend-window" />
                        <Input type="number" placeholder="...in the last N days" value={segmentRules.spendInLastDays}
                          onChange={e => { setSegmentRules({ ...segmentRules, spendInLastDays: e.target.value }); setSegmentPreview(null); }}
                          data-testid="segment-spend-window-days" />
                      </div>
                      <p className="text-[11px] text-gray-400">
                        Min spend/visits above are lifetime-to-date. The spend window pair is the real "spent $X in the
                        last N days" rule — both fields are required together. "Inactive for" catches customers who
                        haven't visited in that many days (or never have).
                      </p>
                      <div className="flex gap-2 items-center flex-wrap">
                        <Button type="button" size="sm" variant="outline" onClick={previewCustomSegment} disabled={previewing}
                          data-testid="segment-preview-btn">
                          {previewing ? 'Counting…' : 'Preview audience'}
                        </Button>
                        {segmentPreview && (
                          <Badge variant="outline" data-testid="segment-preview-count">
                            <Users size={10} className="mr-1" /> {segmentPreview.count} match
                          </Badge>
                        )}
                        <Input placeholder="Save as… (name)" value={segmentName}
                          onChange={e => setSegmentName(e.target.value)} className="text-sm w-40" data-testid="segment-name" />
                        <Button type="button" size="sm" variant="outline" onClick={saveSegment} disabled={savingSegment}
                          data-testid="segment-save-btn">
                          <Save size={12} className="mr-1" /> {savingSegment ? 'Saving…' : editingSegmentId ? 'Update' : 'Save'}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Voucher code */}
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 space-y-2">
              <label className="flex items-center gap-2 text-sm font-semibold text-amber-800">
                <input type="checkbox" checked={form.voucherEnabled}
                  onChange={e => setForm({ ...form, voucherEnabled: e.target.checked })} data-testid="voucher-enable-toggle" />
                <Ticket size={14} /> Attach a redeemable voucher code to this email
              </label>
              {form.voucherEnabled && (
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <select className="p-2 border rounded-md text-sm" value={form.voucherValueType}
                    onChange={e => setForm({ ...form, voucherValueType: e.target.value })} data-testid="voucher-value-type">
                    <option value="percent">% off</option>
                    <option value="fixed">$ off</option>
                  </select>
                  <Input type="number" placeholder="Value" value={form.voucherValue}
                    onChange={e => setForm({ ...form, voucherValue: e.target.value })} data-testid="voucher-value" />
                  <Input type="number" placeholder="Expires in (days)" value={form.voucherExpiresInDays}
                    onChange={e => setForm({ ...form, voucherExpiresInDays: e.target.value })} data-testid="voucher-expires" />
                  <Input type="number" placeholder="Min spend ($, optional)" value={form.voucherMinSpend}
                    onChange={e => setForm({ ...form, voucherMinSpend: e.target.value })} data-testid="voucher-min-spend" />
                  <p className="col-span-2 text-[11px] text-amber-700/80">
                    One shared code goes out with every email in this campaign. Staff can type it, scan it, or ask NUA to check it — redemption happens right at POS like any other voucher.
                  </p>
                </div>
              )}
            </div>

            {/* Recurring */}
            <div className="rounded-lg border border-violet-200 bg-violet-50/60 p-3 space-y-2">
              <label className="flex items-center gap-2 text-sm font-semibold text-violet-800">
                <input type="checkbox" checked={form.recurringEnabled}
                  onChange={e => setForm({ ...form, recurringEnabled: e.target.checked })} data-testid="recurring-enable-toggle" />
                <Repeat size={14} /> Make this recurring
              </label>
              {form.recurringEnabled && (
                <div className="pt-1 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-violet-700">Every</span>
                    <Input type="number" className="w-20" value={form.recurringIntervalDays}
                      onChange={e => setForm({ ...form, recurringIntervalDays: e.target.value })} data-testid="recurring-interval-days" />
                    <span className="text-sm text-violet-700">days</span>
                  </div>
                  <p className="text-[11px] text-violet-700/80">
                    The audience (loyalty tier or segment above) is re-checked fresh on every run — a "hasn't visited in
                    30 days" segment picks up whoever's newly inactive each time, not a one-off snapshot. Starts
                    immediately and keeps running until deleted.
                  </p>
                </div>
              )}
            </div>

            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleCreate} disabled={creating}
              data-testid="confirm-create-campaign">
              {creating ? 'Creating…' : form.recurringEnabled ? 'Create Recurring Campaign' : 'Create Campaign'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Full segment customer list */}
      <Dialog open={!!fullListSegment} onOpenChange={o => { if (!o) { setFullListSegment(null); setFullList(null); } }}>
        <DialogContent className="max-w-md max-h-[80vh] overflow-y-auto" data-testid="segment-full-list-dialog">
          <DialogHeader><DialogTitle>{fullListSegment?.name} — {fullList ? fullList.count : '…'} matching</DialogTitle></DialogHeader>
          <div className="space-y-1">
            {loadingFullList && <p className="text-sm text-gray-400 text-center py-6">Loading…</p>}
            {fullList?.customers?.length === 0 && <p className="text-sm text-gray-400 text-center py-6">No customers match this segment.</p>}
            {fullList?.customers?.map(c => (
              <div key={c.id} className="flex justify-between items-center text-sm py-1.5 border-b last:border-0" data-testid={`segment-list-row-${c.id}`}>
                <div>
                  <p className="font-medium">{c.name}</p>
                  <p className="text-xs text-gray-500">{c.email}</p>
                </div>
                <p className="text-xs text-gray-500">${(c.totalSpent || 0).toFixed(0)} · {c.visits || 0} visits</p>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
