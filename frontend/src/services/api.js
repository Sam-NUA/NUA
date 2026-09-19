import axios from 'axios';

const API_BASE_URL = `${process.env.REACT_APP_BACKEND_URL}/api`;

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach auth token to every request — unless the caller already set its
// own Authorization header (guestSessionAPI/billSplitAPI do this: a guest
// page has its own short-lived phone-verified token, never the staff
// session, and a staff member testing the guest flow on a browser where
// they're ALSO logged in as staff must not have that call silently
// switched to their staff credential).
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('nua_token');
  if (token && !config.headers.Authorization) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Silent refresh on a 401: the access token lasts 8 hours, and until now
// there was nothing between "still valid" and "force a full re-login" — any
// session left open past that window (an unattended kiosk, an overnight
// shift) just started throwing 401s on every call with no recovery. POST
// /auth/refresh reads the httpOnly refresh_token cookie set at login (valid
// 7 days) and returns a fresh access token; on success this updates
// localStorage and retries the original request exactly once. Concurrent
// 401s (several polling components failing around the same moment) share
// one in-flight refresh instead of each firing their own.
let refreshPromise = null;
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const isAuthEndpoint = original?.url?.includes('/auth/refresh') || original?.url?.includes('/auth/login');
    if (error.response?.status === 401 && original && !original._retriedAfterRefresh && !isAuthEndpoint) {
      original._retriedAfterRefresh = true;
      try {
        if (!refreshPromise) {
          refreshPromise = axios
            .post(`${API_BASE_URL}/auth/refresh`, {}, { withCredentials: true })
            .finally(() => { refreshPromise = null; });
        }
        const r = await refreshPromise;
        const newToken = r.data?.token;
        if (newToken) {
          localStorage.setItem('nua_token', newToken);
          original.headers.Authorization = `Bearer ${newToken}`;
          return api(original);
        }
      } catch {
        // Refresh token is itself missing/expired — the session is genuinely
        // over, not just the access token. Fall through to the rejection
        // below; AuthContext's next checkAuth (or a protected-route guard)
        // is what actually navigates to /login, this just stops pretending
        // localStorage still holds something usable.
        localStorage.removeItem('nua_token');
      }
    }
    return Promise.reject(error);
  }
);

// Auth — self-service password recovery (login/logout/2FA live in AuthContext)
export const authAPI = {
  forgotPassword: (email) => api.post('/auth/forgot-password', { email }),
  resetPassword: (token, password) => api.post('/auth/reset-password', { token, password }),
};

// Products API
export const productsAPI = {
  getAll: (params) => api.get('/products', { params }),
  create: (data) => api.post('/products', data),
  update: (id, data) => api.put(`/products/${id}`, data),
  delete: (id) => api.delete(`/products/${id}`),
  adjustStock: (id, data) => api.post(`/products/${id}/adjust-stock`, data),
  variants: (id) => api.get(`/products/${id}/variants`),
  autoTranslate: (id) => api.post(`/products/${id}/auto-translate`),
  bulkAutoTranslate: (onlyMissing = true) => api.post('/products/bulk-auto-translate', null, { params: { only_missing: onlyMissing } }),
};

// Stock transfers between locations (retail multi-location)
export const stockTransfersAPI = {
  list: (params) => api.get('/stock-transfers', { params }),
  create: (data) => api.post('/stock-transfers', data),
  receive: (id) => api.post(`/stock-transfers/${id}/receive`),
  cancel: (id) => api.post(`/stock-transfers/${id}/cancel`),
};

// Beauty/services: service catalog + staff-as-resource appointment booking
export const servicesAPI = {
  list: (activeOnly = true) => api.get('/services', { params: { active_only: activeOnly } }),
  create: (data) => api.post('/services', data),
  update: (id, data) => api.put(`/services/${id}`, data),
  delete: (id) => api.delete(`/services/${id}`),
};

export const staffRosterAPI = {
  list: () => api.get('/auth/staff'),
};

export const appointmentsAPI = {
  list: (params) => api.get('/appointments', { params }),
  availability: (params) => api.get('/appointments/availability', { params }),
  create: (data) => api.post('/appointments', data),
  update: (id, data) => api.put(`/appointments/${id}`, data),
  complete: (id) => api.post(`/appointments/${id}/complete`),
  cancel: (id) => api.post(`/appointments/${id}/cancel`),
  noShow: (id, fee = 0) => api.post(`/appointments/${id}/no-show`, null, { params: { fee } }),
};

export const clientIntakeAPI = {
  list: (params) => api.get('/client-intake', { params }),
  create: (data) => api.post('/client-intake', data),
};

// EFTPOS terminals
export const eftposAPI = {
  listTerminals: () => api.get('/eftpos/terminals'),
  createTerminal: (data) => api.post('/eftpos/terminals', data),
  updateTerminal: (id, data) => api.put(`/eftpos/terminals/${id}`, data),
  deleteTerminal: (id) => api.delete(`/eftpos/terminals/${id}`),
  testTerminal: (id) => api.post(`/eftpos/terminals/${id}/test`),
  listTransactions: (terminalId) => api.get('/eftpos/transactions', { params: terminalId ? { terminal_id: terminalId } : {} }),
  testHistory: (id) => api.get(`/eftpos/terminals/${id}/test-history`),
};

// Promotions API
export const promotionsAPI = {
  getAll: () => api.get('/promotions'),
  getActive: () => api.get('/promotions/active'),
  create: (data) => api.post('/promotions', data),
  update: (id, data) => api.put(`/promotions/${id}`, data),
  delete: (id) => api.delete(`/promotions/${id}`),
};

// Customers API
export const customersAPI = {
  getAll: (params) => api.get('/customers', { params }),
  create: (data) => api.post('/customers', data),
  update: (id, data) => api.put(`/customers/${id}`, data),
  getProfile: (id) => api.get(`/customers/${id}/profile`),
  getWallet: (id) => api.get(`/customers/${id}/wallet`),
  getWalletOffers: () => api.get('/customers/wallet-offers'),
  saveWalletOffers: (data) => api.post('/customers/wallet-offers', data),
  redeemStoreCredit: (id, amount) => api.post(`/customers/${id}/store-credit/redeem`, { amount }),
};

// Feedback API
export const feedbackAPI = {
  create: (data) => api.post('/feedback', data),
};

// Transactions API
export const transactionsAPI = {
  getAll: (params) => api.get('/transactions', { params }),
  create: (data) => api.post('/transactions', data),
  getDetail: (id) => api.get(`/transactions/${id}`),
};

// Refunds API
export const refundsAPI = {
  create: (data) => api.post('/refunds', data),
};

// Accounting API
export const accountingAPI = {
  getSummary: () => api.get('/accounting/summary'),
};

// Enterprise Finance & Accounting (double-entry)
export const financeAPI = {
  // Chart of Accounts
  listAccounts: () => api.get('/accounting/accounts'),
  createAccount: (data) => api.post('/accounting/accounts', data),
  deleteAccount: (code) => api.delete(`/accounting/accounts/${code}`),
  // Journals
  listJournals: (params) => api.get('/accounting/journals', { params }),
  createJournal: (data) => api.post('/accounting/journals', data),
  reverseJournal: (id, data) => api.post(`/accounting/journals/${id}/reverse`, data),
  // Reports
  trialBalance: (params) => api.get('/accounting/reports/trial-balance', { params }),
  profitLoss: (params) => api.get('/accounting/reports/profit-loss', { params }),
  balanceSheet: (params) => api.get('/accounting/reports/balance-sheet', { params }),
  cashFlow: (params) => api.get('/accounting/reports/cash-flow', { params }),
  // AP
  listBills: (params) => api.get('/accounting/bills', { params }),
  createBill: (data) => api.post('/accounting/bills', data),
  payBill: (id, data) => api.post(`/accounting/bills/${id}/pay`, data),
  // AR
  listInvoices: (params) => api.get('/accounting/invoices', { params }),
  createInvoice: (data) => api.post('/accounting/invoices', data),
  parseInvoiceUpload: (data) => api.post('/accounting/invoices/parse-upload', data),
  receiveInvoice: (id, data) => api.post(`/accounting/invoices/${id}/receive`, data),
  // Deposits
  listDeposits: (status) => api.get('/accounting/deposits', { params: status ? { status } : {} }),
  createDeposit: (data) => api.post('/accounting/deposits', data),
  applyDeposit: (id, data) => api.post(`/accounting/deposits/${id}/apply`, data),
  refundDeposit: (id) => api.post(`/accounting/deposits/${id}/refund`),
  // Bank rec
  bankStatement: (code, params) => api.get(`/accounting/bank/statement/${code}`, { params }),
  importBank: (data) => api.post('/accounting/bank/import', data),
  matchBank: (lineId, jid) => api.post(`/accounting/bank/${lineId}/match/${jid}`),
  ignoreBank: (lineId) => api.post(`/accounting/bank/${lineId}/ignore`),
  // Budgets
  listBudgets: () => api.get('/accounting/budgets'),
  createBudget: (data) => api.post('/accounting/budgets', data),
  updateBudget: (id, data) => api.put(`/accounting/budgets/${id}`, data),
  deleteBudget: (id) => api.delete(`/accounting/budgets/${id}`),
  budgetVsActual: (params) => api.get('/accounting/reports/budget-vs-actual', { params }),
  // KPIs
  kpis: () => api.get('/accounting/kpis'),
};

// BAS/GST API
export const basGstAPI = {
  getReports: () => api.get('/bas-gst/reports'),
  submit: (id, useApi) => api.post(`/bas-gst/submit/${id}`, null, { params: { use_api: useApi } }),
};

// Locations API
export const locationsAPI = {
  getAll: () => api.get('/locations'),
  create: (data) => api.post('/locations', data),
  update: (id, data) => api.put(`/locations/${id}`, data),
  delete: (id) => api.delete(`/locations/${id}`),
};

// Categories API
export const categoriesAPI = {
  getAll: () => api.get('/categories'),
};

// Product Image Library
export const productImagesAPI = {
  list: (params = {}) => api.get('/product-images', { params }),
  upload: (data) => api.post('/product-images', data),
  delete: (id) => api.delete(`/product-images/${id}`),
};

// Products bulk-edit (separate from CRUD for clarity)
export const productsBulkAPI = {
  bulkEdit: (payload) => api.post('/products/bulk-edit', payload),
};

// AI Bookings Inbox — unified inbound channels (DM, phone, web)
export const bookingsInboxAPI = {
  list: (params = {}) => api.get('/bookings/inbox', { params }),
  ingest: (data) => api.post('/bookings/inbox', data),
  ack: (id, data) => api.post(`/bookings/inbox/${id}/ack`, data),
  dismiss: (id) => api.post(`/bookings/inbox/${id}/dismiss`),
};

// Awards (Fair Work / multi-country) + Super calc
export const awardsAPI = {
  catalogue: (country) => api.get('/awards/catalogue', { params: country ? { country } : {} }),
  install: (code) => api.post('/awards/install', { code }),
  uninstall: (code) => api.delete(`/awards/${code}`),
  superByAward: (payload) => api.post('/payruns/super-by-award', payload),
};

// Channel Menus — per-channel pricing, availability, prep, AI discounts
export const channelMenusAPI = {
  channels: () => api.get('/channel-menus/channels'),
  list: (channel) => api.get(`/channel-menus/${channel}`),
  patch: (channel, body) => api.post(`/channel-menus/${channel}/patch`, body),
  bulkPrice: (channel, body) => api.post(`/channel-menus/${channel}/bulk-price`, body),
  aiPrepTimes: (channel) => api.post(`/channel-menus/${channel}/ai-prep-times`),
  aiDiscountSlow: (channel, body) => api.post(`/channel-menus/${channel}/ai-discount-slow`, body),
};

// Reservations: AI table auto-assign
export const reservationsAIAPI = {
  aiAssignTable: (reservationId) => api.post(`/reservations/${reservationId}/ai-assign-table`),
  aiAssignWalkin: (body) => api.post('/walkins/ai-assign', body),
  seatWalkin: (body) => api.post('/walkins/seat', body),
};

// Modifiers API
export const modifiersAPI = {
  getAll: () => api.get('/modifiers'),
};

// Reservations API
export const reservationsAPI = {
  getAll: (params) => api.get('/reservations', { params }),
  // Guest lookup + 360 booking summary. Same endpoint serves staff typing a
  // name/phone/email and the NUA phone agent resolving an inbound caller ID.
  guestLookup: (params) => api.get('/reservations/guest-lookup', { params }),
  guestIntel: (customerId) => api.get(`/reservations/guest-intel/${customerId}`),
  get: (id) => api.get(`/reservations/${id}`),
  create: (data) => api.post('/reservations', data),
  update: (id, data) => api.put(`/reservations/${id}`, data),
  delete: (id) => api.delete(`/reservations/${id}`),
  seat: (id, tableId) => api.post(`/reservations/${id}/seat`, null, { params: { table_id: tableId } }),
  complete: (id) => api.post(`/reservations/${id}/complete`),
  noShow: (id, fee) => api.post(`/reservations/${id}/no-show`, null, { params: { fee } }),
  requestDeposit: (id, originUrl) => api.post(`/reservations/${id}/request-deposit`, { originUrl }),
  cancel: (id, reason) => api.post(`/reservations/${id}/cancel`, { reason }),
  restore: (id, status) => api.post(`/reservations/${id}/restore`, status ? { status } : {}),
  approve: (id) => api.post(`/reservations/${id}/approve`),
  reject: (id, reason) => api.post(`/reservations/${id}/reject`, { reason }),
  autoAssign: (id) => api.get(`/reservations/auto-assign/${id}`),
  getCancellationPolicy: () => api.get('/reservations/cancellation-policy'),
  updateCancellationPolicy: (data) => api.put('/reservations/cancellation-policy', data),
  // Booking calendar helpers
  dayCounts: (fromDate, toDate) => api.get('/reservations/day-counts', { params: { fromDate, toDate } }),
  createBlackout: (data) => api.post('/reservations/blackouts', data),
  deleteBlackout: (date) => api.delete(`/reservations/blackouts/${date}`),
};

// Floor Plans API
export const floorPlansAPI = {
  getAll: () => api.get('/floor-plans'),
  get: (id) => api.get(`/floor-plans/${id}`),
  create: (data) => api.post('/floor-plans', data),
  update: (id, data) => api.put(`/floor-plans/${id}`, data),
  // Typed-table validation for POS dine-in.
  listTables: () => api.get('/floor-plans/tables/all'),
  occupyByNumber: (number, orderId) => api.post(`/floor-plans/tables/by-number/${encodeURIComponent(number)}/occupy`, null, { params: { order_id: orderId } }),
};

// Coursing API — course assignment, fire/hold config, POS -> kitchen
export const coursingAPI = {
  getConfig: () => api.get('/coursing/config'),
  updateConfig: (data) => api.put('/coursing/config', data),
  sendToKitchen: (data) => api.post('/coursing/send-to-kitchen', data),
  openOrders: (params) => api.get('/coursing/orders/open', { params }),
  addRound: (id, data) => api.post(`/coursing/orders/${id}/add-round`, data),
  settle: (data) => api.post('/coursing/settle', data),
  voidItems: (id, data) => api.post(`/coursing/orders/${id}/void`, data),
  // SSE endpoint — consumed via EventSource, not axios.
  setPrintTarget: (printer, data) => api.put(`/print-targets/${encodeURIComponent(printer)}`, data),
  printHealth: () => api.get('/print-targets/health'),
  printSelfTest: (printer) => api.post(`/print-targets/${encodeURIComponent(printer)}/test`),
  analytics: (days = 7) => api.get('/coursing/analytics', { params: { days } }),
  streamUrl: (tableNumber) =>
    `${API_BASE_URL}/coursing/stream?tableNumber=${encodeURIComponent(tableNumber || '')}`
    + `&token=${encodeURIComponent(localStorage.getItem('nua_token') || '')}`,
  endOfService: () => api.get('/coursing/end-of-service'),
  closeService: (reason) => api.post('/coursing/end-of-service/close', { reason }),
};

// Two-factor sign-in
export const twoFactorAPI = {
  status: () => api.get('/auth/2fa/status'),
  setup: () => api.post('/auth/2fa/setup', {}),
  verify: (code) => api.post('/auth/2fa/verify', { code }),
  disable: (password) => api.post('/auth/2fa/disable', { password }),
  regenerateCodes: (password) => api.post('/auth/2fa/recovery-codes', { password }),
  revokeDevice: (id) => api.delete(`/auth/2fa/devices/${id}`),
  getPolicy: () => api.get('/auth/2fa/policy'),
  setPolicy: (required, roles) => api.post('/auth/2fa/policy', { required, roles }),
};

// Ops: health + recent unhandled-error visibility
export const opsAPI = {
  health: () => api.get('/health'),
  recentErrors: (limit = 50) => api.get('/ops/errors', { params: { limit } }),
  recentClientErrors: (limit = 50) => api.get('/ops/client-errors', { params: { limit } }),
  reportClientError: (payload) => api.post('/ops/client-errors', payload),
};

// Backup / restore
export const backupAPI = {
  download: () => api.get('/ops/backup', { responseType: 'blob' }),
  runDrill: () => api.post('/ops/backup/drill'),
};

// POS layout — structured customization (cart side, tile density, quick actions)
export const posLayoutAPI = {
  get: () => api.get('/pos/layout'),
  save: (data) => api.post('/pos/layout', data),
};

// Waitlist API
export const waitlistAPI = {
  getAll: (params) => api.get('/waitlist', { params }),
  add: (data) => api.post('/waitlist', data),
  update: (id, data) => api.put(`/waitlist/${id}`, data),
  seat: (id, tableId) => api.post(`/waitlist/${id}/seat`, null, { params: { table_id: tableId } }),
  remove: (id) => api.delete(`/waitlist/${id}`),
};

// Kitchen Display (KDS) API
export const kitchenAPI = {
  getOrders: (params) => api.get('/kitchen/orders', { params }),
  createOrder: (data) => api.post('/kitchen/orders', data),
  startOrder: (id) => api.post(`/kitchen/orders/${id}/start`),
  readyOrder: (id) => api.post(`/kitchen/orders/${id}/ready`),
  servedOrder: (id) => api.post(`/kitchen/orders/${id}/served`),
  cancelOrder: (id) => api.post(`/kitchen/orders/${id}/cancel`),
  fireCourse: (id, course) => api.post(`/kitchen/orders/${id}/fire-course/${course}`),
  holdCourse: (id, course) => api.post(`/kitchen/orders/${id}/hold-course/${course}`),
  serveCourse: (id, course) => api.post(`/kitchen/orders/${id}/serve-course/${course}`),
  readyCourse: (id, course) => api.post(`/kitchen/orders/${id}/ready-course/${course}`),
  setPriority: (id, priority) => api.post(`/kitchen/orders/${id}/priority`, null, { params: { priority } }),
  getAvgOrderTime: () => api.get('/kitchen/avg-order-time'),
  getNextOrderETA: () => api.get('/kitchen/next-order-eta'),
  getDocketConfig: () => api.get('/kitchen/docket-config'),
  updateDocketConfig: (data) => api.put('/kitchen/docket-config', data),
};

// Pre-Shift Dashboard API
export const preShiftAPI = {
  getToday: () => api.get('/pre-shift/today'),
};

// AI Command Center API
export const analyticsAPI = {
  getCommandCenter: () => api.get('/analytics/command-center'),
  getMenuEngineering: () => api.get('/analytics/menu-engineering'),
  getTodayPulse: () => api.get('/analytics/today-pulse'),
  getTodayTargets: () => api.get('/analytics/today-targets'),
  saveTodayTargets: (data) => api.post('/analytics/today-targets', data),
};

// Events & Experiences
export const eventsAPI = {
  getAll: (params) => api.get('/events', { params }),
  create: (data) => api.post('/events', data),
  update: (id, data) => api.put(`/events/${id}`, data),
};

// Demand Forecasting
export const forecastAPI = {
  getDemand: () => api.get('/analytics/demand-forecast'),
  getTableTurns: () => api.get('/analytics/table-turns'),
  getSmartRoster: () => api.get('/staff/smart-roster'),
  getSuggestions: () => api.get('/analytics/forecast-suggestions'),
};

// Public Booking Portal
export const publicAPI = {
  getMenu: (business) => api.get('/public/menu', { params: { business } }),
  getAvailableSlots: (date, partySize, business) => api.get('/public/available-slots', { params: { date, party_size: partySize, business } }),
  book: (data, business) => api.post('/public/book', { ...data, business }),
  joinWaitlist: (data, business) => api.post('/public/join-waitlist', { ...data, business }),
  getEvents: (business) => api.get('/public/events', { params: { business } }),
  trackWaitlist: (code) => api.get(`/waitlist/track/${code}`),
  trackWaitlistStreamUrl: (code) => `${API_BASE_URL}/waitlist/track/stream/${encodeURIComponent(code)}`,
};

// QR Payment
export const paymentAPI = {
  generateQR: (data) => api.post('/payments/generate-qr', data),
  confirm: (paymentId) => api.post(`/payments/${paymentId}/confirm`),
};

// Table-Side Ordering (Public)
export const tableOrderAPI = {
  getMenu: (tableId, business) => api.get(`/table/${tableId}/menu`, { params: { business } }),
  placeOrder: (tableId, data, business) => api.post(`/table/${tableId}/order`, data, { params: { business } }),
  getOrders: (tableId, business) => api.get(`/table/${tableId}/orders`, { params: { business } }),
};

// Stripe Checkout
export const stripeAPI = {
  createCheckout: (data) => api.post('/stripe/checkout', data),
  checkStatus: (sessionId) => api.get(`/stripe/checkout/status/${sessionId}`),
};

// Crypto checkout (Bitcoin + USDC via Coinbase Commerce) — same shape as
// stripeAPI above, real hosted-checkout redirect + status poll. Coinbase's
// redirect doesn't echo the charge code back, so the post-redirect page
// polls by orderId instead (checkStatusByOrder) — checkStatus(chargeCode)
// is for callers that already have the charge code some other way.
export const cryptoAPI = {
  createCheckout: (data) => api.post('/crypto/checkout', data),
  checkStatus: (chargeCode) => api.get(`/crypto/checkout/status/${chargeCode}`),
  checkStatusByOrder: (orderId) => api.get(`/crypto/checkout/status-by-order/${orderId}`),
};

// AI outbound voice calls (Twilio) — confirm a booking, remind a guest, or
// read back a custom message over a real phone call.
export const voiceAPI = {
  call: (data) => api.post('/voice/calls', data),
  list: () => api.get('/voice/calls'),
  get: (callId) => api.get(`/voice/calls/${callId}`),
};

// Integrations Hub
export const integrationsAPI = {
  getAll: () => api.get('/integrations'),
  getDetail: (slug) => api.get(`/integrations/${slug}`),
  connect: (slug, data) => api.post(`/integrations/${slug}/connect`, data),
  disconnect: (slug) => api.post(`/integrations/${slug}/disconnect`),
  sync: (slug, syncType = 'sales') => api.post(`/integrations/${slug}/sync`, null, { params: { sync_type: syncType } }),
  getCredentials: (slug) => api.get(`/integrations/${slug}/credentials`),
  getSyncHistory: (provider) => api.get('/integrations/sync-runs/history', { params: provider ? { provider } : {} }),
  getSyncRunDetail: (runId) => api.get(`/integrations/sync-runs/${runId}`),
};

// Advanced Features — Tips, Training Mode, EOD Reports, Email Marketing, AI Insights
export const advancedAPI = {
  addTip: (data) => api.post('/tips/add', data),
  getTips: () => api.get('/tips'),
  getTipsSummary: () => api.get('/tips/summary'),
  getTrainingMode: () => api.get('/settings/training-mode'),
  setTrainingMode: (enabled) => api.post('/settings/training-mode', { enabled }),
  getEndOfDayReport: (params) => api.get('/reports/end-of-day', { params }),
  getTheme: () => api.get('/business/theme'),
  saveTheme: (data) => api.post('/business/theme', data),
  getAIInsights: (data) => api.post('/reports/ai-insights', data),
  getCampaigns: () => api.get('/marketing/campaigns'),
  createCampaign: (data) => api.post('/marketing/campaigns', data),
  sendCampaign: (id) => api.post(`/marketing/campaigns/${id}/send`),
  runCampaignNow: (id) => api.post(`/marketing/campaigns/${id}/run-now`),
  runDueCampaigns: () => api.post('/marketing/campaigns/run-due'),
  deleteCampaign: (id) => api.delete(`/marketing/campaigns/${id}`),
  getCampaignTemplates: () => api.get('/marketing/campaigns/templates'),
  draftCampaign: (data) => api.post('/marketing/campaigns/draft', data),
  improveCampaignCopy: (data) => api.post('/marketing/campaigns/improve', data),
  previewSegment: (rules) => api.post('/marketing/segments/preview', { rules }),
  getSegments: () => api.get('/marketing/segments'),
  createSegment: (data) => api.post('/marketing/segments', data),
  updateSegment: (id, data) => api.put(`/marketing/segments/${id}`, data),
  deleteSegment: (id) => api.delete(`/marketing/segments/${id}`),
  getSegmentCustomers: (id) => api.get(`/marketing/segments/${id}/customers`),
};

// Staff Management — PIN, Timecards, Roster, Payrun
export const staffMgmtAPI = {
  pinLogin: (pin) => api.post('/auth/pin-login', { pin }),
  approvePinLogin: (staffPin, managerPin) => api.post('/auth/pin-login/approve', { staffPin, managerPin }),
  setPin: (staffId, pin) => api.post(`/auth/staff/${staffId}/set-pin`, { pin }),
  clockIn: () => api.post('/staff/clock-in'),
  clockOut: (data) => api.post('/staff/clock-out', data || {}),
  myStatus: () => api.get('/staff/my-status'),
  getPosSessionSettings: () => api.get('/settings/pos-session'),
  savePosSessionSettings: (data) => api.post('/settings/pos-session', data),
  getTimecards: (params) => api.get('/staff/timecards', { params }),
  getRoster: (params) => api.get('/staff/roster', { params }),
  createRosterShift: (data) => api.post('/staff/roster', data),
  updateRosterShift: (id, data) => api.put(`/staff/roster/${id}`, data),
  deleteRosterShift: (id) => api.delete(`/staff/roster/${id}`),
  editTimecard: (id, data) => api.put(`/staff/timecards/${id}`, data),
  requestTimeOff: (data) => api.post('/staff/time-off', data),
  listTimeOff: (params) => api.get('/staff/time-off', { params }),
  approveTimeOff: (id) => api.post(`/staff/time-off/${id}/approve`),
  rejectTimeOff: (id, data) => api.post(`/staff/time-off/${id}/reject`, data || {}),
  cancelTimeOff: (id) => api.delete(`/staff/time-off/${id}`),
  calculatePayrun: (params) => api.get('/payrun/calculate', { params }),
  processPayrun: (data) => api.post('/payrun/process', data),
  getPayrunHistory: () => api.get('/payrun/history'),
  getStaffReports: (params) => api.get('/staff/reports', { params }),
  getReceiptSettings: () => api.get('/receipt/settings'),
  saveReceiptSettings: (data) => api.post('/receipt/settings', data),
};

// Menu Features — AI Import, Price Adjust, What-If Advanced
export const menuFeaturesAPI = {
  aiPreviewMenu: (data) => api.post('/menu/ai-preview', data, { timeout: 90000 }),
  aiCommitMenu: (data) => api.post('/menu/ai-commit', data),
  bulkPriceAdjust: (data) => api.post('/menu/price-adjust', data),
};

// Enterprise Features — Surcharging, Live Sales, Permissions, Reports, Hardware
export const enterpriseAPI = {
  // Surcharging
  getSurchargeSettings: () => api.get('/surcharge/settings'),
  saveSurchargeSettings: (data) => api.post('/surcharge/settings', data),
  checkSurcharge: () => api.get('/surcharge/check'),
  // Auto-gratuity
  getGratuitySettings: () => api.get('/gratuity/settings'),
  saveGratuitySettings: (data) => api.post('/gratuity/settings', data),
  // Live Sales
  getLiveSales: () => api.get('/live-sales'),
  // Permissions
  getAllPermissions: () => api.get('/permissions/all'),
  getPermissionCatalog: () => api.get('/permissions/catalog'),
  getRolePermissions: () => api.get('/permissions/roles'),
  setRolePermissions: (role, permissions) => api.post(`/permissions/roles/${role}`, { permissions }),
  resetRolePermissions: (role) => api.delete(`/permissions/roles/${role}`),
  getStaffPermissions: (staffId) => api.get(`/permissions/staff/${staffId}`),
  setStaffPermissions: (staffId, permissions) => api.post(`/permissions/staff/${staffId}`, { permissions }),
  clearStaffPermissionsOverride: (staffId) => api.delete(`/permissions/staff/${staffId}`),
  // Upsells
  // Reports
  getReportConfig: () => api.get('/reports/automated-config'),
  saveReportConfig: (data) => api.post('/reports/automated-config', data),
  // Hardware
  getPrinters: () => api.get('/hardware/printers'),
  addPrinter: (data) => api.post('/hardware/printers', data),
  deletePrinter: (id) => api.delete(`/hardware/printers/${id}`),
  getScanners: () => api.get('/hardware/scanners'),
  addScanner: (data) => api.post('/hardware/scanners', data),
};

// Gamification — Leaderboard, Smart Tips, Quarterly Review, Print Routing
export const gamificationAPI = {
  getLeaderboard: () => api.get('/staff/leaderboard'),
  smartDistributeTips: () => api.post('/tips/smart-distribute'),
  getQuarterlyReview: () => api.get('/reports/quarterly-review'),
  getAIAlternatives: (items) => api.post('/reports/quarterly-review/ai-alternatives', { items }),
  getPrintRouting: () => api.get('/print-routing/config'),
  savePrintRouting: (data) => api.post('/print-routing/config', data),
  sendToPrinters: (data) => api.post('/print-routing/send', data),
};

// Reservation Features — Table Combos, Booking Rules, Schedule, Experiences, Clubmember, Analytics
export const reservationFeaturesAPI = {
  getTableCombos: () => api.get('/tables/combinations'),
  createTableCombo: (data) => api.post('/tables/combinations', data),
  deleteTableCombo: (id) => api.delete(`/tables/combinations/${id}`),
  getBookingRules: (business) => api.get('/booking/rules', { params: { business } }),
  saveBookingRules: (data) => api.post('/booking/rules', data),
  getBookingSchedule: () => api.get('/booking/schedule'),
  saveBookingSchedule: (shifts) => api.post('/booking/schedule', { shifts }),
  getExperiences: (business) => api.get('/booking/experiences', { params: { business } }),
  createExperience: (data) => api.post('/booking/experiences', data),
  updateExperience: (id, data) => api.put(`/booking/experiences/${id}`, data),
  deleteExperience: (id) => api.delete(`/booking/experiences/${id}`),
  getClubOffers: () => api.get('/clubmember/offers'),
  createClubOffer: (data) => api.post('/clubmember/offers', data),
  updateClubOffer: (id, data) => api.put(`/clubmember/offers/${id}`, data),
  deleteClubOffer: (id) => api.delete(`/clubmember/offers/${id}`),
  getBookingAnalytics: () => api.get('/booking/analytics'),
  getSocialAccounts: () => api.get('/clubmember/social-accounts'),
  addSocialAccount: (data) => api.post('/clubmember/social-accounts', data),
  removeSocialAccount: (id) => api.delete(`/clubmember/social-accounts/${id}`),
};

// Booking Analytics — real reporting layer (channels, time analysis, table
// performance, actual/estimated/unknown revenue, report builder + exports)
export const bookingAnalyticsAPI = {
  getReport: (params) => api.get('/booking-analytics/report', { params }),
  downloadCsv: (params) => api.get('/booking-analytics/report.csv', { params, responseType: 'blob' }),
  downloadPdf: (params) => api.get('/booking-analytics/report.pdf', { params, responseType: 'blob' }),
};

// Loyalty API (enhanced)
export const loyaltyAPI = {
  getTiers: () => api.get('/loyalty/tiers'),
  updateTier: (id, data) => api.put(`/loyalty/tiers/${id}`, data),
  getRewards: () => api.get('/loyalty/rewards'),
  createReward: (data) => api.post('/loyalty/rewards', data),
  updateReward: (id, data) => api.put(`/loyalty/rewards/${id}`, data),
  deleteReward: (id) => api.delete(`/loyalty/rewards/${id}`),
};

// Guest-facing loyalty portal — unauthenticated, phone-only lookup
export const loyaltyGuestAPI = {
  requestCode: (phone) => api.post('/loyalty/v2/guest-lookup/request-code', { phone }),
  lookup: (phone, code, business) => api.post('/loyalty/v2/guest-lookup', { phone, code, business }),
};

// Items System — Categories, Modifiers, Discounts, Comp/Void, Payment Links
export const itemsSystemAPI = {
  getCategories: () => api.get('/categories'),
  createCategory: (data) => api.post('/categories', data),
  updateCategory: (id, data) => api.put(`/categories/${id}`, data),
  deleteCategory: (id) => api.delete(`/categories/${id}`),
  mergeCategory: (sourceId, targetId) => api.post(`/categories/${sourceId}/merge/${targetId}`),
  cleanupLegacyCategories: () => api.post('/categories/cleanup-legacy'),
  getModifiers: () => api.get('/modifiers'),
  createModifier: (data) => api.post('/modifiers', data),
  updateModifier: (id, data) => api.put(`/modifiers/${id}`, data),
  deleteModifier: (id) => api.delete(`/modifiers/${id}`),
  getDiscounts: () => api.get('/discounts'),
  createDiscount: (data) => api.post('/discounts', data),
  updateDiscount: (id, data) => api.put(`/discounts/${id}`, data),
  deleteDiscount: (id) => api.delete(`/discounts/${id}`),
  createCompVoid: (data) => api.post('/comp-void', data),
  getCompVoids: () => api.get('/comp-void'),
  createPaymentLink: (data) => api.post('/payment-links', data),
  getPaymentLinks: () => api.get('/payment-links'),
  deletePaymentLink: (id) => api.delete(`/payment-links/${id}`),
};

// AI Pantry — invoice OCR + insights
export const aiPantryAPI = {
  parseInvoice: (data) => api.post('/ai-pantry/parse-invoice', data),
  applyInvoice: (id, selections) => api.post(`/ai-pantry/apply-invoice/${id}`, { selections }),
  listInvoices: () => api.get('/ai-pantry/invoices'),
  productInsights: () => api.get('/products/insights'),
};

// Inventory + Recipes + BAS / Accounting
export const inventoryAPI = {
  listIngredients: () => api.get('/ingredients'),
  createIngredient: (data) => api.post('/ingredients', data),
  updateIngredient: (id, data) => api.put(`/ingredients/${id}`, data),
  deleteIngredient: (id) => api.delete(`/ingredients/${id}`),
  lowStock: () => api.get('/ingredients/low-stock'),
  getRecipe: (productId) => api.get(`/recipes/product/${productId}`),
  saveRecipe: (productId, data) => api.put(`/recipes/product/${productId}`, data),
  createStockTake: (data) => api.post('/stock-takes', data),
  listStockTakes: () => api.get('/stock-takes'),
  assignInvoiceToStock: (invoiceId, assignments, priceUpdates) => api.post(`/invoices/${invoiceId}/assign-stock`, { assignments, priceUpdates }),
  bas: (params) => api.get('/accounting/bas', { params }),
  basCsv: (params) => api.get('/accounting/bas.csv', { params, responseType: 'blob' }),
};

// Online Ordering — public storefront + owner inbox + AI ETA
export const onlineAPI = {
  businessInfo: (business) => api.get('/online/business', { params: business ? { business } : {} }),
  publicCategories: (business) => api.get('/online/categories', { params: business ? { business } : {} }),
  publicProducts: (business) => api.get('/online/products', { params: business ? { business } : {} }),
  placeOrder: (data) => api.post('/online/orders', data),
  listOrders: (status) => api.get('/online/orders', { params: status ? { status } : {} }),
  updateStatus: (id, data) => api.patch(`/online/orders/${id}/status`, data),
  recomputeEta: (id) => api.post(`/online/orders/${id}/eta`),
  track: (code) => api.get(`/online/orders/track/${code}`),
  // SSE endpoint — consumed via EventSource, not axios.
  trackStreamUrl: (code) => `${API_BASE_URL}/online/orders/track/stream/${encodeURIComponent(code)}`,
  kitchenLoad: () => api.get('/online/kitchen/load'),
  checkVoucher: (code, cart, business) => api.post('/vouchers/public-check', { code, cart }, { params: { business } }),
  checkout: (orderId, originUrl) => api.post('/online/orders/checkout', { orderId, originUrl }),
};

// v17 — Loyalty engine + AI Agent (Ash)
export const loyaltyEngineAPI = {
  getConfig: () => api.get('/loyalty/config'),
  updateConfig: (data) => api.put('/loyalty/config', data),
  getBalance: (customerId) => api.get(`/loyalty/balance/${customerId}`),
};
export const agentAPI = {
  getSegments: () => api.get('/agent/segments'),
  getDecisions: (limit = 100) => api.get('/agent/decisions', { params: { limit } }),
  tick: () => api.post('/agent/tick'),
  // audioBase64: a data: URL as produced by FileReader.readAsDataURL(blob)
  // (same convention v15API.voiceOrder uses — the backend strips the
  // "data:...;base64," prefix itself either way).
  voiceCommand: (audioBase64, mime = 'audio/webm') =>
    api.post('/agent/voice-command', { audioBase64, mime }),
  voiceCommandText: (text) => api.post('/agent/voice-command', { text }),
  voiceCatalog: () => api.get('/agent/voice-catalog'),
};
// Phase E+F — Autonomy config, Phone Agent, POs, A/B tests, Your Usual
export const phaseEFAPI = {
  getAutonomy: () => api.get('/agent/autonomy'),
  updateAutonomy: (data) => api.put('/agent/autonomy', data),
  voiceExtended: (text) => api.post('/agent/voice-extended', { text }),
  tickExtended: () => api.post('/agent/tick-extended'),
  getCalls: () => api.get('/phone-agent/calls'),
  simulateCall: (caller, transcript) => api.post('/phone-agent/simulate', { caller, transcript }),
  getPOs: () => api.get('/purchase-orders'),
  generatePOs: () => api.post('/purchase-orders/generate'),
  updatePO: (id, action) => api.post(`/purchase-orders/${id}/${action}`),
  editPO: (id, items) => api.patch(`/purchase-orders/${id}`, { items }),
  poPdfUrl: (id) => `${process.env.REACT_APP_BACKEND_URL}/api/purchase-orders/${id}/pdf`,
  getABTests: () => api.get('/ab-tests'),
  createABTest: (data) => api.post('/ab-tests', data),
  concludeAB: (id) => api.post(`/ab-tests/${id}/conclude`),
  yourUsual: (customerId) => api.get(`/customers/${customerId}/your-usual`),
};

// Phase E+F Wave 2 — Auto-upsell, Price-tune, Overbooking, Cost coach, Labor forecast, Surge, Voice-to-recipe, Kitchen load
export const aiWave2API = {
  upsell: (cart) => api.post('/ai/upsell', { cart }),
  priceTune: () => api.get('/ai/price-tune'),
  applyPriceTune: (productId, newPrice) => api.post('/ai/price-tune/apply', { productId, newPrice }),
  overbookingCheck: (date, time, partySize) => api.post('/ai/overbooking-check', { date, time, partySize }),
  costCoach: () => api.get('/ai/cost-coach'),
  laborForecast: () => api.get('/ai/labor-forecast'),
  surgeRecs: () => api.get('/ai/surge-recommendations'),
  applySurge: (rules) => api.post('/ai/surge/apply', { rules }),
  activeSurge: () => api.get('/ai/surge/active'),
  voiceRecipe: (text, audioBase64, mime) => api.post('/ai/voice-recipe', { text, audioBase64, mime }),
  listRecipes: () => api.get('/ai/recipes'),
  kitchenLoad: () => api.get('/ai/kitchen-load'),
};

// v25 Suite — Enterprise / AI GM / Profit / Recipes / Franchise / Fraud / etc.
export const v25API = {
  // Must-have
  exceptions: () => api.get('/v25/exceptions'),
  addSite: (data) => api.post('/v25/sites', data),
  hardware: () => api.get('/v25/hardware'),
  disputes: () => api.get('/v25/disputes'),
  openDispute: (data) => api.post('/v25/disputes', data),
  attachEvidence: (id, notes) => api.post(`/v25/disputes/${id}/evidence`, { notes }),
  compareSuppliers: (item) => api.get('/v25/suppliers/compare', { params: { item } }),
  // Should-have
  kioskStart: (data) => api.post('/v25/kiosk/session', data),
  kioskAdd: (sid, item) => api.post(`/v25/kiosk/session/${sid}/add`, { item }),
  kioskSetCourse: (sid, data) => api.post(`/v25/kiosk/session/${sid}/course`, data),
  kioskCheckout: (sid) => api.post(`/v25/kiosk/session/${sid}/checkout`),
  substitute: (productId) => api.post('/v25/substitute', { productId }),
  cfdCurrent: () => api.get('/v25/cfd/current'),
  churnRisk: () => api.get('/v25/recovery/churn-risk'),
  winBack: (customerIds, voucherValue) => api.post('/v25/recovery/win-back', { customerIds, voucherValue }),
  stationReadiness: () => api.get('/v25/station-readiness'),
  marginGuardrails: () => api.get('/v25/margin-guardrails'),
  // Tier 1 — NUA Pro & co
  ashPlan: () => api.get('/v25/ash-pro/plan'),
  ashApprove: (planId, actionIds) => api.post('/v25/ash-pro/approve', { planId, actionIds }),
  profitGuardian: () => api.get('/v25/profit-guardian'),
  digitalTwin: () => api.get('/v25/digital-twin'),
  shiftManager: () => api.get('/v25/shift-manager'),
  autoMarketing: (audience) => api.post('/v25/marketing/auto', { audience }),
  listMarketing: () => api.get('/v25/marketing/auto'),
  sendMarketing: (id, edits) => api.post(`/v25/marketing/auto/${id}/send`, edits || {}),
  holdMarketing: (id, hold) => api.post(`/v25/marketing/auto/${id}/hold`, { hold }),
  // Tier 2
  dynamicRules: () => api.get('/v25/dynamic-pricing'),
  addDynamic: (data) => api.post('/v25/dynamic-pricing', data),
  subPlans: () => api.get('/v25/subscriptions/plans'),
  addSubPlan: (data) => api.post('/v25/subscriptions/plans', data),
  enrollSub: (customerId, planId) => api.post('/v25/subscriptions/enroll', { customerId, planId }),
  subMembers: () => api.get('/v25/subscriptions/members'),
  updateSubMember: (id, data) => api.patch(`/v25/subscriptions/members/${id}`, data),
  cancelSubMember: (id) => api.delete(`/v25/subscriptions/members/${id}`),
  // Gift cards live under v26API now — see below.
  // Tier 3
  upsertRecipe: (data) => api.post('/v25/recipes/upsert', data),
  getRecipe: (pid) => api.get(`/v25/recipes/${pid}`),
  predictiveOrders: () => api.post('/v25/predictive-orders'),
  waste: () => api.get('/v25/waste'),
  logWaste: (data) => api.post('/v25/waste', data),
  wasteInsights: () => api.get('/v25/waste/insights'),
  // Tier 4
  concierge: (message) => api.post('/v25/concierge', { message }),
  reputation: () => api.get('/v25/reputation'),
  respondReview: (reviewId, response) => api.post('/v25/reputation/respond', { reviewId, response }),
  // Tier 5
  franchiseDashboard: () => api.get('/v25/franchise/dashboard'),
  benchmark: () => api.get('/v25/benchmark'),
  fraudDetection: () => api.get('/v25/fraud-detection'),
};

// Licensing & Entitlements
export const licenseAPI = {  me: () => api.get('/license/me'),
  audit: () => api.get('/license/audit'),
  validate: (payload) => api.post('/license/validate', payload),
  onboard: (data) => api.post('/license/onboard', data),
  activateDevice: (data) => api.post('/license/device/activate', data),
  revokeDevice: (deviceId) => api.post('/license/device/revoke', { deviceId }),
  requestAbnChange: (data) => api.post('/license/abn/change-request', data),
  billingRecovery: (returnUrl) => api.post('/license/billing/recovery-link', { returnUrl }),
  forceState: (state, reason) => api.post('/license/dev/force-state', { state, reason }),
};

// v26 Commerce — vouchers, gift cards, events, staff availability, CFD
export const v26API = {
  // Vouchers / coupons
  listVouchers: () => api.get('/v26/vouchers'),
  createVoucher: (data) => api.post('/v26/vouchers', data),
  updateVoucher: (vid, data) => api.patch(`/v26/vouchers/${vid}`, data),
  deleteVoucher: (vid) => api.delete(`/v26/vouchers/${vid}`),
  applyVoucher: (code, cart) => api.post(`/v26/vouchers/${code}/apply`, { cart }),
  // Auto-apply promotions
  applyPromos: (cart, orderType) => api.post('/v26/cart/apply-promos', { cart, orderType }),
  activePromos: () => api.get('/v26/promotions/active-now'),
  // Subscriptions
  updateSubPlan: (id, data) => api.patch(`/v26/subscriptions/plans/${id}`, data),
  deleteSubPlan: (id) => api.delete(`/v26/subscriptions/plans/${id}`),
  // Gift cards
  listGiftCards: (status) => api.get('/v26/gift-cards', { params: status ? { status } : {} }),
  sellGift: (data) => api.post('/v26/gift-cards/sell', data),
  lookupGift: (code) => api.get(`/v26/gift-cards/lookup/${code}`),
  activateGift: (code, data) => api.post(`/v26/gift-cards/${code}/activate`, data || {}),
  redeemGiftPartial: (code, amount, transactionId) => api.post(`/v26/gift-cards/${code}/redeem`, { amount, transactionId }),
  giftTransactions: (code) => api.get(`/v26/gift-cards/${code}/transactions`),
  editGiftCard: (code, data) => api.patch(`/v26/gift-cards/${code}`, data),
  reloadGiftCard: (code, amount, reason) => api.post(`/v26/gift-cards/${code}/reload`, { amount, reason }),
  stopGiftCard: (code, reason) => api.post(`/v26/gift-cards/${code}/stop`, { reason }),
  reactivateGiftCard: (code) => api.post(`/v26/gift-cards/${code}/reactivate`),
  resendGiftCard: (code, email) => api.post(`/v26/gift-cards/${code}/resend`, email ? { email } : {}),
  // Events
  listEvents: (upcomingOnly = false) => api.get('/v26/events', { params: { upcomingOnly } }),
  createEvent: (data) => api.post('/v26/events', data),
  updateEvent: (eid, data) => api.patch(`/v26/events/${eid}`, data),
  bookEvent: (eid, data) => api.post(`/v26/events/${eid}/book`, data),
  eventAiPreview: (date) => api.post('/v26/events/ai-preview', { date }),
  // Staff availability
  getAvailability: (staffId) => api.get(`/v26/staff/${staffId}/availability`),
  setAvailability: (staffId, data) => api.put(`/v26/staff/${staffId}/availability`, data),
  // Roster
  clearRoster: (week) => api.post('/v26/roster/clear-all', { week }),
  syncRoster: () => api.post('/v26/roster/sync-staff'),
  // CFD enriched
  cfdEnriched: () => api.get('/v26/cfd/enriched'),
  cfdPush: (data) => api.post('/v26/cfd/push', data),
};
export const v15API = {
  getBadges: () => api.get('/dock/badges'),
  // Tabs (hold/recall)
  getTabs: () => api.get('/pos/tabs'),
  createTab: (data) => api.post('/pos/tabs', data),
  deleteTab: (id) => api.delete(`/pos/tabs/${id}`),
  updateTab: (id, data) => api.put(`/pos/tabs/${id}`, data),
  mergeTabs: (id, otherTabId) => api.post(`/pos/tabs/${id}/merge`, { otherTabId }),
  splitTab: (id, ways, tableNumbers) => api.post(`/pos/tabs/${id}/split`, { ways, tableNumbers }),
  // Favorites
  // Variants
  // CSV import
  // Voice POS
  voiceOrder: (audioBase64, mime) => api.post('/pos/voice-order', { audioBase64, mime }),
  openDrawer: (data) => api.post('/pos/open-drawer', data),
  getDrawerEvents: () => api.get('/pos/drawer-events'),
  // Ask NUA
  // Item image gen
  // Anomalies
  getAnomalies: () => api.get('/analytics/inventory-anomalies'),
  // Auto-roster
  autoRoster: (weekStart) => api.post('/staff/auto-roster', { weekStart }),
  commitAutoRoster: (shifts) => api.post('/staff/roster/commit-auto', { shifts }),
  getRosteringSettings: () => api.get('/staff/rostering-settings'),
  updateRosteringSettings: (data) => api.put('/staff/rostering-settings', data),
  // Shift swap
  getSwaps: () => api.get('/staff/shift-swaps'),
  createSwap: (data) => api.post('/staff/shift-swaps', data),
  approveSwap: (id) => api.post(`/staff/shift-swaps/${id}/approve`),
  rejectSwap: (id) => api.post(`/staff/shift-swaps/${id}/reject`),
  // Heatmap & cohort
  getBookingHeatmap: () => api.get('/analytics/booking-heatmap'),
  getCohortRetention: () => api.get('/analytics/cohort-retention'),
  // 2FA
  setup2FA: () => api.post('/auth/2fa/setup'),
  verify2FA: (code) => api.post('/auth/2fa/verify', { code }),
  disable2FA: () => api.post('/auth/2fa/disable'),
  // GDPR
  gdprExport: (customerId) => api.get(`/customers/${customerId}/gdpr-export`),
  gdprErase: (customerId) => api.delete(`/customers/${customerId}/gdpr-erase`),
  // BAS e-file
  // i18n
  getLabels: (lang) => api.get(`/i18n/labels/${lang}`),
};

// ============ Social Media Marketing ============
export const socialAPI = {
  listAccounts: () => api.get('/social/accounts'),
  connectAccount: (data) => api.post('/social/accounts', data),
  disconnectAccount: (id) => api.delete(`/social/accounts/${id}`),
  listPosts: (params = {}) => api.get('/social/posts', { params }),
  createPost: (data) => api.post('/social/posts', data),
  updatePost: (id, data) => api.patch(`/social/posts/${id}`, data),
  deletePost: (id) => api.delete(`/social/posts/${id}`),
  publishPost: (id) => api.post(`/social/posts/${id}/publish`),
  duplicatePost: (id, data = {}) => api.post(`/social/posts/${id}/duplicate`, data),
  aiGenerate: (data) => api.post('/social/ai-generate', data),
  aiWeeklyPlan: (data) => api.post('/social/ai-weekly-plan', data),
  getPlanJob: (planId) => api.get(`/social/plan-jobs/${planId}`),
  bestTimes: () => api.get('/social/best-times'),
  listPlatforms: () => api.get('/social/platforms'),
};

// ── Superannuation (Fair Work compliant) ────────────────────────────────
export const superAPI = {
  rate: (payDate) => api.get('/super/rate', { params: payDate ? { payDate } : {} }),
  calc: (body) => api.post('/super/calc', body),
  commitWeeklyRun: (body) => api.post('/super/weekly-runs', body),
  listWeeklyRuns: (params = {}) => api.get('/super/weekly-runs', { params }),
  markPaid: (id, data) => api.patch(`/super/weekly-runs/${id}`, data),
  summary: (fy) => api.get('/super/summary', { params: fy ? { fy } : {} }),
};

// ── Temperature Monitoring ──────────────────────────────────────────────
export const temperatureAPI = {
  brands: () => api.get('/temperature/brands'),
  listDevices: () => api.get('/temperature/devices'),
  createDevice: (data) => api.post('/temperature/devices', data),
  updateDevice: (id, data) => api.patch(`/temperature/devices/${id}`, data),
  deleteDevice: (id) => api.delete(`/temperature/devices/${id}`),
  rotateSecret: (id) => api.post(`/temperature/devices/${id}/rotate-secret`),
  logReading: (data) => api.post('/temperature/readings', data),
  listReadings: (params) => api.get('/temperature/readings', { params }),
  listAlerts: (params) => api.get('/temperature/alerts', { params }),
  ackAlert: (id) => api.post(`/temperature/alerts/${id}/acknowledge`),
  report: (params) => api.get('/temperature/report', { params }),
  scanMissing: () => api.post('/temperature/scan-missing'),
};

// ── Table Courses / Send-nudge ──────────────────────────────────────────
export const tableCoursesAPI = {
  updateSettings: (data) => api.put('/table-courses/settings', data),
  listStates: () => api.get('/table-courses/states'),
  upsertState: (data) => api.post('/table-courses/states', data),
  send: (data) => api.post('/table-courses/send', data),
};

// ── Finalize batch (v27.7): pre-shift, day rules, marketing analytics,
// channel controls, digital wallet, PDF exports, automation triggers ─────
export const finalizeAPI = {
  preShiftBriefing: () => api.get('/preshift/briefing'),
  marketingAnalytics: (days = 30) => api.get('/marketing/analytics', { params: { days } }),
  channelStates: () => api.get('/channels/state'),
  updateChannelState: (data) => api.post('/channels/state', data),
  getChannelSchedule: (channel) => api.get(`/channels/${channel}/schedule`),
  saveChannelSchedule: (channel, data) => api.post(`/channels/${channel}/schedule`, data),
  channelEffectiveStatus: (channel) => api.get(`/channels/${channel}/effective-status`),
  guestWallet: (customerId) => api.get(`/customers/${customerId}/wallet`),
  guestWalletApplePkpassUrl: (customerId) => `${process.env.REACT_APP_BACKEND_URL}/api/customers/${customerId}/wallet/apple.pkpass`,
  guestWalletGoogle: (customerId) => api.get(`/customers/${customerId}/wallet/google`),
  gmbSync: (locationId) => api.post(`/locations/${locationId}/gmb-sync`),

  // Payroll (Australian compliance)
  payrunCalculate: (data) => api.post('/payroll/payrun/calculate', data),
  payrunCommit: (data) => api.post('/payroll/payrun/commit', data),
  payrollRegister: (days = 90) => api.get(`/payroll/register?days=${days}`),
  rosterCompliance: (daysAhead = 14) => api.get(`/payroll/roster-compliance?days_ahead=${daysAhead}`),
  payrollYtd: (staffId) => api.get(`/payroll/ytd/${staffId}`),
  payslipPdf: (runId, staffId) => api.get(`/payroll/payslip/${runId}/${staffId}/pdf`, { responseType: 'blob' }),

  // Wallet credentials
  walletCredentialsStatus: () => api.get('/settings/wallet-credentials'),
  walletCredentialsSave: (data) => api.post('/settings/wallet-credentials', data),

  // AI Bundle Discovery (market-basket)
  bundleSuggestions: (days = 30) => api.get(`/v26/promotions/bundle-suggestions?days=${days}`),

  // BAS worksheet (G1-G20, W1-W5, T1)
  basWorksheet: (start, end) => api.get(`/bas-gst/worksheet?period_start=${start}&period_end=${end}`),

  // ── v29 · Customer Commerce Platform ─────────────────────────
  // Universal Voucher Engine
  issueVoucher: (data) => api.post('/vouchers', data),
  bulkVoucher: (data) => api.post('/vouchers/bulk', data),
  listVouchers: (params = {}) => api.get('/vouchers', { params }),
  validateVoucher: (data) => api.post('/vouchers/validate', data),
  revokeVoucher: (id, reason) => api.post(`/vouchers/${id}/revoke`, { reason }),

  // Unified Wallet
  walletGet: (customerId) => api.get(`/wallet/${customerId}`),
  walletTimeline: (customerId) => api.get(`/wallet/${customerId}/timeline`),

  // Flexible Refunds
  createRefund: (data) => api.post('/refunds/flexible', data),

  // AI Promotion Builder
  aiPromotionGoal: (goal) => api.post('/ai/promotion-goal', { goal }),

  // Promotion Analytics
  promoAnalytics: (days = 30) => api.get(`/promo-analytics/summary?days=${days}`),

  // Loyalty 2.0
  loyaltyStatus: (customerId) => api.get(`/loyalty/status/${customerId}`),

  // AI Personalisation
  personalisation: (customerId) => api.get(`/personalisation/${customerId}`),

  // Gift Card 2.0
};

// NUA — daily briefing, insights, agent chat (AI surface reused by the Owner Dashboard app)
export const nuaAPI = {
  getBriefing: (force) => api.get('/nua/briefing', { params: force ? { force: true } : {} }),
  regenerateBriefing: () => api.post('/nua/briefing/regenerate'),
  getInsights: (limit = 50) => api.get(`/nua/insights?limit=${limit}`),
  getHealthScore: () => api.get('/nua/health-score'),
};

// Multi-Business / Multi-Tenant — create/list/edit businesses, tenant data
// export, and the one-time businessId backfill migration for pre-tenancy data
export const businessAPI = {
  create: (data) => api.post('/business/create', data),
  list: () => api.get('/business/list'),
  get: (id) => api.get(`/business/${id}`),
  update: (id, data) => api.put(`/business/${id}`, data),
  summary: (id) => api.get(`/business/${id}/summary`),
  exportData: (id, collection) => api.get(`/business/${id}/export`, { params: collection ? { collection } : {} }),
  backfillTenant: () => api.post('/business/backfill-tenant'),
  purgeDemoData: () => api.post('/business/purge-demo-data', { confirm: 'PURGE' }),
  setupStatus: (id) => api.get(`/business/${id}/setup-status`),
};

// Customer Identity — the free base layer + per-add-on entitlements
// (bookings-guests, loyalty, punch-card, marketing). Every checkout and
// booking already writes into this layer; this is its admin surface.
export const identityAPI = {
  getEntitlements: () => api.get('/identity/entitlements'),
  setEntitlements: (data) => api.put('/identity/entitlements', data),
  search: (search) => api.get('/identity/customers', { params: search ? { search } : {} }),
  getCustomer: (id) => api.get(`/identity/customers/${id}`),
  migrateLegacyCrm: () => api.post('/identity/migrate-legacy-crm'),
};

// Passwordless guest identity — one verified phone session any guest-facing
// surface (booking, waitlist, online ordering) can use to prefill forms
// instead of asking a returning guest to re-type their details every time.
export const guestSessionAPI = {
  requestCode: (phone) => api.post('/guest/session/request-code', { phone }),
  verify: (phone, code, business) => api.post('/guest/session/verify', { phone, code, business }),
  me: (token) => api.get('/guest/session/me', { headers: { Authorization: `Bearer ${token}` } }),
};

// Guest-facing bill splitting — a table's open items become individually
// claimable, paid by each guest on their own phone via guestSessionAPI's
// phone-verified session. View/mode calls need no guest identity; claim/
// release/checkout do, and take the guest token explicitly (never the
// staff session) since this runs on a guest's own device.
export const billSplitAPI = {
  getSplit: (tableNumber, business) => api.get(`/table/${encodeURIComponent(tableNumber)}/split`, { params: { business } }),
  chooseMode: (tableNumber, mode, equalCount, { customAmounts, customPercents, business } = {}) =>
    api.post(`/table/${encodeURIComponent(tableNumber)}/split/mode`,
      { mode, equalCount, customAmounts, customPercents }, { params: { business } }),
  status: (splitId) => api.get(`/table/split/${splitId}/status`),
  claim: (splitId, lineIds, token) =>
    api.post(`/table/split/${splitId}/claim`, { lineIds }, { headers: { Authorization: `Bearer ${token}` } }),
  claimEqual: (splitId, index, token) =>
    api.post(`/table/split/${splitId}/claim-equal`, { index }, { headers: { Authorization: `Bearer ${token}` } }),
  release: (splitId, { lineIds, slotIndex }, token) =>
    api.post(`/table/split/${splitId}/release`, { lineIds, slotIndex }, { headers: { Authorization: `Bearer ${token}` } }),
  checkout: (splitId, { provider, lineIds, slotIndex, originUrl, tipAmount, email }, token) =>
    api.post(`/table/split/${splitId}/checkout`, { provider, lineIds, slotIndex, originUrl, tipAmount, email },
      { headers: { Authorization: `Bearer ${token}` } }),
};

// What's New — release notes for owners/managers
export const changelogAPI = {
  list: (window) => api.get('/changelog', { params: window ? { window } : {} }),
  upcoming: () => api.get('/changelog/upcoming'),
  summary: () => api.get('/changelog/summary'),
};

export const repoSyncAPI = {
  status: (limit = 10) => api.get('/repo-sync/status', { params: { limit } }),
  run: () => api.post('/repo-sync/run'),
};

export default api;
