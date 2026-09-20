import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { productsAPI } from '../services/api';
import { Search, CornerDownLeft, Package } from 'lucide-react';

/**
 * Global command bar — Ctrl/⌘+K anywhere. Type what you want:
 * a page ("roster", "end of day"), or a product name (jumps to Item Library).
 * Faster than the sidebar for anyone who already knows what they're after.
 * See VoiceCommandButton.jsx for the always-visible mic equivalent of this
 * (same idea, spoken instead of typed).
 */
const DESTINATIONS = [
  { label: 'Today', path: '/today', keywords: 'home overview pulse alerts briefing vips 86', roles: ['owner', 'manager', 'cashier', 'kitchen'] },
  { label: 'POS Terminal', path: '/pos', keywords: 'sell checkout order cart', roles: ['owner', 'manager', 'cashier'] },
  { label: 'Kitchen Display', path: '/kitchen', keywords: 'kds tickets', roles: ['owner', 'manager', 'kitchen'] },
  { label: 'Floor Plan', path: '/floor-plan', keywords: 'tables seating', roles: ['owner', 'manager', 'cashier'] },
  { label: 'Bookings', path: '/reservations', keywords: 'reservations tables tonight', roles: ['owner', 'manager', 'cashier'] },
  { label: 'Waitlist', path: '/waitlist', keywords: 'queue walk-in', roles: ['owner', 'manager', 'cashier'] },
  { label: 'Item Library', path: '/products', keywords: 'products menu items prices', roles: ['owner', 'manager', 'cashier'] },
  { label: 'Categories', path: '/categories', keywords: 'menu groups', roles: ['owner', 'manager'] },
  { label: 'Modifiers', path: '/modifiers', keywords: 'options extras', roles: ['owner', 'manager'] },
  { label: 'Inventory', path: '/inventory', keywords: 'stock levels reorder', roles: ['owner', 'manager'] },
  { label: 'Measured Stock', path: '/measured-stock', keywords: 'bottles kegs pours', roles: ['owner', 'manager'] },
  { label: 'Purchase Orders', path: '/purchase-orders', keywords: 'suppliers ordering', roles: ['owner', 'manager'] },
  { label: 'Customers', path: '/customers', keywords: 'guests crm profiles wallet', roles: ['owner', 'manager', 'cashier'] },
  { label: 'Vouchers', path: '/vouchers', keywords: 'discount codes offers', roles: ['owner', 'manager'] },
  { label: 'Marketing', path: '/marketing', keywords: 'promotions email loyalty social', roles: ['owner', 'manager'] },
  { label: 'Staff', path: '/staff', keywords: 'team employees pins', roles: ['owner', 'manager'] },
  { label: 'Roster & Payrun', path: '/staff-roster', keywords: 'shifts schedule payroll', roles: ['owner', 'manager'] },
  { label: 'Tip Management', path: '/tip-management', keywords: 'tips pooling', roles: ['owner', 'manager'] },
  { label: 'Dashboard (classic)', path: '/dashboard', keywords: 'charts kpis stats', roles: ['owner', 'manager'] },
  { label: 'Menu Engineering', path: '/menu-engineering', keywords: 'stars dogs margins matrix', roles: ['owner', 'manager'] },
  { label: 'Forecasting', path: '/forecasting', keywords: 'demand predict', roles: ['owner', 'manager'] },
  { label: 'Finance Suite', path: '/finance', keywords: 'ledger journal accounts money', roles: ['owner'] },
  { label: 'Transactions', path: '/accounting', keywords: 'sales refunds history', roles: ['owner'] },
  { label: 'BAS / GST', path: '/bas-gst', keywords: 'tax ato report', roles: ['owner'] },
  { label: 'Payroll', path: '/payroll', keywords: 'wages pay staff', roles: ['owner'] },
  { label: 'Super', path: '/super', keywords: 'superannuation', roles: ['owner'] },
  { label: 'End of Day', path: '/end-of-day', keywords: 'close till z-report settle', roles: ['owner', 'manager'] },
  { label: 'Online Orders', path: '/online-orders', keywords: 'delivery pickup web', roles: ['owner', 'manager'] },
  { label: 'Gift Cards', path: '/gift-cards', keywords: 'sell voucher card barcode reload stop resend', roles: ['owner', 'manager', 'cashier'] },
  { label: 'NUA AI', path: '/ash', keywords: 'ai assistant intelligence brain ash', roles: ['owner', 'manager'] },
  { label: 'Automation Brain', path: '/automation-triggers', keywords: 'rules triggers automation', roles: ['owner', 'manager'] },
  { label: 'Approvals', path: '/approvals', keywords: 'pending requests', roles: ['owner', 'manager'] },
  { label: 'Audit Log', path: '/audit', keywords: 'history changes who', roles: ['owner'] },
  { label: 'Integrations', path: '/integrations', keywords: 'xero deliveroo connect api', roles: ['owner'] },
  { label: 'Settings', path: '/settings', keywords: 'configure theme receipt tax', roles: ['owner', 'manager'] },
];

export default function CommandBar() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [products, setProducts] = useState(null); // lazy-loaded on first open
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();
  const { user } = useAuth();
  const role = user?.role || 'cashier';

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(v => !v);
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (!open) { setQuery(''); setHighlight(0); return; }
    setTimeout(() => inputRef.current?.focus(), 30);
    if (products === null) {
      productsAPI.getAll().then(r => setProducts(r.data || [])).catch(() => setProducts([]));
    }
  }, [open]); // eslint-disable-line

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const allowed = DESTINATIONS.filter(d => role === 'owner' || d.roles.includes(role));
    if (!q) return allowed.slice(0, 8).map(d => ({ type: 'page', ...d }));
    const pages = allowed
      .filter(d => d.label.toLowerCase().includes(q) || d.keywords.includes(q))
      .slice(0, 6)
      .map(d => ({ type: 'page', ...d }));
    const prods = (products || [])
      .filter(p => (p.name || '').toLowerCase().includes(q) || (p.category || '').toLowerCase().includes(q))
      .slice(0, 5)
      .map(p => ({ type: 'product', label: p.name, sub: `$${Number(p.price || 0).toFixed(2)} · ${p.category || ''}`, path: '/products' }));
    return [...pages, ...prods];
  }, [query, products, role]);

  const go = useCallback((item) => {
    if (!item) return;
    setOpen(false);
    navigate(item.path);
  }, [navigate]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] bg-black/30 backdrop-blur-[2px] flex items-start justify-center pt-[15vh]"
      onClick={() => setOpen(false)} data-testid="command-bar-overlay">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-2xl border overflow-hidden"
        onClick={e => e.stopPropagation()} data-testid="command-bar">
        <div className="flex items-center gap-2 px-4 py-3 border-b">
          <Search size={16} className="text-gray-400" />
          <input ref={inputRef} value={query}
            onChange={e => { setQuery(e.target.value); setHighlight(0); }}
            onKeyDown={e => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setHighlight(h => Math.min(h + 1, results.length - 1)); }
              if (e.key === 'ArrowUp') { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)); }
              if (e.key === 'Enter') { e.preventDefault(); go(results[highlight]); }
            }}
            placeholder="Jump to a page or find an item…"
            className="flex-1 outline-none text-sm"
            data-testid="command-bar-input" />
          <kbd className="text-[10px] text-gray-400 border rounded px-1.5 py-0.5">esc</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-1">
          {results.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-6">No matches for “{query}”</p>
          )}
          {results.map((r, i) => (
            <button key={`${r.type}-${r.path}-${r.label}`}
              onClick={() => go(r)} onMouseEnter={() => setHighlight(i)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm ${i === highlight ? 'bg-gray-100' : ''}`}
              data-testid={`command-result-${i}`}>
              {r.type === 'product'
                ? <Package size={15} className="text-gray-400 flex-shrink-0" />
                : <Search size={15} className="text-gray-400 flex-shrink-0" />}
              <span className="flex-1">
                <span className="font-medium text-gray-800">{r.label}</span>
                {r.sub && <span className="ml-2 text-xs text-gray-400">{r.sub}</span>}
              </span>
              {i === highlight && <CornerDownLeft size={13} className="text-gray-400" />}
            </button>
          ))}
        </div>
        <div className="px-4 py-2 border-t bg-gray-50 text-[10px] text-gray-400 flex items-center gap-3">
          <span>↑↓ navigate</span><span>↵ open</span><span className="ml-auto">Ctrl/⌘+K to toggle</span>
        </div>
      </div>
    </div>
  );
}
