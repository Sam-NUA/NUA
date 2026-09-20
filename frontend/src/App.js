import React, { Suspense, lazy } from 'react';
import './App.css';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext';
import { POSProvider } from './contexts/POSContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { BusinessProvider, useBusiness } from './contexts/BusinessContext';
import { LicenseProvider } from './contexts/LicenseContext';
import { Toaster } from './components/ui/sonner';
import BottomDock from './components/BottomDock';
import BackButton from './components/BackButton';
import LicensePage, { LicenseLockScreen, LicenseBanner } from './pages/LicensePage';
const Login = lazy(() => import('./pages/Login'));
const OnboardingWizard = lazy(() => import('./pages/OnboardingWizard'));
const ResetPassword = lazy(() => import('./pages/ResetPassword'));
const Today = lazy(() => import('./pages/Today'));
import CommandBar from './components/CommandBar';
import VoiceCommandButton from './components/VoiceCommandButton';
const Dashboard = lazy(() => import('./pages/Dashboard'));
const POSTerminal = lazy(() => import('./pages/POSTerminal'));
const StaffApp = lazy(() => import('./pages/StaffApp'));
const OwnerDashboardApp = lazy(() => import('./pages/OwnerDashboardApp'));
import { getAppShell } from './lib/appShell';
const Products = lazy(() => import('./pages/Products'));
const Customers = lazy(() => import('./pages/Customers'));
const Inventory = lazy(() => import('./pages/Inventory'));
const StockTransfers = lazy(() => import('./pages/StockTransfers'));
const Appointments = lazy(() => import('./pages/Appointments'));
const InventoryAccounting = lazy(() => import('./pages/InventoryAccounting'));
const ChannelMenus = lazy(() => import('./pages/ChannelMenus'));
const SocialMedia = lazy(() => import('./pages/SocialMedia'));
const Accounting = lazy(() => import('./pages/Accounting'));
const BASGST = lazy(() => import('./pages/BASGST'));
const Settings = lazy(() => import('./pages/Settings'));
const Reservations = lazy(() => import('./pages/Reservations'));
const FloorPlan = lazy(() => import('./pages/FloorPlan'));
const WaitlistPage = lazy(() => import('./pages/Waitlist'));
const Kitchen = lazy(() => import('./pages/Kitchen'));
const CoursingAnalytics = lazy(() => import('./pages/CoursingAnalytics'));
const ClockInPrompt = lazy(() => import('./pages/ClockInPrompt'));
const CommandCenter = lazy(() => import('./pages/CommandCenter'));
const MenuEngineering = lazy(() => import('./pages/MenuEngineering'));
const AutomationTriggers = lazy(() => import('./pages/AutomationTriggers'));
const LoyaltyEvents = lazy(() => import('./pages/LoyaltyEvents'));
const Forecasting = lazy(() => import('./pages/Forecasting'));
const WhatIfSimulator = lazy(() => import('./pages/WhatIfSimulator'));
const BookingPortal = lazy(() => import('./pages/BookingPortal'));
const TableOrder = lazy(() => import('./pages/TableOrder'));
const SplitBillGuestEnhanced = lazy(() => import('./pages/SplitBillGuestEnhanced'));
const SplitBillStaff = lazy(() => import('./pages/SplitBillStaff'));
const PaymentSuccess = lazy(() => import('./pages/PaymentSuccess'));
const Integrations = lazy(() => import('./pages/Integrations'));
const WhatsNew = lazy(() => import('./pages/WhatsNew'));
const EFTPOSTerminals = lazy(() => import('./pages/EFTPOSTerminals'));
const StaffManagement = lazy(() => import('./pages/StaffManagement'));
const AIPantry = lazy(() => import('./pages/AIPantry'));
const MemberPortal = lazy(() => import('./pages/MemberPortal'));
const StaffRoster = lazy(() => import('./pages/StaffRoster'));
const StaffLeaderboard = lazy(() => import('./pages/StaffLeaderboard'));
const QuarterlyReview = lazy(() => import('./pages/QuarterlyReview'));
const BookingSettings = lazy(() => import('./pages/BookingSettings'));
const BookingExperience = lazy(() => import('./pages/BookingExperience'));
const BookingAnalytics = lazy(() => import('./pages/BookingAnalytics'));
const Clubmember = lazy(() => import('./pages/Clubmember'));
const EmailMarketing = lazy(() => import('./pages/EmailMarketing'));
const Marketing = lazy(() => import('./pages/Marketing'));
const Super = lazy(() => import('./pages/Super'));
const Payroll = lazy(() => import('./pages/Payroll'));
const Vouchers = lazy(() => import('./pages/Vouchers'));
const FinanceLedger = lazy(() => import('./pages/FinanceLedger'));
const AshDashboard = lazy(() => import('./pages/AshDashboard'));
const AshCommandCenter = lazy(() => import('./pages/AshCommandCenter'));
const AshPlans = lazy(() => import('./pages/AshPlans'));
const AshPermissions = lazy(() => import('./pages/AshPermissions'));
const AshMemory = lazy(() => import('./pages/AshMemory'));
const LoyaltyProgress = lazy(() => import('./pages/LoyaltyProgress'));
const MeasuredStock = lazy(() => import('./pages/MeasuredStock'));
const Approvals = lazy(() => import('./pages/Approvals'));
const AuditLogUniversal = lazy(() => import('./pages/AuditLogUniversal'));
const HQDashboard = lazy(() => import('./pages/HQDashboard'));
const MultiBusiness = lazy(() => import('./pages/MultiBusiness'));
const IdentitySettings = lazy(() => import('./pages/IdentitySettings'));
import AshChat from './components/AshChat';
import NotificationBell from './components/NotificationBell';
const Temperature = lazy(() => import('./pages/Temperature'));
const EndOfDay = lazy(() => import('./pages/EndOfDay'));
const TipManagement = lazy(() => import('./pages/TipManagement'));
const Categories = lazy(() => import('./pages/Categories'));
const Modifiers = lazy(() => import('./pages/Modifiers'));
const Discounts = lazy(() => import('./pages/Discounts'));
const CompVoid = lazy(() => import('./pages/CompVoid'));
const PaymentLinks = lazy(() => import('./pages/PaymentLinks'));
const InventoryAnomalies = lazy(() => import('./pages/InventoryAnomalies'));
const CohortRetention = lazy(() => import('./pages/CohortRetention'));
const ShiftSwaps = lazy(() => import('./pages/ShiftSwaps'));
const SecurityCompliance = lazy(() => import('./pages/SecurityCompliance'));
const LoyaltyConfig = lazy(() => import('./pages/LoyaltyConfig'));
const AgentDashboard = lazy(() => import('./pages/AgentDashboard'));
const AgentAutonomy = lazy(() => import('./pages/AgentAutonomy'));
const PhoneAgent = lazy(() => import('./pages/PhoneAgent'));
const PurchaseOrders = lazy(() => import('./pages/PurchaseOrders'));
const MenuABTesting = lazy(() => import('./pages/MenuABTesting'));
const AICostCoach = lazy(() => import('./pages/AICostCoach'));
const LaborForecast = lazy(() => import('./pages/LaborForecast'));
const SurgePricing = lazy(() => import('./pages/SurgePricing'));
const VoiceRecipe = lazy(() => import('./pages/VoiceRecipe'));
const KitchenLoad = lazy(() => import('./pages/KitchenLoad'));
const PriceTune = lazy(() => import('./pages/PriceTune'));
const EnterpriseCommandCenter = lazy(() => import('./pages/EnterpriseCommandCenter'));
const NuaPro = lazy(() => import('./pages/NuaPro'));
const ProfitGuardian = lazy(() => import('./pages/ProfitGuardian'));
const DigitalTwin = lazy(() => import('./pages/DigitalTwin'));
// V25Pages/V26Pages are batch named-export files (20 + 3 components) — lazy()
// needs a default export, so each one wraps the shared module import and
// picks its own named export off it. All still resolve from one chunk (the
// whole file loads together the first time any of these routes is hit)
// since React.lazy can't split named exports out of a single module on its
// own — but that's still 23 components deferred out of the eager bundle
// instead of importing all of them upfront.
const lazyNamed = (loader, name) => lazy(() => loader().then(m => ({ default: m[name] })));
const v25 = () => import('./pages/V25Pages');
const v26 = () => import('./pages/V26Pages');
const ShiftManager = lazyNamed(v25, 'ShiftManager');
const AutoMarketing = lazyNamed(v25, 'AutoMarketing');
const Exceptions = lazyNamed(v25, 'Exceptions');
const HardwareHealth = lazyNamed(v25, 'HardwareHealth');
const Disputes = lazyNamed(v25, 'Disputes');
const SupplierMarketplace = lazyNamed(v25, 'SupplierMarketplace');
const GiftCards = lazyNamed(v25, 'GiftCards');
const PredictiveOrders = lazyNamed(v25, 'PredictiveOrders');
const WasteTracking = lazyNamed(v25, 'WasteTracking');
const Concierge = lazyNamed(v25, 'Concierge');
const Reputation = lazyNamed(v25, 'Reputation');
const Franchise = lazyNamed(v25, 'Franchise');
const FraudDetection = lazyNamed(v25, 'FraudDetection');
const MarginGuardrails = lazyNamed(v25, 'MarginGuardrails');
const StationReadiness = lazyNamed(v25, 'StationReadiness');
const KioskMode = lazyNamed(v25, 'KioskMode');
const CFD = lazyNamed(v25, 'CFD');
const ChurnRisk = lazyNamed(v25, 'ChurnRisk');
const RecipeCosting = lazyNamed(v25, 'RecipeCosting');
const DynamicPricing = lazyNamed(v25, 'DynamicPricing');
const Subscriptions = lazyNamed(v25, 'Subscriptions');
const EventsManager = lazyNamed(v26, 'EventsManager');
const StaffAvailability = lazyNamed(v26, 'StaffAvailability');
const OnlineOrders = lazy(() => import('./pages/OnlineOrders'));
const OrderOnline = lazy(() => import('./pages/OrderOnline'));
const TrackOrder = lazy(() => import('./pages/TrackOrder'));
const TrackWaitlist = lazy(() => import('./pages/TrackWaitlist'));
const LoyaltyGuestPortal = lazy(() => import('./pages/LoyaltyGuestPortal'));
import { useTheme } from './contexts/ThemeContext';
import useIdleLogout from './hooks/useIdleLogout';

function StaffLayout({ children }) {
  const { darkMode } = useTheme();
  return (
    <div
      className="min-h-screen pb-20 transition-colors"
      style={{
        backgroundColor: darkMode ? '#0b0b0f' : '#f6f7fb',
        color: darkMode ? '#eaeaea' : '#1f2937',
      }}
    >
      <LicenseBanner />
      <LicenseLockScreen />
      <div className="px-6 py-6 max-w-screen-2xl mx-auto">
        <BackButton />
        {children}
      </div>
      <BottomDock />
      <AshChat />
      <NotificationBell />
      <CommandBar />
      <VoiceCommandButton />
    </div>
  );
}

function ProtectedRoutes() {
  const { user, loading, logout } = useAuth();
  // Called unconditionally (Rules of Hooks) even though it only matters
  // once a user is logged in — same reasoning as useIdleLogout below.
  const { business, loading: businessLoading } = useBusiness();
  // Owner-configurable POS auto-logout (Settings → POS Session). Called
  // unconditionally (Rules of Hooks) — the hook itself no-ops while
  // enabled is false, i.e. before there's a session to time out.
  useIdleLogout(!!user, logout);
  // Read (and persist) the shell BEFORE the login gate — a ?shell= query
  // param only ever shows up on the very first, pre-login page load, so it
  // must be captured into localStorage right away or it's lost the moment
  // the login redirect drops the query string.
  const shell = getAppShell();
  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="animate-pulse text-gray-500 text-lg">Loading...</div></div>;
  if (!user) return <Login />;

  // First-login setup wizard — owner only (a cashier/manager logging in
  // before the owner has finished setup just uses the app normally; there's
  // nothing for them to configure). Blocks the whole shell, whatever shell
  // or URL was hit, until name/ABN/vertical are set — same "loading" wait
  // as the auth check above so it never flashes the real app first.
  if (user.role === 'owner') {
    if (businessLoading) return <div className="min-h-screen flex items-center justify-center"><div className="animate-pulse text-gray-500 text-lg">Loading...</div></div>;
    if (business && !business.onboardingComplete) return <OnboardingWizard />;
  }

  // staff.nuapos.com.au — deliberately narrow (per the v1 scope): whatever
  // path was hit, this is the Staff app and nothing else. Same backend, same
  // login, same account — just a different, single-purpose front door with
  // none of the admin chrome (no BottomDock, no CommandBar, no Ash FAB).
  if (shell === 'staff') {
    return (
      <LicenseProvider>
        <LicenseBanner />
        <LicenseLockScreen />
        <Routes>
          <Route path="*" element={<StaffApp />} />
        </Routes>
      </LicenseProvider>
    );
  }

  // Role-based landing: owner.nuapos.com.au always opens the Dashboard app;
  // otherwise owners/managers get the Today pulse, cashiers the POS, kitchen
  // staff the KDS. Same data everywhere — different front door. Unlike the
  // staff shell, the owner shell keeps the full admin nav — the Dashboard
  // app is the front door, not a cage, since owners need to reach every
  // report and drill-down NUA POS has.
  // owner.nuapos.com.au opens Pulse — but only for the roles Pulse is for.
  // A cashier or kitchen login reaching the owner subdomain (a shared
  // device, a bookmark, a mistyped URL) still lands on their own home
  // screen rather than a dashboard of takings and margins.
  const isManagement = user.role === 'owner' || user.role === 'manager';
  const home = (shell === 'owner' && isManagement) ? '/owner-dashboard'
    : user.role === 'cashier' ? '/pos' : user.role === 'kitchen' ? '/kitchen' : '/today';
  return (
    <LicenseProvider>
    <StaffLayout>
      <Routes>
        <Route path="/" element={<Navigate to={home} replace />} />
        <Route path="/today" element={<Today />} />
        <Route path="/staff-app" element={<StaffApp />} />
        {/* Pulse is owner/manager only — the route itself is guarded, not
            just the nav entry, so typing the URL doesn't get you in either. */}
        <Route path="/owner-dashboard" element={isManagement ? <OwnerDashboardApp /> : <Navigate to={home} replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        {/* Pre-Shift Briefing merged into Today (Aug 2026) — old links/bookmarks still land somewhere useful */}
        <Route path="/pre-shift" element={<Navigate to="/today" replace />} />
        <Route path="/clock-in" element={<ClockInPrompt />} />
        <Route path="/command-center" element={<CommandCenter />} />
        <Route path="/pos" element={<POSTerminal />} />
        <Route path="/split-monitor" element={<SplitBillStaff />} />
        <Route path="/reservations" element={<Reservations />} />
        {/* AI Bookings Inbox and Busy-Time Heatmap merged into Reservations as tabs (Aug 2026) */}
        <Route path="/bookings-inbox" element={<Navigate to="/reservations" replace />} />
        <Route path="/channel-menus" element={<ChannelMenus />} />
        <Route path="/social-media" element={<Navigate to="/marketing?tab=social" replace />} />
        <Route path="/marketing" element={<Marketing />} />
        <Route path="/floor-plan" element={<FloorPlan />} />
        <Route path="/waitlist" element={<WaitlistPage />} />
        {/* Table Layout's combinations feature merged into Floor Plan as a panel (Aug 2026) */}
        <Route path="/table-layout" element={<Navigate to="/floor-plan" replace />} />
        <Route path="/booking-settings" element={<BookingSettings />} />
        <Route path="/booking-experience" element={<Navigate to="/marketing?tab=experiences" replace />} />
        <Route path="/clubmember" element={<Navigate to="/marketing?tab=club" replace />} />
        <Route path="/booking-analytics" element={<BookingAnalytics />} />
        <Route path="/kitchen" element={<Kitchen />} />
        <Route path="/coursing-analytics" element={<CoursingAnalytics />} />
        <Route path="/menu-engineering" element={<MenuEngineering />} />
        <Route path="/what-if" element={<WhatIfSimulator />} />
        <Route path="/products" element={<Products />} />
        <Route path="/categories" element={<Categories />} />
        <Route path="/modifiers" element={<Modifiers />} />
        <Route path="/discounts" element={<Navigate to="/marketing?tab=promotions" replace />} />
        <Route path="/comp-void" element={<CompVoid />} />
        <Route path="/payment-links" element={<PaymentLinks />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/loyalty" element={<Navigate to="/marketing?tab=loyalty" replace />} />
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/stock-transfers" element={<StockTransfers />} />
        <Route path="/appointments" element={<Appointments />} />
        <Route path="/inventory-accounting" element={<InventoryAccounting />} />
        <Route path="/forecasting" element={<Forecasting />} />
        <Route path="/automation" element={<Navigate to="/automation-triggers" replace />} />
        <Route path="/automation-triggers" element={<AutomationTriggers />} />
        <Route path="/accounting" element={<Accounting />} />
        <Route path="/finance" element={<FinanceLedger />} />
        <Route path="/ash" element={<AshDashboard />} />
        <Route path="/ash-hq" element={<AshCommandCenter />} />
        <Route path="/ash-plans" element={<AshPlans />} />
        <Route path="/ash-permissions" element={<AshPermissions />} />
        <Route path="/ash-memory" element={<AshMemory />} />
        <Route path="/loyalty-progress" element={<LoyaltyProgress />} />
        <Route path="/measured-stock" element={<MeasuredStock />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/audit" element={<AuditLogUniversal />} />
        <Route path="/hq" element={<HQDashboard />} />
        <Route path="/multi-business" element={<MultiBusiness />} />
        <Route path="/identity-settings" element={<IdentitySettings />} />
        <Route path="/bas-gst" element={<BASGST />} />
        <Route path="/super" element={<Super />} />
        <Route path="/payroll" element={<Payroll />} />
        <Route path="/vouchers" element={<Vouchers />} />
        <Route path="/temperature" element={<Temperature />} />
        <Route path="/integrations" element={<Integrations />} />
        <Route path="/eftpos-terminals" element={<EFTPOSTerminals />} />
        <Route path="/staff" element={<StaffManagement />} />
        <Route path="/staff-roster" element={<StaffRoster />} />
        <Route path="/leaderboard" element={<StaffLeaderboard />} />
        <Route path="/quarterly-review" element={<QuarterlyReview />} />
        <Route path="/ai-pantry" element={<AIPantry />} />
        <Route path="/email-marketing" element={<Navigate to="/marketing?tab=email" replace />} />
        <Route path="/end-of-day" element={<EndOfDay />} />
        <Route path="/tip-management" element={<TipManagement />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/print-routing" element={<Navigate to="/settings?tab=print-routing" replace />} />
        <Route path="/security" element={<SecurityCompliance />} />
        <Route path="/anomalies" element={<InventoryAnomalies />} />
        <Route path="/cohort-retention" element={<CohortRetention />} />
        <Route path="/shift-swaps" element={<ShiftSwaps />} />
        <Route path="/loyalty-config" element={<LoyaltyConfig />} />
        <Route path="/agent" element={<AgentDashboard />} />
        <Route path="/agent-autonomy" element={<AgentAutonomy />} />
        <Route path="/phone-agent" element={<PhoneAgent />} />
        <Route path="/purchase-orders" element={<PurchaseOrders />} />
        <Route path="/ab-tests" element={<MenuABTesting />} />
        <Route path="/ai-cost-coach" element={<AICostCoach />} />
        <Route path="/labor-forecast" element={<LaborForecast />} />
        <Route path="/surge-pricing" element={<SurgePricing />} />
        <Route path="/voice-recipe" element={<VoiceRecipe />} />
        <Route path="/kitchen-load" element={<KitchenLoad />} />
        <Route path="/price-tune" element={<PriceTune />} />
        {/* v25 Enterprise Suite */}
        <Route path="/enterprise" element={<EnterpriseCommandCenter />} />
        <Route path="/ash-pro" element={<NuaPro />} />
        <Route path="/profit-guardian" element={<ProfitGuardian />} />
        <Route path="/digital-twin" element={<DigitalTwin />} />
        <Route path="/shift-manager" element={<ShiftManager />} />
        <Route path="/auto-marketing" element={<AutoMarketing />} />
        <Route path="/exceptions" element={<Exceptions />} />
        <Route path="/hardware-health" element={<HardwareHealth />} />
        <Route path="/disputes" element={<Disputes />} />
        <Route path="/supplier-marketplace" element={<SupplierMarketplace />} />
        <Route path="/gift-cards" element={<GiftCards />} />
        <Route path="/predictive-orders" element={<PredictiveOrders />} />
        <Route path="/waste-tracking" element={<WasteTracking />} />
        <Route path="/concierge" element={<Concierge />} />
        <Route path="/reputation" element={<Reputation />} />
        <Route path="/franchise" element={<Franchise />} />
        <Route path="/fraud-detection" element={<FraudDetection />} />
        <Route path="/margin-guardrails" element={<MarginGuardrails />} />
        <Route path="/station-readiness" element={<StationReadiness />} />
        <Route path="/kiosk" element={<KioskMode />} />
        <Route path="/cfd" element={<CFD />} />
        <Route path="/churn-risk" element={<ChurnRisk />} />
        <Route path="/recipe-costing" element={<RecipeCosting />} />
        <Route path="/dynamic-pricing-rules" element={<DynamicPricing />} />
        <Route path="/subscriptions" element={<Subscriptions />} />
        {/* v26 commerce */}
        {/* /vouchers is already routed above to the Universal Voucher Engine
            (Vouchers.jsx) — VoucherManager (marketing/coupon codes) lives at
            /marketing?tab=vouchers instead, so this used to be an unreachable
            duplicate <Route path="/vouchers">. */}
        <Route path="/events" element={<EventsManager />} />
        <Route path="/staff-availability" element={<StaffAvailability />} />
        <Route path="/gift-card-sale" element={<Navigate to="/gift-cards" replace />} />
        <Route path="/marketing-emails" element={<Navigate to="/marketing?tab=email" replace />} />
        <Route path="/online-orders" element={<OnlineOrders />} />
        <Route path="/license" element={<LicensePage />} />
        <Route path="/whats-new" element={<WhatsNew />} />
      </Routes>
    </StaffLayout>
    </LicenseProvider>
  );
}

function App() {
  return (
    <ThemeProvider>
      <POSProvider>
        <AuthProvider>
        <BusinessProvider>
          <div className="App">
            <BrowserRouter>
              {/* Page components are lazy-loaded (see the const X = lazy(...)
                  imports above) — one Suspense boundary here covers every
                  nested <Routes> too (ProtectedRoutes', the staff-shell one),
                  since a boundary catches any descendant's suspend regardless
                  of nesting depth. Previously all ~120 page components were
                  imported eagerly at module load, in one bundle, before the
                  user had picked a single route. */}
              <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><div className="animate-pulse text-gray-500 text-lg">Loading...</div></div>}>
                <Routes>
                  {/* Public routes — no sidebar, no auth */}
                  <Route path="/booking" element={<BookingPortal />} />
                  <Route path="/table/:tableId" element={<TableOrder />} />
                  <Route path="/split/:tableNumber" element={<SplitBillGuestEnhanced />} />
                  <Route path="/split-bill" element={<SplitBillGuestEnhanced />} />
                  <Route path="/join" element={<MemberPortal />} />
                  <Route path="/payment-success" element={<PaymentSuccess />} />
                  <Route path="/order-online" element={<OrderOnline />} />
                  <Route path="/track" element={<TrackOrder />} />
                  <Route path="/track/:code" element={<TrackOrder />} />
                  <Route path="/waitlist-track" element={<TrackWaitlist />} />
                  <Route path="/waitlist-track/:code" element={<TrackWaitlist />} />
                  <Route path="/rewards" element={<LoyaltyGuestPortal />} />
                  <Route path="/reset-password" element={<ResetPassword />} />
                  {/* Staff routes — auth required */}
                  <Route path="/*" element={<ProtectedRoutes />} />
                </Routes>
              </Suspense>
              <Toaster />
            </BrowserRouter>
          </div>
        </BusinessProvider>
        </AuthProvider>
      </POSProvider>
    </ThemeProvider>
  );
}

export default App;
