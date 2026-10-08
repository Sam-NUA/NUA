import React, { useEffect, useMemo, useState } from 'react';
import {
  Instagram, Facebook, Twitter, Share2, Plus, Sparkles, Trash2, Send, Calendar,
  Image as ImageIcon, RefreshCcw, Hash, Megaphone, AlertCircle,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { toast } from 'sonner';
import { useTheme } from '../contexts/ThemeContext';
import { socialAPI, productsAPI, promotionsAPI } from '../services/api';
import ImageLibrary from '../components/ImageLibrary';
import { SocialCalendar } from '../components/social/SocialCalendar';

const PLATFORM_ICON = {
  instagram: Instagram,
  facebook: Facebook,
  tiktok: Megaphone,        // lucide doesn't ship a TikTok glyph; using Megaphone
  x: Twitter,
  google_business: Share2,
};

const TONE_OPTIONS = [
  { v: 'warm',    label: 'Warm' },
  { v: 'bold',    label: 'Bold' },
  { v: 'playful', label: 'Playful' },
  { v: 'luxe',    label: 'Luxe' },
  { v: 'concise', label: 'Concise' },
];

const POST_TYPES = [
  { v: 'post',  label: 'Post' },
  { v: 'story', label: 'Story' },
  { v: 'reel',  label: 'Reel' },
];

const SocialMedia = () => {
  const { theme } = useTheme();
  const [accounts, setAccounts] = useState([]);
  const [posts, setPosts] = useState([]);
  const [platforms, setPlatforms] = useState([]);
  const [products, setProducts] = useState([]);
  const [promotions, setPromotions] = useState([]);

  // Composer state
  const [sourceType, setSourceType] = useState('product');
  const [sourceId, setSourceId] = useState('');
  const [tone, setTone] = useState('warm');
  const [postType, setPostType] = useState('post');
  const [selectedPlatforms, setSelectedPlatforms] = useState(['instagram']);
  const [customPrompt, setCustomPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [generations, setGenerations] = useState([]);   // [{platform, caption, hashtags, imageHint, imageAlt}]
  const [imageOverride, setImageOverride] = useState('');
  const [scheduledFor, setScheduledFor] = useState('');
  const [imageLibraryOpen, setImageLibraryOpen] = useState(false);

  // Account connect dialog
  const [connectOpen, setConnectOpen] = useState(false);
  const [connectPlatform, setConnectPlatform] = useState('instagram');
  const [connectHandle, setConnectHandle] = useState('');
  const [connectDisplayName, setConnectDisplayName] = useState('');

  // Tab: composer vs calendar
  const [view, setView] = useState('composer');

  const reload = async () => {
    try {
      const [acc, ps, pl, prod, promo] = await Promise.all([
        socialAPI.listAccounts(),
        socialAPI.listPosts(),
        socialAPI.listPlatforms(),
        productsAPI.getAll(),
        promotionsAPI.getAll(),
      ]);
      setAccounts(acc.data || []);
      setPosts(ps.data || []);
      setPlatforms(pl.data || []);
      setProducts(prod.data || []);
      setPromotions(promo.data || []);
    } catch {
      toast.error('Failed to load social media data');
    }
  };

  useEffect(() => { reload(); }, []);

  const connectedPlatformKeys = useMemo(() => new Set(accounts.map(a => a.platform)), [accounts]);

  const togglePlatform = (key) => {
    setSelectedPlatforms(prev => prev.includes(key) ? prev.filter(p => p !== key) : [...prev, key]);
  };

  const handleConnect = async () => {
    if (!connectHandle.trim()) return toast.error('Handle is required');
    try {
      await socialAPI.connectAccount({
        platform: connectPlatform,
        handle: connectHandle.trim(),
        displayName: connectDisplayName.trim() || undefined,
      });
      toast.success(`${connectPlatform} planning account added`);
      setConnectOpen(false); setConnectHandle(''); setConnectDisplayName('');
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to connect');
    }
  };

  const handleDisconnect = async (id) => {
    if (!window.confirm('Disconnect this account?')) return;
    try { await socialAPI.disconnectAccount(id); toast.success('Disconnected'); reload(); }
    catch { toast.error('Failed to disconnect'); }
  };

  const handleGenerate = async () => {
    if (sourceType !== 'special' && !sourceId) {
      return toast.error(`Pick a ${sourceType} first`);
    }
    if (selectedPlatforms.length === 0) {
      return toast.error('Select at least one platform');
    }
    setGenerating(true);
    try {
      const r = await socialAPI.aiGenerate({
        sourceType, sourceId: sourceId || undefined,
        tone, postType, platforms: selectedPlatforms,
        customPrompt: customPrompt || undefined,
      });
      setGenerations(r.data?.generations || []);
      // Default image: the product image if available
      const firstImg = (r.data?.generations || []).find(g => g.imageHint)?.imageHint;
      if (firstImg) setImageOverride(firstImg);
      const fellBack = (r.data?.generations || []).some(g => g.isFallback);
      if (fellBack) toast.warning('AI fell back to template — caption usable, but check tone.');
      else toast.success(`Generated ${r.data?.generations?.length || 0} draft(s)`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Generation failed');
    } finally { setGenerating(false); }
  };

  const saveAsDraft = async (gen, status = 'draft') => {
    try {
      await socialAPI.createPost({
        platform: gen.platform,
        postType,
        caption: gen.caption,
        hashtags: gen.hashtags || [],
        imageUrl: imageOverride || gen.imageHint || null,
        sourceType,
        sourceId: sourceId || undefined,
        scheduledFor: scheduledFor || undefined,
        status,
      });
      toast.success(`${gen.platform} ${status === 'scheduled' ? 'scheduled' : 'saved'}`);
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Save failed');
    }
  };

  const publishNow = async (gen) => {
    try {
      const r = await socialAPI.createPost({
        platform: gen.platform,
        postType,
        caption: gen.caption,
        hashtags: gen.hashtags || [],
        imageUrl: imageOverride || gen.imageHint || null,
        sourceType, sourceId: sourceId || undefined,
        status: 'draft',
      });
      await socialAPI.publishPost(r.data?.id);
      toast.success(`Published to ${gen.platform}`);
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Publish failed');
    }
  };

  const handleDeletePost = async (id) => {
    if (!window.confirm('Delete this post?')) return;
    try { await socialAPI.deletePost(id); toast.success('Deleted'); reload(); }
    catch { toast.error('Failed'); }
  };

  const platformConnected = (key) => connectedPlatformKeys.has(key);

  return (
    <div className="space-y-6" data-testid="social-media-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: theme.text }}>Social Media Marketing</h1>
          <p className="text-gray-500 mt-1">
            Generate posts, stories & reels from your products and promos — powered by AI, wired to your image library.
          </p>
        </div>
        <Button onClick={() => setConnectOpen(true)} style={{ backgroundColor: theme.primary }} data-testid="connect-account-btn">
          <Plus className="mr-2" size={18} /> Connect Account
        </Button>
      </div>

      {/* Tab toggle */}
      <div className="flex gap-2" data-testid="social-tabs">
        <Button
          variant={view === 'composer' ? 'default' : 'outline'}
          onClick={() => setView('composer')}
          style={{ backgroundColor: view === 'composer' ? theme.primary : 'transparent', color: view === 'composer' ? 'white' : theme.text }}
          data-testid="tab-composer"
        >
          <Sparkles className="mr-2" size={16} /> Composer
        </Button>
        <Button
          variant={view === 'calendar' ? 'default' : 'outline'}
          onClick={() => setView('calendar')}
          style={{ backgroundColor: view === 'calendar' ? theme.primary : 'transparent', color: view === 'calendar' ? 'white' : theme.text }}
          data-testid="tab-calendar"
        >
          <Calendar className="mr-2" size={16} /> Calendar
        </Button>
      </div>

      {/* Connected accounts row */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="accounts-row">
        {platforms.map(p => {
          const Icon = PLATFORM_ICON[p.key] || Share2;
          const connected = accounts.find(a => a.platform === p.key);
          return (
            <Card key={p.key} className={`border-2 ${connected ? '' : 'border-dashed opacity-60'}`} data-testid={`platform-card-${p.key}`}>
              <CardContent className="p-3 flex items-center gap-3">
                <Icon size={28} style={{ color: connected ? theme.primary : '#9ca3af' }} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold" style={{ color: theme.text }}>{p.label}</p>
                  {connected ? (
                    <p className="text-xs text-gray-500 truncate">@{connected.handle}</p>
                  ) : (
                    <p className="text-xs text-gray-400">Not connected</p>
                  )}
                </div>
                {connected && (
                  <button
                    onClick={() => handleDisconnect(connected.id)}
                    className="text-xs text-gray-400 hover:text-red-600"
                    data-testid={`disconnect-${p.key}`}
                    title="Disconnect"
                  ><Trash2 size={14} /></button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Mock OAuth banner */}
      {(
        <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800 flex items-center gap-2" data-testid="mock-oauth-banner">
          <AlertCircle size={14} />
          <span><strong>Content planning only.</strong> Save drafts and plan your calendar here. Automatic publishing is not available; scheduled posts will not be sent to social platforms.</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6" data-testid="composer-tab" style={{ display: view === 'composer' ? 'grid' : 'none' }}>
        {/* Composer */}
        <Card data-testid="composer-card">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Sparkles size={18} style={{ color: theme.primary }} />
              <h2 className="text-lg font-bold" style={{ color: theme.text }}>AI Composer</h2>
            </div>

            <div className="grid grid-cols-3 gap-1.5">
              {['product', 'promotion', 'special'].map(t => (
                <button key={t}
                  onClick={() => { setSourceType(t); setSourceId(''); setGenerations([]); }}
                  className={`px-2.5 py-1.5 text-xs rounded-md font-medium capitalize ${sourceType === t ? 'text-white' : 'bg-gray-100 text-gray-700'}`}
                  style={sourceType === t ? { background: theme.primary } : {}}
                  data-testid={`source-${t}`}>
                  {t}
                </button>
              ))}
            </div>

            {sourceType === 'product' && (
              <select className="w-full p-2 border rounded text-sm" value={sourceId}
                onChange={e => setSourceId(e.target.value)} data-testid="source-product-select">
                <option value="">— Pick a product —</option>
                {products.map(p => <option key={p.id} value={p.id}>{p.name} (${p.price})</option>)}
              </select>
            )}
            {sourceType === 'promotion' && (
              <select className="w-full p-2 border rounded text-sm" value={sourceId}
                onChange={e => setSourceId(e.target.value)} data-testid="source-promo-select">
                <option value="">— Pick a promotion —</option>
                {promotions.map(p => <option key={p.id} value={p.id}>{p.name} ({p.discount}% off)</option>)}
              </select>
            )}
            {sourceType === 'special' && (
              <textarea
                className="w-full p-2 border rounded text-sm min-h-[60px]"
                placeholder="Describe the special (e.g. 'Truffle pasta night, 7-9pm Friday')..."
                value={customPrompt}
                onChange={e => setCustomPrompt(e.target.value)}
                data-testid="special-prompt"
              />
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] uppercase tracking-widest text-gray-500 block mb-1">Tone</label>
                <select className="w-full p-2 border rounded text-sm" value={tone}
                  onChange={e => setTone(e.target.value)} data-testid="tone-select">
                  {TONE_OPTIONS.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-widest text-gray-500 block mb-1">Format</label>
                <div className="flex gap-1">
                  {POST_TYPES.map(o => (
                    <button key={o.v} onClick={() => setPostType(o.v)}
                      className={`flex-1 py-1.5 text-xs rounded font-medium ${postType === o.v ? 'text-white' : 'bg-gray-100 text-gray-600'}`}
                      style={postType === o.v ? { background: theme.primary } : {}}
                      data-testid={`format-${o.v}`}>
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-widest text-gray-500 block mb-1">Platforms</label>
              <div className="flex gap-1.5 flex-wrap">
                {platforms.map(p => {
                  const on = selectedPlatforms.includes(p.key);
                  const conn = platformConnected(p.key);
                  return (
                    <button key={p.key} onClick={() => togglePlatform(p.key)}
                      disabled={!conn}
                      className={`px-2.5 py-1 text-xs rounded-full font-medium border ${on ? 'text-white border-transparent' : 'bg-white text-gray-700'} ${!conn ? 'opacity-40 cursor-not-allowed' : ''}`}
                      style={on ? { background: theme.primary } : {}}
                      data-testid={`platform-pick-${p.key}`}
                      title={conn ? '' : 'Connect this account first'}>
                      {p.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-widest text-gray-500 block mb-1">Image (optional)</label>
              <div className="flex gap-2 items-center">
                {imageOverride
                  ? <img src={imageOverride} alt="" className="w-14 h-14 rounded object-cover border" />
                  : <span className="text-xs text-gray-400">Uses product image by default</span>}
                <Button type="button" variant="outline" size="sm" onClick={() => setImageLibraryOpen(true)} data-testid="pick-social-image">
                  <ImageIcon size={14} className="mr-1.5" /> Library
                </Button>
                {imageOverride && (
                  <button onClick={() => setImageOverride('')} className="text-xs text-gray-400 hover:text-red-600">Clear</button>
                )}
              </div>
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-widest text-gray-500 block mb-1">Schedule (optional)</label>
              <Input type="datetime-local" value={scheduledFor}
                onChange={e => setScheduledFor(e.target.value)} data-testid="schedule-input" />
            </div>

            <Button onClick={handleGenerate}
              disabled={generating || selectedPlatforms.length === 0}
              className="w-full text-white hover:opacity-90"
              style={{ background: theme.primary }}
              data-testid="generate-btn">
              {generating ? <><RefreshCcw size={14} className="mr-2 animate-spin" /> Generating…</> : <><Sparkles size={14} className="mr-2" /> Generate {selectedPlatforms.length} draft{selectedPlatforms.length !== 1 ? 's' : ''}</>}
            </Button>
          </CardContent>
        </Card>

        {/* Generations Preview */}
        <Card data-testid="generations-card">
          <CardContent className="p-4 space-y-3">
            <h2 className="text-lg font-bold" style={{ color: theme.text }}>Drafts</h2>
            {generations.length === 0 ? (
              <p className="text-sm text-gray-400 italic py-8 text-center" data-testid="generations-empty">
                Pick a source, configure tone + platforms, then click Generate.
              </p>
            ) : generations.map((g, idx) => {
              const Icon = PLATFORM_ICON[g.platform] || Share2;
              return (
                <div key={idx} className="border rounded-lg p-3 space-y-2 bg-gray-50/50" data-testid={`draft-${g.platform}`}>
                  <div className="flex items-center gap-2">
                    <Icon size={16} style={{ color: theme.primary }} />
                    <span className="text-xs font-bold uppercase tracking-wider">{g.platform}</span>
                    {g.isFallback && <span className="text-[10px] text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">FALLBACK</span>}
                    <span className="ml-auto text-[10px] text-gray-500">{postType}</span>
                  </div>
                  {(imageOverride || g.imageHint) && (
                    <img src={imageOverride || g.imageHint} alt={g.imageAlt || ''} className="w-full h-28 object-cover rounded" />
                  )}
                  <textarea
                    className="w-full text-sm p-2 border rounded resize-none min-h-[80px] bg-white"
                    value={g.caption}
                    onChange={(e) => {
                      const next = [...generations];
                      next[idx] = { ...g, caption: e.target.value };
                      setGenerations(next);
                    }}
                    data-testid={`caption-${g.platform}`}
                  />
                  <div className="flex flex-wrap gap-1">
                    {(g.hashtags || []).map((h, i) => (
                      <span key={i} className="text-[10px] px-2 py-0.5 rounded-full"
                        style={{ background: `${theme.secondary}20`, color: theme.secondary }}>
                        <Hash size={9} className="inline -mt-0.5" />{h.replace(/^#/, '')}
                      </span>
                    ))}
                  </div>
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => saveAsDraft(g, 'draft')} data-testid={`save-draft-${g.platform}`}>
                      Save draft
                    </Button>
                    {scheduledFor && (
                      <Button size="sm" variant="outline" onClick={() => saveAsDraft(g, 'scheduled')} data-testid={`schedule-${g.platform}`}>
                        <Calendar size={12} className="mr-1" /> Schedule
                      </Button>
                    )}
                    <Button size="sm" className="text-white hover:opacity-90"
                      style={{ background: theme.primary }}
                      disabled title="Publishing is not available yet"
                      onClick={() => publishNow(g)}
                      data-testid={`publish-${g.platform}`}>
                      <Send size={12} className="mr-1" /> Publish
                    </Button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>

      {/* Posts history */}
      <Card data-testid="posts-history-card" style={{ display: view === 'composer' ? 'block' : 'none' }}>
        <CardContent className="p-4">
          <h2 className="text-lg font-bold mb-3" style={{ color: theme.text }}>Recent posts</h2>
          {posts.length === 0 ? (
            <p className="text-sm text-gray-400 italic">No posts yet — generate and save a draft above.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-gray-500 bg-gray-50">
                  <tr>
                    <th className="px-2 py-2 text-left">Platform</th>
                    <th className="px-2 py-2 text-left">Type</th>
                    <th className="px-2 py-2 text-left">Caption</th>
                    <th className="px-2 py-2 text-center">Status</th>
                    <th className="px-2 py-2 text-left">When</th>
                    <th className="px-2 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {posts.map(p => {
                    const Icon = PLATFORM_ICON[p.platform] || Share2;
                    const dateStr = p.publishedAt || p.scheduledFor || p.createdAt;
                    return (
                      <tr key={p.id} className="border-t" data-testid={`post-row-${p.id}`}>
                        <td className="px-2 py-2"><Icon size={14} style={{ color: theme.primary }} /> {p.platform}</td>
                        <td className="px-2 py-2 capitalize text-xs">{p.postType}</td>
                        <td className="px-2 py-2 text-xs max-w-md truncate">{p.caption}</td>
                        <td className="px-2 py-2 text-center">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                            p.status === 'published' ? 'bg-emerald-100 text-emerald-700'
                            : p.status === 'scheduled' ? 'bg-amber-100 text-amber-700'
                            : p.status === 'failed' ? 'bg-red-100 text-red-700'
                            : 'bg-gray-100 text-gray-600'
                          }`}>
                            {p.status}
                          </span>
                        </td>
                        <td className="px-2 py-2 text-xs text-gray-500">
                          {dateStr ? new Date(dateStr).toLocaleString() : '—'}
                        </td>
                        <td className="px-2 py-2 text-right">
                          {p.status !== 'published' && (
                            <Button size="sm" variant="outline" className="mr-1" disabled title="Publishing is not available yet" onClick={async () => {
                              try { await socialAPI.publishPost(p.id); toast.success('Published'); reload(); }
                              catch { toast.error('Failed'); }
                            }} data-testid={`publish-row-${p.id}`}><Send size={12} /></Button>
                          )}
                          <Button size="sm" variant="ghost" className="text-red-500" onClick={() => handleDeletePost(p.id)} data-testid={`delete-row-${p.id}`}><Trash2 size={12} /></Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Calendar view */}
      {view === 'calendar' && (
        <SocialCalendar
          theme={theme}
          posts={posts}
          accounts={accounts}
          onReload={reload}
        />
      )}

      {/* Connect account dialog */}
      <Dialog open={connectOpen} onOpenChange={setConnectOpen}>
        <DialogContent className="max-w-sm" data-testid="connect-dialog">
          <DialogHeader><DialogTitle>Connect Social Account</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <select className="w-full p-2 border rounded text-sm" value={connectPlatform}
              onChange={e => setConnectPlatform(e.target.value)} data-testid="connect-platform-select">
              {platforms.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
            <Input placeholder="Handle (e.g. nua_eatery)" value={connectHandle}
              onChange={e => setConnectHandle(e.target.value)} data-testid="connect-handle-input" />
            <Input placeholder="Display name (optional)" value={connectDisplayName}
              onChange={e => setConnectDisplayName(e.target.value)} data-testid="connect-displayname-input" />
            <p className="text-[10px] text-gray-400 leading-relaxed">
              <AlertCircle size={10} className="inline mr-1" />
              This adds a <strong>planning account</strong>. It does not connect to your social platform or enable publishing. Provider integration and account authorisation are still required.
            </p>
            <Button onClick={handleConnect} className="w-full text-white" style={{ background: theme.primary }}
              data-testid="connect-submit">
              Connect (Mock OAuth)
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <ImageLibrary
        open={imageLibraryOpen}
        onClose={() => setImageLibraryOpen(false)}
        onPick={(dataUrl) => setImageOverride(dataUrl)}
        themeColor={theme.primary}
      />
    </div>
  );
};

export default SocialMedia;
