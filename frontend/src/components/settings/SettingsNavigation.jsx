import React, { useState } from 'react';
import { Search, ChevronRight, LayoutGrid } from 'lucide-react';

const groups = [
  { label: 'Venue', items: [
    ['business', 'Business & hours', 'Business details, tax IDs and opening hours', 'abn address phone google'],
    ['locations', 'Locations', 'Venue addresses, contact details and local hours', 'branches stores'],
  ] },
  { label: 'POS & service', items: [
    ['pos-layout', 'POS layout', 'Arrange the selling screen for your team', 'tiles products buttons'],
    ['theme', 'Appearance', 'Colours, branding and screen preferences', 'theme logo'],
    ['receipt', 'Receipts', 'Receipt branding, QR codes and messages', 'receipt logo paper'],
    ['coursing', 'Courses & firing', 'Control when courses reach the kitchen', 'food kitchen pacing'],
    ['session', 'Screen lock', 'Choose when an inactive POS signs out', 'timeout pin session auto logout', ['owner', 'manager']],
    ['surcharge', 'Surcharges', 'Weekend and public holiday charges', 'fees pricing', ['owner']],
    ['gratuity', 'Automatic gratuity', 'Service charges based on group size', 'tips auto gratuity covers', ['owner']],
    ['training', 'Training mode', 'Practise using the POS', 'practice demo'],
  ] },
  { label: 'Team & access', items: [
    ['users', 'Staff & PINs', 'Team members, login PINs and pay details', 'owner employee password roles'],
    ['permissions', 'Permissions', 'Choose what each team member can access', 'roles access staff', ['owner']],
    ['security', 'Account & security', 'Password, recovery and two-factor sign-in', 'login password reset mfa 2fa trusted devices'],
  ] },
  { label: 'Customers & reports', items: [
    ['targets', 'Targets & offers', 'Daily goals and customer birthday offers', 'sales labour labor refund wallet birthday', ['owner', 'manager']],
    ['wallet', 'Wallet passes', 'Set up digital customer wallet passes', 'apple google loyalty credentials'],
    ['reports', 'Scheduled reports', 'Report types, delivery times and recipients', 'automated email daily', ['owner']],
  ] },
  { label: 'Devices & printing', items: [
    ['hardware', 'Printers & scanners', 'Manage the devices used at your venue', 'hardware barcode equipment'],
    ['print-routing', 'Print routing & health', 'Send orders to the right printer and check its status', 'kitchen receipt paper offline'],
  ] },
  { label: 'Maintenance', items: [
    ['ops', 'System health', 'Check service status and recent errors', 'diagnostics logs monitoring'],
    ['backup', 'Backup & restore', 'Backup tools and recovery checks', 'download data restore'],
  ] },
];

export default function SettingsNavigation({ activeTab, onSelect, role, children }) {
  const [query, setQuery] = useState('');
  const available = groups.map(group => ({ ...group, items: group.items.filter(item => !item[4] || item[4].includes(role)) })).filter(group => group.items.length);
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const filtered = available.map(group => ({ ...group, items: group.items.filter(item => terms.every(term => `${group.label} ${item.slice(0, 4).join(' ')}`.toLowerCase().includes(term))) })).filter(group => group.items.length);
  const selected = available.flatMap(group => group.items).find(item => item[0] === activeTab);
  const select = id => { onSelect(id); setQuery(''); };
  const searching = terms.length > 0;
  const count = filtered.reduce((total, group) => total + group.items.length, 0);
  return (
    <div className="space-y-5 min-w-0">
      <div className="max-w-xl">
        <label htmlFor="settings-search" className="block text-sm font-medium text-gray-700 mb-2">Find a setting</label>
        <div className="relative">
          <Search size={18} className="absolute left-3 top-3 text-gray-400" aria-hidden="true" />
          <input id="settings-search" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search PINs, printers, receipts…" className="w-full rounded-xl border border-gray-300 bg-white py-2.5 pl-10 pr-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#750D28]" />
        </div>
      </div>
      <div className="lg:hidden">
        <label htmlFor="settings-section" className="block text-sm font-medium text-gray-700 mb-2">Go to section</label>
        <select id="settings-section" value={activeTab} onChange={event => select(event.target.value)} className="w-full rounded-xl border border-gray-300 bg-white p-3 text-sm text-gray-900">
          <option value="overview">All settings</option>
          {available.map(group => <optgroup key={group.label} label={group.label}>{group.items.map(item => <option key={item[0]} value={item[0]}>{item[1]}</option>)}</optgroup>)}
        </select>
      </div>
      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)] items-start">
        <nav aria-label="Settings sections" className="hidden lg:block rounded-2xl border border-gray-200 bg-white p-3">
          <button type="button" onClick={() => select('overview')} aria-current={activeTab === 'overview' ? 'page' : undefined} className="w-full flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-semibold text-[#750D28] hover:bg-[#F7F3EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#750D28]">
            <LayoutGrid size={16} aria-hidden="true" />All settings
          </button>
          {available.map(group => <div key={group.label} className="mt-4">
            <p className="px-3 mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">{group.label}</p>
            {group.items.map(item => <button key={item[0]} type="button" data-testid={`settings-tab-${item[0]}`} onClick={() => select(item[0])} aria-current={activeTab === item[0] ? 'page' : undefined} className={`w-full text-left rounded-lg px-3 py-2.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#750D28] ${activeTab === item[0] ? 'bg-[#F7F3EF] text-[#750D28] font-semibold' : 'text-gray-700 hover:bg-gray-50'}`}>{item[1]}</button>)}
          </div>)}
        </nav>
        <div className="min-w-0 space-y-5">
          {(activeTab === 'overview' || searching) ? <>
            <div>
              <h2 className="text-xl font-semibold text-gray-900">{searching ? 'Search results' : 'Everything in its place'}</h2>
              <p className="text-sm text-gray-500 mt-1" role="status">{searching ? `${count} matching ${count === 1 ? 'setting' : 'settings'}` : 'Choose a section to view and update its settings.'}</p>
            </div>
            {count === 0 && <div className="rounded-xl border border-dashed p-6 text-sm text-gray-600">No settings found. Try “staff”, “receipt” or “printer”. <button type="button" className="underline font-medium text-[#750D28]" onClick={() => setQuery('')}>Clear search</button></div>}
            <div className="grid gap-4 xl:grid-cols-2" data-testid="settings-overview">
              {filtered.map(group => <section key={group.label} className="rounded-2xl border border-gray-200 bg-white p-4">
                <h3 className="text-sm font-semibold text-[#750D28] px-2 mb-2">{group.label}</h3>
                {group.items.map(item => <button type="button" key={item[0]} data-testid={`settings-open-${item[0]}`} onClick={() => select(item[0])} className="w-full flex items-center gap-3 rounded-xl p-3 text-left hover:bg-[#F7F3EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#750D28]">
                  <span className="flex-1 min-w-0"><span className="block font-medium text-sm text-gray-900">{item[1]}</span><span className="block text-xs leading-relaxed text-gray-500 mt-1">{item[2]}</span></span><ChevronRight size={16} className="shrink-0 text-gray-400" aria-hidden="true" />
                </button>)}
              </section>)}
            </div>
          </> : <div className="mb-5">
            <button type="button" onClick={() => select('overview')} className="text-sm text-[#750D28] underline underline-offset-4 mb-3">Back to all settings</button>
            <h2 className="text-xl font-semibold text-gray-900">{selected?.[1]}</h2>
            <p className="text-sm text-gray-500 mt-1">{selected?.[2]}. Changes are saved using the buttons in this section.</p>
          </div>}
          {/* Keep forms mounted while searching so in-progress edits are preserved. */}
          <div hidden={searching || activeTab === 'overview'} className="min-w-0 space-y-4 overflow-x-auto" data-testid="settings-content">{children}</div>
        </div>
      </div>
    </div>
  );
}
