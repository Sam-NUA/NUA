import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { useBusiness } from '../contexts/BusinessContext';
import { getMenuLabels } from '../lib/businessVertical';
import { v15API } from '../services/api';
import {
  LayoutDashboard, ShoppingCart, Package, Users, Warehouse, Calculator,
  Settings, Utensils, ChefHat, BarChart3, Zap, Award, TrendingUp,
  FlaskConical, Sunrise, Brain, Plug, Users2, LogOut, Mail, ClipboardList,
  Trophy, Printer, PieChart, MoreHorizontal, X, FileText, DollarSign, Tag,
  Link2, Ban, Receipt, Calendar, MapPin, Clock, Sparkles, BookOpen, Shield, ShoppingBag,
  ShieldAlert, AlertTriangle, Flame, ArrowLeftRight, Key, Sun, Moon
} from 'lucide-react';
import Logo from './brand/Logo';
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogClose } from './ui/dialog';
import { Input } from './ui/input';

// Role-default quick actions (left → right) on the bottom dock.
// 4 most-common items per role, then "More" splash button. `kitchen` and
// `barista` roles only exist at hospitality businesses in practice, so
// their bars are left as-is; owner/manager/cashier exist at every
// vertical and get a non-restaurant-specific bar swapped in below.
export const QUICK_ACTIONS = {
  owner: [
    { path: '/today', label: 'Today', icon: Sunrise },
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/reservations', label: 'Bookings', icon: Utensils },
    { path: '/products', label: 'Items', icon: Package },
  ],
  manager: [
    { path: '/today', label: 'Today', icon: Sunrise },
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/kitchen', label: 'Kitchen', icon: ChefHat },
    { path: '/staff-roster', label: 'Roster', icon: ClipboardList },
  ],
  cashier: [
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/reservations', label: 'Bookings', icon: Utensils },
    { path: '/customers', label: 'Customers', icon: Users },
    { path: '/loyalty', label: 'Loyalty', icon: Award },
  ],
  kitchen: [
    { path: '/kitchen', label: 'Kitchen', icon: ChefHat },
    { path: '/today', label: 'Today', icon: Sunrise },
    { path: '/inventory', label: 'Inventory', icon: Warehouse },
    { path: '/ai-pantry', label: 'AI Pantry', icon: Brain },
  ],
  barista: [
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/kitchen', label: 'Drinks', icon: ChefHat },
    { path: '/customers', label: 'Customers', icon: Users },
    { path: '/loyalty', label: 'Loyalty', icon: Award },
  ],
};

// Non-hospitality quick-bar overrides: today's Bookings/Kitchen pages are
// restaurant-table and kitchen-docket specific (Phase 4 of the vertical
// roadmap builds a real appointment/resource booking system) — until then,
// swap those slots for something that works everywhere.
const QUICK_ACTIONS_NON_HOSPITALITY = {
  owner: [
    { path: '/today', label: 'Today', icon: Sunrise },
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/customers', label: 'Customers', icon: Users },
    { path: '/products', label: 'Items', icon: Package },
  ],
  manager: [
    { path: '/today', label: 'Today', icon: Sunrise },
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/inventory', label: 'Inventory', icon: Warehouse },
    { path: '/staff-roster', label: 'Roster', icon: ClipboardList },
  ],
  cashier: [
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/products', label: 'Items', icon: Package },
    { path: '/customers', label: 'Customers', icon: Users },
    { path: '/loyalty', label: 'Loyalty', icon: Award },
  ],
};

// Beauty/services gets its own quick bar rather than falling back to
// QUICK_ACTIONS_NON_HOSPITALITY's generic "Customers" slot — a salon's
// day revolves around who's booked in next, the same way a restaurant's
// revolves around Bookings, so Appointments earns the same prominent spot.
const QUICK_ACTIONS_BEAUTY_SERVICES = {
  owner: [
    { path: '/today', label: 'Today', icon: Sunrise },
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/appointments', label: 'Appointments', icon: Calendar },
    { path: '/products', label: 'Items', icon: Package },
  ],
  manager: [
    { path: '/today', label: 'Today', icon: Sunrise },
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/appointments', label: 'Appointments', icon: Calendar },
    { path: '/staff-roster', label: 'Roster', icon: ClipboardList },
  ],
  cashier: [
    { path: '/pos', label: 'POS', icon: ShoppingCart },
    { path: '/appointments', label: 'Appointments', icon: Calendar },
    { path: '/customers', label: 'Customers', icon: Users },
    { path: '/loyalty', label: 'Loyalty', icon: Award },
  ],
};

export const quickActionsFor = (role, vertical) => {
  const table = vertical === 'hospitality' ? QUICK_ACTIONS
    : vertical === 'beauty' || vertical === 'services' ? { ...QUICK_ACTIONS, ...QUICK_ACTIONS_BEAUTY_SERVICES }
    : { ...QUICK_ACTIONS, ...QUICK_ACTIONS_NON_HOSPITALITY };
  return table[role] || table.cashier;
};

// Full feature catalog for the "More" splash modal — grouped by role access.
// `verticals` on a group or item narrows it to specific business verticals
// (see frontend/src/lib/businessVertical.js); omitted means "every
// vertical." Kitchen dockets, temp probes, and today's table-oriented
// booking system are hospitality-specific — Phase 2/4 of the vertical
// roadmap give retail and beauty/services their own equivalents instead of
// showing them a restaurant's tools.
const ALL_FEATURES = [
  { group: 'Operations', items: [
    { path: '/today', label: 'Today', icon: Sunrise, access: ['owner', 'manager', 'cashier', 'kitchen'] },
    { path: '/pos', label: 'POS Terminal', icon: ShoppingCart, access: ['owner', 'manager', 'cashier', 'barista'] },
    { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, access: ['owner', 'manager'] },
    { path: '/command-center', label: 'Command Center', icon: Brain, access: ['owner', 'manager'] },
    { path: '/kitchen', label: 'Kitchen Display', icon: ChefHat, access: ['owner', 'manager', 'kitchen'], verticals: ['hospitality'] },
    { path: '/temperature', label: 'Temp Monitoring', icon: Flame, access: ['owner', 'manager', 'kitchen'], verticals: ['hospitality'] },
  ]},
  { group: 'Reservations', verticals: ['hospitality'], items: [
    { path: '/reservations', label: 'Bookings', icon: Utensils, access: ['owner', 'manager', 'cashier'] },
    { path: '/floor-plan', label: 'Floor Plan', icon: MapPin, access: ['owner', 'manager', 'cashier'] },
    { path: '/waitlist', label: 'Waitlist', icon: Clock, access: ['owner', 'manager', 'cashier'] },
    { path: '/booking-settings', label: 'Settings & Rules', icon: Settings, access: ['owner', 'manager'] },
    { path: '/booking-analytics', label: 'Analytics', icon: BarChart3, access: ['owner', 'manager'] },
  ]},
  { group: 'Appointments', verticals: ['beauty', 'services'], items: [
    { path: '/appointments', label: 'Book Appointment', icon: Calendar, access: ['owner', 'manager', 'cashier'] },
  ]},
  { group: 'Social Media & Promotions', items: [
    { path: '/marketing?tab=social',      label: 'Social Media',    icon: Sparkles, access: ['owner', 'manager'] },
    { path: '/marketing?tab=promotions',  label: 'Promotions',      icon: DollarSign, access: ['owner', 'manager'] },
    { path: '/marketing?tab=experiences', label: 'Experiences',     icon: Sparkles, access: ['owner', 'manager'] },
    { path: '/marketing?tab=club',        label: 'Club Members',    icon: Award, access: ['owner', 'manager'] },
    { path: '/marketing?tab=email',       label: 'Email Marketing', icon: Mail, access: ['owner', 'manager'] },
    { path: '/marketing?tab=loyalty',     label: 'Loyalty',         icon: Award, access: ['owner', 'manager', 'cashier'] },
    { path: '/marketing?tab=vouchers',    label: 'Vouchers',        icon: Tag, access: ['owner', 'manager'] },
    { path: '/marketing?tab=gift-cards',  label: 'Gift Cards',      icon: Tag, access: ['owner', 'manager', 'cashier'] },
    { path: '/marketing?tab=events',      label: 'Events',          icon: Trophy, access: ['owner', 'manager'] },
    { path: '/loyalty-config',            label: 'Loyalty Config',  icon: Tag, access: ['owner'] },
  ]},
  { group: 'Items', items: [
    { path: '/products', label: 'Item Library', icon: Package, access: ['owner', 'manager', 'cashier'] },
    { path: '/categories', label: 'Categories', icon: Tag, access: ['owner', 'manager'] },
    { path: '/modifiers', label: 'Modifiers', icon: ClipboardList, access: ['owner', 'manager'] },
    { path: '/channel-menus', label: 'Channel Menus', icon: Link2, access: ['owner', 'manager'] },
    { path: '/comp-void', label: 'Comp / Void', icon: Ban, access: ['owner', 'manager'] },
    { path: '/payment-links', label: 'Payment Links', icon: Link2, access: ['owner', 'manager'] },
  ]},
  { group: 'Menu Engineering', items: [
    { path: '/menu-engineering', label: 'Menu Matrix', icon: FlaskConical, access: ['owner', 'manager'] },
    { path: '/what-if', label: 'What-If', icon: TrendingUp, access: ['owner', 'manager'] },
    { path: '/inventory', label: 'Inventory', icon: Warehouse, access: ['owner', 'manager', 'kitchen'] },
    { path: '/stock-transfers', label: 'Stock Transfers', icon: ArrowLeftRight, access: ['owner', 'manager'], verticals: ['hospitality', 'retail'] },
    { path: '/ai-pantry', label: 'AI Pantry', icon: Brain, access: ['owner', 'manager', 'kitchen'] },
    { path: '/forecasting', label: 'Forecasting', icon: BarChart3, access: ['owner', 'manager'] },
    { path: '/quarterly-review', label: 'Quarterly Review', icon: PieChart, access: ['owner', 'manager'] },
  ]},
  { group: 'Team', items: [
    { path: '/staff', label: 'Staff', icon: Users2, access: ['owner', 'manager'] },
    { path: '/staff-roster', label: 'Roster & Payrun', icon: ClipboardList, access: ['owner', 'manager'] },
    { path: '/leaderboard', label: 'Leaderboard', icon: Trophy, access: ['owner', 'manager', 'cashier', 'kitchen'] },
    { path: '/tip-management', label: 'Tip Management', icon: DollarSign, access: ['owner', 'manager'] },
  ]},
  { group: 'Customers', items: [
    { path: '/customers', label: 'Customer List', icon: Users, access: ['owner', 'manager', 'cashier'] },
  ]},
  { group: 'Accounting', items: [
    { path: '/finance', label: 'Finance Suite', icon: Receipt, access: ['owner'] },
    { path: '/accounting', label: 'Transactions', icon: Receipt, access: ['owner'] },
    { path: '/super', label: 'Superannuation', icon: Shield, access: ['owner'] },
    { path: '/bas-gst', label: 'BAS/GST', icon: FileText, access: ['owner'] },
    { path: '/end-of-day', label: 'End of Day', icon: Calendar, access: ['owner'] },
    { path: '/integrations', label: 'Integrations', icon: Plug, access: ['owner'] },
  ]},
  { group: 'System', items: [
    { path: '/automation-triggers', label: 'Automation', icon: Zap, access: ['owner', 'manager'] },
    { path: '/settings', label: 'Settings', icon: Settings, access: ['owner', 'manager'] },
  ]},
  { group: 'Enterprise (v25)', items: [
    { path: '/enterprise', label: 'Command Center', icon: Brain, access: ['owner', 'manager'] },
    { path: '/ash-pro', label: 'NUA Pro · AI GM', icon: Brain, access: ['owner'] },
    { path: '/profit-guardian', label: 'Profit Guardian', icon: Shield, access: ['owner', 'manager'] },
    { path: '/digital-twin', label: 'Digital Twin', icon: Sparkles, access: ['owner', 'manager'] },
    { path: '/shift-manager', label: 'Shift Manager', icon: Zap, access: ['owner', 'manager'] },
    { path: '/auto-marketing', label: 'Auto Marketing', icon: Mail, access: ['owner', 'manager'] },
    { path: '/recipe-costing', label: 'Recipe Costing', icon: ChefHat, access: ['owner', 'manager'], verticals: ['hospitality'] },
    { path: '/predictive-orders', label: 'Predictive Orders', icon: Package, access: ['owner', 'manager'] },
    { path: '/waste-tracking', label: 'Waste Tracking', icon: Ban, access: ['owner', 'manager', 'kitchen'] },
    { path: '/gift-cards', label: 'Gift Cards', icon: Tag, access: ['owner', 'manager', 'cashier'] },
    { path: '/subscriptions', label: 'Subscriptions', icon: Award, access: ['owner', 'manager'] },
    { path: '/dynamic-pricing-rules', label: 'Dynamic Pricing', icon: TrendingUp, access: ['owner'] },
    { path: '/concierge', label: 'AI Concierge', icon: Sparkles, access: ['owner', 'manager', 'cashier'] },
    { path: '/reputation', label: 'Reputation', icon: Trophy, access: ['owner', 'manager'] },
    { path: '/franchise', label: 'Franchise', icon: MapPin, access: ['owner'] },
    { path: '/fraud-detection', label: 'Fraud Detection', icon: ShieldAlert, access: ['owner', 'manager'] },
    { path: '/exceptions', label: 'Loss Control', icon: AlertTriangle, access: ['owner', 'manager'] },
    { path: '/hardware-health', label: 'Hardware Health', icon: Plug, access: ['owner', 'manager'] },
    { path: '/disputes', label: 'Chargebacks', icon: Shield, access: ['owner', 'manager'] },
    { path: '/supplier-marketplace', label: 'Supplier Market', icon: Package, access: ['owner', 'manager'] },
    { path: '/margin-guardrails', label: 'Margin Guardrails', icon: DollarSign, access: ['owner', 'manager'] },
    { path: '/station-readiness', label: 'Station Readiness', icon: ClipboardList, access: ['owner', 'manager', 'kitchen'], verticals: ['hospitality'] },
    { path: '/kiosk', label: 'Kiosk Mode', icon: ShoppingCart, access: ['owner', 'manager'] },
    { path: '/cfd', label: 'Customer Display', icon: Sparkles, access: ['owner', 'manager', 'cashier'] },
    { path: '/churn-risk', label: 'Guest Recovery', icon: Users, access: ['owner', 'manager'] },
    { path: '/license', label: 'License & Billing', icon: Key, access: ['owner'] },
    { path: '/vouchers', label: 'Vouchers & Codes', icon: Tag, access: ['owner', 'manager'] },
    { path: '/events', label: 'Events & Experiences', icon: Trophy, access: ['owner', 'manager'] },
    { path: '/staff-availability', label: 'Staff Availability', icon: Users, access: ['owner', 'manager'] },
    { path: '/marketing?tab=email', label: 'AI Marketing Emails', icon: Sparkles, access: ['owner', 'manager'] },
    { path: '/online-orders', label: 'Online Orders', icon: ShoppingBag, access: ['owner', 'manager', 'cashier', 'kitchen'] },
    { path: '/inventory-accounting', label: 'Inventory & BAS', icon: Receipt, access: ['owner', 'manager'] },
  ]},
  { group: 'Analytics & AI', items: [
    { path: '/agent', label: 'NUA AI Agent', icon: Brain, access: ['owner', 'manager'] },
    { path: '/agent-autonomy', label: 'NUA Autonomy', icon: Zap, access: ['owner'] },
    { path: '/phone-agent', label: 'AI Phone Agent', icon: Sparkles, access: ['owner', 'manager'] },
    { path: '/ab-tests', label: 'Menu A/B Tests', icon: FlaskConical, access: ['owner', 'manager'] },
    { path: '/purchase-orders', label: 'Purchase Orders', icon: Package, access: ['owner', 'manager'] },
    { path: '/ai-cost-coach', label: 'AI Cost Coach', icon: DollarSign, access: ['owner', 'manager'] },
    { path: '/labor-forecast', label: 'Labor Forecast', icon: Users2, access: ['owner', 'manager'] },
    { path: '/surge-pricing', label: 'Surge Pricing', icon: TrendingUp, access: ['owner'] },
    { path: '/price-tune', label: 'Price-Tune', icon: Tag, access: ['owner', 'manager'] },
    { path: '/voice-recipe', label: 'Voice-to-Recipe', icon: BookOpen, access: ['owner', 'manager', 'kitchen'], verticals: ['hospitality'] },
    { path: '/kitchen-load', label: 'Kitchen Load', icon: ChefHat, access: ['owner', 'manager', 'kitchen'], verticals: ['hospitality'] },
    { path: '/audit', label: 'Audit Log', icon: ShieldAlert, access: ['owner', 'manager'] },
    { path: '/anomalies', label: 'Inventory Anomalies', icon: AlertTriangle, access: ['owner', 'manager'] },
    { path: '/cohort-retention', label: 'Cohort Retention', icon: Users, access: ['owner', 'manager'] },
    { path: '/shift-swaps', label: 'Shift Swaps', icon: ArrowLeftRight, access: ['owner', 'manager', 'cashier', 'kitchen', 'barista'] },
    { path: '/security', label: 'Security & GDPR', icon: Shield, access: ['owner', 'manager'] },
  ]},
];

export default function BottomDock() {
  const { theme, darkMode, toggleDarkMode } = useTheme();
  const { user, logout } = useAuth();
  const { vertical } = useBusiness();
  const navigate = useNavigate();
  const location = useLocation();
  const [showMore, setShowMore] = useState(false);
  const [featureSearch, setFeatureSearch] = useState('');
  const moreButtonRef = useRef(null);
  const [badges, setBadges] = useState({});

  useEffect(() => {
    if (!user) return;
    // Only owners/managers need live badges (kitchen + cashier don't have access)
    if (!['owner', 'manager'].includes(user.role)) return;
    const tick = async () => {
      if (document.visibilityState !== 'visible') return;
      try { const r = await v15API.getBadges(); setBadges(r.data || {}); } catch { /* badge poll best-effort */ }
    };
    tick();
    const id = setInterval(tick, 60000); // poll every 60s
    return () => clearInterval(id);
  }, [user]);

  if (!user) return null;
  const role = user.role || 'cashier';
  const customPerms = (user?.customPermissions?.length > 0) ? user.customPermissions : (user?.permissions || []);
  const hasCustomPerms = Array.isArray(customPerms) && customPerms.length > 0 && !customPerms.includes('*');

  // Vertical gate applies ahead of (and independent from) role/permission
  // checks below — an owner running a retail shop still shouldn't see
  // "Kitchen Display" in their own splash just because owners see
  // everything else access-wise.
  const matchesVertical = (item) => !item.verticals || item.verticals.includes(vertical);

  const isAllowed = (item) => {
    if (!matchesVertical(item)) return false;
    if (role === 'owner') return true;
    if (hasCustomPerms) {
      const key = item.path.replace('/', '') || 'dashboard';
      return customPerms.includes(key);
    }
    return item.access?.includes(role);
  };

  // Quick actions are role-based defaults — no permission filtering (use splash for granular access)
  const quick = quickActionsFor(role, vertical).slice(0, 4);
  const menuLabels = getMenuLabels(vertical);
  const visibleFeatureGroups = ALL_FEATURES
    .filter(g => !g.verticals || g.verticals.includes(vertical))
    .map(g => g.group === 'Items'
      ? { ...g, group: menuLabels.group, items: g.items.map(it => it.path === '/products' ? { ...it, label: menuLabels.itemLabel } : it) }
      : g);

  const search = featureSearch.trim().toLowerCase();
  const filteredGroups = visibleFeatureGroups.map(group => ({ ...group, items: group.items.filter(isAllowed).filter(item => !search || `${group.group} ${item.label} ${item.path}`.toLowerCase().includes(search)) })).filter(group => group.items.length);
  const setMoreOpen = (open) => { setShowMore(open); if (!open) setFeatureSearch(''); };

  const handleLogout = async () => { setShowMore(false); await logout(); navigate('/'); };

  return (
    <>
      {/* BOTTOM DOCK */}
      <div
        className={`fixed bottom-0 left-0 right-0 z-40 backdrop-blur-md border-t shadow-[0_-4px_20px_rgba(0,0,0,0.06)] ${darkMode ? 'border-white/10' : 'border-gray-200'}`}
        style={{ backgroundColor: darkMode ? 'rgba(21,21,29,0.95)' : 'rgba(255,255,255,0.95)', paddingBottom: 'env(safe-area-inset-bottom)' }}
        data-testid="bottom-dock"
      >
        <div className="max-w-screen-2xl mx-auto px-2 sm:px-4 h-16 flex items-center justify-between gap-2">
          <div className="hidden md:flex items-center gap-1 text-sm">
            {/* In-product chrome — product variant only, never the marketing
                lockup (BRAND-SPEC §3). Wordmark colour follows the dock's own
                background, not the theme accent (BRAND-SPEC §2). */}
            <span className="px-2">
              <Logo variant="product" background={darkMode ? 'dark' : 'light'} size={22} />
            </span>
            <span className={`text-[10px] mr-2 hidden sm:inline ${darkMode ? 'text-zinc-500' : 'text-gray-400'}`}>{user.name} · {role}</span>
          </div>
          <div className="flex items-center gap-1 flex-1 min-w-0 justify-evenly md:justify-center md:max-w-xl" role="navigation" aria-label="Main navigation">
            {quick.map(q => {
              const Icon = q.icon;
              const isActive = location.pathname === q.path;
              const badgeKey = q.path === '/reservations' ? 'reservations' :
                                q.path === '/kitchen' ? 'kitchen' :
                                q.path === '/pos' ? 'pos' :
                                q.path === '/waitlist' ? 'waitlist' : null;
              const count = badgeKey ? badges[badgeKey] : 0;
              return (
                <button
                  key={q.path}
                  onClick={() => navigate(q.path)}
                  aria-current={isActive ? 'page' : undefined}
                  className={`relative flex flex-col items-center gap-0.5 px-1 sm:px-3 py-2 rounded-xl transition-all min-w-0 flex-1 md:flex-none md:min-w-[64px] ${isActive ? 'text-white' : (darkMode ? 'text-zinc-400 hover:text-white hover:bg-white/5' : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100')}`}
                  style={isActive ? { backgroundColor: theme.primary } : {}}
                  data-testid={`dock-${q.path.replace('/', '')}`}
                >
                  <div className="relative">
                    <Icon size={18} />
                    {count > 0 && (
                      <span className="absolute -top-2 -right-2 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center" data-testid={`badge-${q.path.replace('/', '')}`}>
                        {count > 99 ? '99+' : count}
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] font-medium">{q.label}</span>
                </button>
              );
            })}
            <button
              ref={moreButtonRef}
              aria-haspopup="dialog" aria-expanded={showMore}
              onClick={() => setMoreOpen(true)}
              className={`flex flex-col items-center gap-0.5 px-1 sm:px-3 py-2 rounded-xl transition-all min-w-0 flex-1 md:flex-none md:min-w-[64px] ${darkMode ? 'text-zinc-400 hover:text-white hover:bg-white/5' : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'}`}
              data-testid="dock-more"
            >
              <MoreHorizontal size={18} />
              <span className="text-[10px] font-medium">More</span>
            </button>
          </div>
          <div className="hidden md:flex items-center gap-1">
            <button
              onClick={toggleDarkMode}
              className={`flex items-center justify-center w-9 h-9 rounded-xl transition-all ${darkMode ? 'text-amber-400 hover:bg-white/5' : 'text-zinc-500 hover:bg-gray-100'}`}
              title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
              data-testid="dock-theme-toggle"
            >
              {darkMode ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              onClick={handleLogout}
              className={`flex items-center gap-1 px-3 py-2 rounded-xl transition-all ${darkMode ? 'text-zinc-500 hover:text-red-400 hover:bg-red-500/10' : 'text-gray-400 hover:text-red-500 hover:bg-red-50'}`}
              aria-label="Sign out"
              data-testid="dock-logout"
            >
              <LogOut size={16} />
              <span className="text-xs hidden sm:inline">Sign Out</span>
            </button>
          </div>
        </div>
      </div>

      <Dialog open={showMore} onOpenChange={setMoreOpen}>
        <DialogContent className="max-w-5xl p-0 gap-0 [&>button]:hidden" data-testid="more-splash"
          onCloseAutoFocus={event => { event.preventDefault(); moreButtonRef.current?.focus(); }}>
          <div className="sticky top-0 bg-background border-b p-4 sm:p-6 z-10 rounded-t-xl">
            <DialogTitle className="pr-12">All Features</DialogTitle>
            <DialogClose className="absolute right-2 top-2 flex h-11 w-11 items-center justify-center rounded-lg hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring" aria-label="Close features">
              <X size={20} />
            </DialogClose>
            <DialogDescription className="mt-1 pr-6">Find a tool for your next task. Showing features available to your account.</DialogDescription>
            <Input aria-label="Find a feature" placeholder="Search features, bookings, inventory…" value={featureSearch}
              onChange={event => setFeatureSearch(event.target.value)} className="mt-4" />
            <div className="flex flex-wrap items-center gap-3 mt-3 text-sm">
              <span className="text-muted-foreground flex-1" role="status">{filteredGroups.reduce((count, group) => count + group.items.length, 0)} features</span>
              <button onClick={toggleDarkMode} className="md:hidden rounded-lg border px-3 py-2">{darkMode ? 'Light mode' : 'Dark mode'}</button>
              <button onClick={handleLogout} className="md:hidden rounded-lg border px-3 py-2">Sign out</button>
            </div>
          </div>
          <div className="p-4 sm:p-6 space-y-6">
            {filteredGroups.length === 0 && <div className="py-8 text-center text-muted-foreground">
              <p>No features found.</p><button className="mt-3 underline" onClick={() => setFeatureSearch('')}>Clear search</button>
            </div>}
            {filteredGroups.map(group => <section key={group.group} aria-label={group.group}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">{group.group === 'Enterprise (v25)' ? 'Advanced operations' : group.group}</h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                {group.items.map(item => {
                  const Icon = item.icon;
                  const active = location.pathname + location.search === item.path;
                  return <button key={item.path} onClick={() => { setMoreOpen(false); navigate(item.path); }}
                    aria-current={active ? 'page' : undefined}
                    className={`flex items-center gap-3 p-3 min-h-16 text-left rounded-xl border transition-colors hover:bg-accent ${active ? 'bg-accent border-primary' : 'bg-card'}`}
                    data-testid={`splash-${item.path.replace('/', '')}`}>
                    <span className="w-9 h-9 shrink-0 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${theme.primary}15`, color: theme.primary }}><Icon size={18} /></span>
                    <span className="text-sm font-medium break-words">{item.label}</span>
                  </button>;
                })}
              </div>
            </section>)}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
