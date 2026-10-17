import React, { useEffect, useState } from 'react';
import { Fingerprint, RefreshCw, Search, User, Award, CalendarCheck, Ticket, Save, Database } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Switch } from '../components/ui/switch';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { identityAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

const ADDONS = [
  { flag: 'bookings_guests.enabled', label: 'Bookings & Guests', desc: 'Notes, tags, allergies, and seating preference per customer.', icon: CalendarCheck },
  { flag: 'loyalty.enabled', label: 'Loyalty', desc: 'Points balance and tier, layered onto the base customer record.', icon: Award },
  { flag: 'punch_card.enabled', label: 'Punch Card', desc: 'A simple visit-count reward, independent of the points-based loyalty program.', icon: Ticket },
  { flag: 'marketing.enabled', label: 'Marketing Segments', desc: 'Lets campaigns build segments filtered by loyalty tier or guest tags.', icon: Fingerprint },
];

/**
 * Every checkout and every booking already writes into the customer
 * identity layer (create_or_match / record_touchpoint), tagging each
 * customer with whichever add-ons are enabled below — but until now there
 * was no screen anywhere that showed this data existed, let alone let an
 * owner turn an add-on on or off. This is that screen.
 */
export default function IdentitySettings() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const isOwner = user?.role === 'owner';

  const [flags, setFlags] = useState(null);
  const [savingFlags, setSavingFlags] = useState(false);
  const [search, setSearch] = useState('');
  const [customers, setCustomers] = useState([]);
  const [loadingCustomers, setLoadingCustomers] = useState(false);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [migrating, setMigrating] = useState(false);
  const [migrateResult, setMigrateResult] = useState(null);

  const loadEntitlements = () => {
    identityAPI.getEntitlements().then(r => setFlags(r.data.feature_flags || {})).catch(() => toast.error('Failed to load entitlements'));
  };
  useEffect(loadEntitlements, []);

  const loadCustomers = (q) => {
    setLoadingCustomers(true);
    identityAPI.search(q).then(r => setCustomers(r.data || [])).catch(() => {}).finally(() => setLoadingCustomers(false));
  };
  useEffect(() => { loadCustomers(''); }, []);

  const toggleFlag = (flag) => setFlags(prev => ({ ...prev, [flag]: !prev[flag] }));

  const saveFlags = async () => {
    setSavingFlags(true);
    try {
      const addons_enabled = ADDONS.filter(a => flags[a.flag]).map(a => a.flag.replace('.enabled', '').replace('_', '-'));
      await identityAPI.setEntitlements({ addons_enabled, feature_flags: flags });
      toast.success('Add-ons updated');
    } catch {
      toast.error('Failed to save');
    } finally {
      setSavingFlags(false);
    }
  };

  const openCustomer = async (c) => {
    setSelected(c);
    setDetail(null);
    try {
      const r = await identityAPI.getCustomer(c.id);
      setDetail(r.data);
    } catch {
      toast.error('Failed to load customer');
    }
  };

  const runMigration = async () => {
    if (!await DialogService.confirm('Migrate legacy combined Loyalty & CRM data into the identity layer? Safe to re-run — already-migrated rows are enriched, not duplicated.')) return;
    setMigrating(true);
    try {
      const r = await identityAPI.migrateLegacyCrm();
      setMigrateResult(r.data);
      toast.success(`Migrated ${r.data.migrated}, skipped ${r.data.skipped}`);
      loadCustomers(search);
    } catch {
      toast.error('Migration failed');
    } finally {
      setMigrating(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="identity-settings-page">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
          <Fingerprint size={22} /> Identity &amp; Add-Ons
        </h1>
        <p className="text-sm text-gray-500">The base customer record every checkout and booking writes to, and which add-ons enrich it.</p>
      </div>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Add-ons</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {!flags && <p className="text-sm text-gray-400">Loading…</p>}
          {flags && ADDONS.map(a => {
            const Icon = a.icon;
            return (
              <div key={a.flag} className="flex items-center justify-between p-3 rounded-lg border" data-testid={`addon-${a.flag}`}>
                <div className="flex items-start gap-3">
                  <Icon size={18} className="mt-0.5 text-gray-400" />
                  <div>
                    <p className="text-sm font-medium">{a.label}</p>
                    <p className="text-xs text-gray-500">{a.desc}</p>
                  </div>
                </div>
                <Switch checked={!!flags[a.flag]} onCheckedChange={() => toggleFlag(a.flag)}
                  disabled={!isOwner} data-testid={`addon-switch-${a.flag}`} />
              </div>
            );
          })}
          {flags && (
            <Button onClick={saveFlags} disabled={savingFlags || !isOwner} data-testid="save-addons-btn"
              style={{ backgroundColor: theme.primary }}>
              <Save size={14} className="mr-1.5" /> {savingFlags ? 'Saving…' : 'Save'}
            </Button>
          )}
          {!isOwner && <p className="text-xs text-gray-400">Owner only — ask an owner to change add-ons.</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-sm">Identity records</CardTitle>
          {isOwner && (
            <Button size="sm" variant="outline" onClick={runMigration} disabled={migrating} data-testid="migrate-legacy-btn">
              <Database size={13} className={`mr-1.5 ${migrating ? 'animate-pulse' : ''}`} /> Migrate legacy CRM data
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {migrateResult && (
            <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-2" data-testid="migrate-result">
              Migrated {migrateResult.migrated}, skipped {migrateResult.skipped} (already matched or no phone/email).
            </p>
          )}
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <Input className="pl-8" placeholder="Search by name, email, or phone…" value={search}
              onChange={e => { setSearch(e.target.value); loadCustomers(e.target.value); }} data-testid="identity-search" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1 max-h-96 overflow-y-auto" data-testid="identity-list">
              {loadingCustomers && <p className="text-xs text-gray-400 p-2">Loading…</p>}
              {!loadingCustomers && customers.length === 0 && (
                <p className="text-xs text-gray-400 p-2">No identity records yet — they're created automatically at checkout or booking.</p>
              )}
              {customers.map(c => (
                <button key={c.id} onClick={() => openCustomer(c)}
                  className={`w-full text-left p-2.5 rounded-lg border text-sm hover:bg-gray-50 transition ${selected?.id === c.id ? 'ring-2' : ''}`}
                  style={selected?.id === c.id ? { borderColor: theme.primary } : {}}
                  data-testid={`identity-row-${c.id}`}>
                  <p className="font-medium flex items-center gap-1.5"><User size={12} /> {c.name || 'Unnamed'}</p>
                  <p className="text-xs text-gray-500">{c.phone || c.email || '—'} · {c.visit_count || 0} visits · {c.source}</p>
                </button>
              ))}
            </div>
            <div className="border rounded-lg p-3 min-h-[10rem]" data-testid="identity-detail">
              {!selected && <p className="text-xs text-gray-400">Select a record to see its base identity plus whichever add-ons are enabled.</p>}
              {selected && !detail && <p className="text-xs text-gray-400">Loading…</p>}
              {detail && (
                <div className="space-y-2 text-sm">
                  <p className="font-semibold">{detail.customer?.name}</p>
                  <p className="text-xs text-gray-500">{detail.customer?.phone} {detail.customer?.email ? `· ${detail.customer.email}` : ''}</p>
                  <p className="text-xs text-gray-400">Source: {detail.customer?.source} · Last seen {detail.customer?.last_seen_at?.slice(0, 10)}</p>
                  {detail.guest_profile !== undefined && (
                    <div className="pt-2 border-t">
                      <Badge variant="outline" className="text-[10px] mb-1"><CalendarCheck size={10} className="mr-1" />Guest Profile</Badge>
                      <p className="text-xs text-gray-500">{detail.guest_profile ? (detail.guest_profile.tags || []).join(', ') || 'No tags' : 'Not enrolled yet'}</p>
                    </div>
                  )}
                  {detail.loyalty_account !== undefined && (
                    <div className="pt-2 border-t">
                      <Badge variant="outline" className="text-[10px] mb-1"><Award size={10} className="mr-1" />Loyalty</Badge>
                      <p className="text-xs text-gray-500">{detail.loyalty_account ? `${detail.loyalty_account.points_balance} pts · ${detail.loyalty_account.tier}` : 'Not enrolled yet'}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
