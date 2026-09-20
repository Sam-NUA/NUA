import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Search, Plus, Minus, Trash2, User, CreditCard, Banknote, Smartphone,
  ShoppingCart, QrCode, SplitSquareHorizontal, X, Check, ChevronLeft, Copy, DollarSign,
  Percent, Ban, Gift, ArrowRightLeft, Combine, Clock
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle
} from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { usePOS } from '../contexts/POSContext';
import { productsAPI, promotionsAPI, customersAPI, transactionsAPI, paymentAPI, stripeAPI, cryptoAPI, advancedAPI, menuFeaturesAPI, gamificationAPI, v15API, loyaltyEngineAPI, phaseEFAPI, aiWave2API, v26API, floorPlansAPI, itemsSystemAPI, kitchenAPI, coursingAPI, posLayoutAPI, finalizeAPI } from '../services/api';
import { useToast } from '../hooks/use-toast';
import { useAuth } from '../contexts/AuthContext';
import VoiceOrderButton from '../components/VoiceOrderButton';
import SwipeableCartItem from '../components/pos/SwipeableCartItem';
import CustomerCombobox from '../components/pos/CustomerCombobox';
import { QrPaymentDialog, UpiPaymentDialog, SplitPaymentDialog, SplitBillLinkDialog } from '../components/pos/PaymentDialogs';
import ModifierPanel from '../components/pos/ModifierPanel';
import POSHeaderBar from '../components/pos/POSHeaderBar';
import ScanVoucherButton from '../components/pos/ScanVoucherButton';
import TableNumberField from '../components/pos/TableNumberField';
import { CourseHeader, SendToKitchenBar, ReadyBanner, SeatPicker } from '../components/pos/CourseControls';
import { validateTable } from '../lib/tableNumber';
import { readableTextColor } from '../lib/contrast';
import { groupCartByCourse, showCourseUI, courseKeys, courseLabel, lineCourse,
         readyCourses, seatOptions, seatsEnabled } from '../lib/coursing';
import { CategoryIcon } from './Categories';
import { createTransactionResilient, courseActionResilient, cacheCatalogue, getCachedCatalogue, isNetworkFailure } from '../lib/offlineQueue';
import { subscribeTickets, streamHealthy } from '../lib/ticketStream';
import useOfflineQueue from '../hooks/useOfflineQueue';
import { WifiOff } from 'lucide-react';

// SwipeableCartItem and CustomerCombobox now live in components/pos/.

const POSTerminal = () => {
  const { theme } = useTheme();
  const { queuedCount, refresh: refreshOfflineQueue } = useOfflineQueue();
  const { user, hasPermission } = useAuth();
  const { cart, addToCart, removeFromCart, updateQuantity, updateCartItemModifiers, clearCart, calculateTotal, selectedCustomer, setSelectedCustomer, currentUser, currentLocation, appliedDiscounts, addDiscount, removeDiscount, appliedGiftCards, addGiftCard, removeGiftCard, pendingGiftActivations, storeCreditApplied, setStoreCreditApplied } = usePOS();
  const { toast } = useToast();
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [products, setProducts] = useState([]);
  const [promotions, setPromotions] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(false);
  // Per-cart idempotency keys for handleStripeCheckout/handleCryptoCheckout
  // — persisted across a manual retry of the same cart so the backend can
  // dedup and avoid creating a second live checkout session (see
  // services/payment_idempotency.py), and regenerated when the total
  // actually changes so a genuinely different cart isn't deduped away.
  const stripeIdemRef = useRef({ key: null, total: null });
  const cryptoIdemRef = useRef({ key: null, total: null });
  const [trainingMode, setTrainingMode] = useState(false);
  // Cart / staff side-panel tabs — the second tab surfaces the logged-in
  // staff member's own quick actions: cash drawer, discounts, comp/void,
  // move/merge/split table, and a quick kitchen-timing readout.
  const [cartTab, setCartTab] = useState('cart');
  const [drawerReason, setDrawerReason] = useState('change');
  const [drawerNote, setDrawerNote] = useState('');
  const [drawerBusy, setDrawerBusy] = useState(false);
  const [drawerHistory, setDrawerHistory] = useState([]);
  const [kitchenEta, setKitchenEta] = useState(null);
  const [showCompVoidQuick, setShowCompVoidQuick] = useState(false);
  const [compVoidForm, setCompVoidForm] = useState({ type: 'comp', reason: '', amount: '', printVoid: false });
  const [compVoidBusy, setCompVoidBusy] = useState(false);
  const [tablesDialogMode, setTablesDialogMode] = useState('view'); // view | move | merge | split
  const [movingTab, setMovingTab] = useState(null);
  const [moveTargetTable, setMoveTargetTable] = useState('');
  const [mergeSelection, setMergeSelection] = useState([]);
  const [splittingTab, setSplittingTab] = useState(null);
  const [splitWays, setSplitWays] = useState(2);

  // Payment flow state
  const [paymentView, setPaymentView] = useState('methods'); // methods | qr | upi | split | processing
  const [splitLinkOpen, setSplitLinkOpen] = useState(false);
  const [showPayment, setShowPayment] = useState(false);

  // QR / UPI state
  const [qrData, setQrData] = useState(null);

  // Split payment state
  const [splitMode, setSplitMode] = useState('equal'); // equal | custom | items | seat
  const [splitCount, setSplitCount] = useState(2);
  const [splitParts, setSplitParts] = useState([]);
  // "By item" split: which guest each unit of each cart line is assigned to —
  // { [cartLineId]: { [guestIdx]: qty } }. Whatever's left unassigned is
  // spread evenly, same fallback initSeatSplitParts uses, so the parts always
  // balance even mid-assignment.
  const [itemAssignments, setItemAssignments] = useState({});
  const [activeSplitIndex, setActiveSplitIndex] = useState(null);
  // When a split part uses QR/UPI, we surface a scan dialog instead of silently
  // confirming — the cashier confirms once the guest actually pays.
  const [splitQrData, setSplitQrData] = useState(null);   // {qrData, transactionId, method, ...}
  const [splitQrView, setSplitQrView] = useState(null);   // 'qr' | 'upi' | null

  // Cash payment state
  const [cashTendered, setCashTendered] = useState(0);
  const [showCashChange, setShowCashChange] = useState(false);

  const [lastTxnId, setLastTxnId] = useState(null);

  // v15: Tabs (Hold/Recall), Loyalty preview, BNPL, Multi-lang
  const [showTabsDialog, setShowTabsDialog] = useState(false);
  const [openTabs, setOpenTabs] = useState([]);
  // Sales auto-held right before a redirect to Stripe/Coinbase (see
  // handleStripeCheckout/handleCryptoCheckout) that the guest never
  // completed — surfaced as a banner so backing out of a hosted checkout
  // doesn't just silently lose the sale. Checked on every mount, which
  // covers the actual bug: a browser Back press after leaving for Stripe
  // is a fresh load of this page, not a route the app can catch via a URL
  // param the way payment-success can.
  const [heldCheckoutTabs, setHeldCheckoutTabs] = useState([]);
  // Send-to-table flow: opens a floor picker so the server can attach the
  // current cart to a specific table as an open tab (defers payment).
  const [sendToTableOpen, setSendToTableOpen] = useState(false);
  const [floorTables, setFloorTables] = useState([]);
  // False until we know the venue has drawn a floor plan. While false the
  // typed table number is accepted as-is, so a venue mid-setup can still sell.
  const [floorConfigured, setFloorConfigured] = useState(false);
  const [sendingToTable, setSendingToTable] = useState(false);
  const [labels, setLabels] = useState({});
  // v17: Points-and-Pay
  const [pointsBalance, setPointsBalance] = useState(null);
  // Customer wallet: store credit + active vouchers + occasion offers
  const [wallet, setWallet] = useState(null);
  // Category "More" overflow panel open state
  const [showMoreCats, setShowMoreCats] = useState(false);
  const [pointsToRedeem, setPointsToRedeem] = useState(0);
  const [loyaltyCfg, setLoyaltyCfg] = useState({ minRedeem: 10, redeemRate: 0.01 });

  // Wave 2: AI Upsell suggestions
  const [upsells, setUpsells] = useState([]);
  const [upsellLoading, setUpsellLoading] = useState(false);

  // Your Usual — predictive items per known customer
  const [yourUsual, setYourUsual] = useState([]);

  // Voucher / coupon manual entry
  const [voucherCode, setVoucherCode] = useState('');
  const [voucherLoading, setVoucherLoading] = useState(false);
  const [showDiscountPicker, setShowDiscountPicker] = useState(false);
  const [availableVouchers, setAvailableVouchers] = useState([]);
  const [universalVouchers, setUniversalVouchers] = useState([]);

  // Gift-card tender
  const [giftCodeInput, setGiftCodeInput] = useState('');
  const [giftLoading, setGiftLoading] = useState(false);

  // Order context: table # / takeaway / walk-in customer name
  const [orderType, setOrderType] = useState('dine-in'); // dine-in | takeaway
  const [tableNumber, setTableNumber] = useState('');
  const [walkInName, setWalkInName] = useState('');

  // Active promotions (only currently-live ones for staff context)
  const [activePromos, setActivePromos] = useState([]);
  // Collapsed category sections in the "All" grouped view
  const [collapsedCats, setCollapsedCats] = useState([]);

  // Categories with icons + colors (kept as full objects, not just names)
  const [categories, setCategories] = useState([{ id: 'all', name: 'All', icon: 'Sparkles', color: '#6366f1' }]);
  // Set only when the menu currently on screen came from the offline cache
  // rather than a live fetch — null the rest of the time.
  const [offlineMenu, setOfflineMenu] = useState(null);
  // Structured layout customization (Settings > POS Layout) — cart side,
  // tile density, which quick actions show. Not free-form positioning: see
  // components/settings/POSLayoutSettings.jsx for why.
  const [posLayout, setPosLayout] = useState({
    cartPosition: 'right', tileSize: 'comfortable', quickActions: { hold: true, tabs: true },
  });

  // Modifier definitions (loaded once); ModifierSheet state for click-to-add flow
  const [modifiers, setModifiers] = useState([]);
  const [modifierSheetProduct, setModifierSheetProduct] = useState(null);
  // Set when the panel was opened by tapping an EXISTING cart line rather than
  // a product tile — routes onConfirm to update that line instead of adding
  // a new one, and carries its current selections in to pre-fill the picker.
  const [editingLineId, setEditingLineId] = useState(null);

  // Smart add-to-cart: if a product has modifierIds, open the picker first.
  // If modifier defs haven't loaded yet but the product has modifierIds,
  // still open the sheet (it will show a loading hint) rather than silently
  // skipping the selection step.
  const handleProductClick = useCallback((product) => {
    if (product.eightySixed) return;
    if ((product.modifierIds || []).length > 0) {
      setModifierSheetProduct(product);
    } else {
      addToCart(product);
    }
  }, [addToCart]);

  // Tapped an existing cart line that has modifiers — open the same panel,
  // pre-filled with what's already selected, so it can be changed in place.
  const handleEditCartModifiers = useCallback((item) => {
    setEditingLineId(item.id);
    // basePrice (not price, which already has the old extras baked in) so the
    // panel's running total doesn't double-count the item's current modifiers.
    setModifierSheetProduct({ ...item, price: item.basePrice ?? item.price });
  }, []);

  // Map a cart line into a backend TransactionItem (flattens selectedModifiers
  // → modifiers list of {modifierId, modifierName, optionId, optionName, price}).
  const toTxItem = useCallback((item, includeCategory = false) => {
    const modifiersFlat = (item.selectedModifiers || []).flatMap(sm =>
      (sm.options || []).map(o => ({
        modifierId: sm.modifierId,
        modifierName: sm.modifierName,
        optionId: o.name,
        optionName: o.name,
        price: o.price || 0,
      }))
    );
    const out = {
      productId: item.productId || item.id,
      productName: item.name,
      quantity: item.quantity,
      price: item.price,
      modifiers: modifiersFlat,
    };
    if (includeCategory) out.category = item.category;
    return out;
  }, []);

  useEffect(() => { fetchData(); }, []);
  useEffect(() => { posLayoutAPI.get().then(r => setPosLayout(r.data)).catch(() => {}); }, []);

  // Detect a sale abandoned mid-Stripe/Crypto-checkout — see
  // handleStripeCheckout/handleCryptoCheckout for how these tabs get
  // created. Checked on mount (a Back press after leaving for a hosted
  // checkout is a fresh load of /pos) and again on `pageshow` — some
  // browsers restore this page from the back/forward cache on Back rather
  // than remounting it, which a mount-only effect would miss entirely.
  const loadHeldCheckouts = useCallback(async () => {
    try {
      const r = await v15API.getTabs();
      setHeldCheckoutTabs((r.data || []).filter(t => t.autoHold));
    } catch { /* best-effort — don't block the terminal loading over this */ }
  }, []);
  useEffect(() => {
    loadHeldCheckouts();
    const onPageShow = () => loadHeldCheckouts();
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, [loadHeldCheckouts]);

  const resumeHeldCheckout = async (tab) => {
    if (cart.length > 0) {
      const proceed = window.confirm('This will replace the current cart with the held sale. Continue?');
      if (!proceed) return;
    }
    clearCart();
    (tab.cart || []).forEach(i => { for (let n = 0; n < i.quantity; n++) addToCart({ ...i }); });
    if (tab.selectedCustomer) setSelectedCustomer(tab.selectedCustomer);
    try { await v15API.deleteTab(tab.id); } catch {}
    setHeldCheckoutTabs(prev => prev.filter(t => t.id !== tab.id));
    toast({ title: 'Held sale resumed', description: 'Pick a payment method to finish it.' });
  };

  const cancelHeldCheckout = async (tab) => {
    const proceed = window.confirm(
      `Cancel this held sale? If the guest still completes the ${tab.checkoutProvider === 'crypto' ? 'crypto' : 'Stripe'} `
      + `payment from a re-opened link, it will still ring up automatically — this only clears the hold on this screen.`
    );
    if (!proceed) return;
    try { await v15API.deleteTab(tab.id); } catch {}
    setHeldCheckoutTabs(prev => prev.filter(t => t.id !== tab.id));
    toast({ title: 'Hold cancelled' });
  };

  // Floor plan tables, loaded once up front so dine-in table entry can be
  // validated as the server types instead of only when they open the picker.
  const loadFloorTables = useCallback(async () => {
    try {
      const r = await floorPlansAPI.listTables();
      setFloorTables(r.data?.tables || []);
      setFloorConfigured(!!r.data?.configured);
    } catch {
      // Older backend or offline: leave validation off rather than block sales.
      setFloorTables([]);
      setFloorConfigured(false);
    }
  }, []);
  useEffect(() => { loadFloorTables(); }, [loadFloorTables]);

  // Live validity of the typed dine-in table. `unknown` blocks checkout.
  const tableCheck = validateTable(tableNumber, floorTables, floorConfigured);
  const tableBlocked = orderType === 'dine-in' && tableCheck.status === 'unknown';

  // ── Coursing ──────────────────────────────────────────────────────────
  // Off by default. A takeaway-only venue never enables it and so never sees
  // a course selector, a Send-to-Kitchen bar, or Fire/Hold buttons.
  const [coursingConfig, setCoursingConfig] = useState(null);
  const [kitchenOrder, setKitchenOrder] = useState(null);   // set once sent
  const [coursingBusy, setCoursingBusy] = useState(false);
  const [courseOverrides, setCourseOverrides] = useState({}); // lineId -> course
  const [seatOverrides, setSeatOverrides] = useState({});     // lineId -> seat
  // How much of each cart line has already gone to the kitchen, keyed by line
  // id. Tracking the *quantity* rather than just "sent" matters: bumping a
  // line from 1 to 3 after sending is two more dishes the kitchen never heard
  // about, and only the difference should be added to the ticket.
  const [sentQty, setSentQty] = useState({});

  useEffect(() => {
    coursingAPI.getConfig()
      .then(r => setCoursingConfig(r.data || null))
      .catch(() => setCoursingConfig(null));   // older backend: feature stays off
  }, []);

  const coursingOn = showCourseUI(orderType, coursingConfig);
  const useSeats = seatsEnabled(coursingConfig);
  const seats = seatOptions(coursingConfig);

  // Apply any per-line course/seat the server picked on top of the defaults.
  const cartWithCourses = cart.map(i => ({
    ...i,
    ...(courseOverrides[i.id] != null ? { course: courseOverrides[i.id] } : {}),
    ...(seatOverrides[i.id] != null ? { seat: seatOverrides[i.id] } : {}),
  }));
  const courseGroups = coursingOn ? groupCartByCourse(cartWithCourses, coursingConfig) : [];
  // Only the un-sent portion of each line is outstanding.
  const pendingLines = cartWithCourses
    .map(i => ({ ...i, quantity: (i.quantity || 0) - (sentQty[i.id] || 0) }))
    .filter(i => i.quantity > 0);
  const pendingCount = pendingLines.reduce((n, i) => n + i.quantity, 0);
  const ready = coursingOn ? readyCourses(kitchenOrder, coursingConfig) : [];

  // An emptied cart drops the per-line state, but NOT the attached ticket:
  // after a refresh the cart is empty while the table still has live courses,
  // and clearing here would immediately undo the reattach below.
  useEffect(() => {
    if (cart.length === 0) { setCourseOverrides({}); setSeatOverrides({}); setSentQty({}); }
  }, [cart.length]);

  // Reattach to whatever ticket the kitchen already has for this table, so a
  // refresh — or picking the table up on a second tablet — can still fire
  // courses instead of being stranded without a ticket reference.
  //
  // Changing table drops the previous ticket first, in the same effect, so
  // table 12's courses can't linger on screen while the server rings up 14.
  useEffect(() => {
    setKitchenOrder(null);
    setSentQty({});
    if (!coursingOn || tableCheck.status !== 'ok') return undefined;
    let cancelled = false;
    coursingAPI.openOrders({ tableNumber })
      .then(r => { if (!cancelled) setKitchenOrder((r.data || [])[0] || null); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [coursingOn, tableNumber, orderType, tableCheck.status]);

  // Live ticket updates over one shared stream for the whole browser — see
  // lib/ticketStream. A connection per table would blow past the browser's
  // six-per-origin cap on a busy floor and silently stop delivering. A slow
  // poll stays as a fallback for proxies that buffer SSE.
  useEffect(() => {
    if (!kitchenOrder?.id || !coursingOn) return undefined;
    const id = kitchenOrder.id;
    const table = kitchenOrder.tableNumber || '';

    const unsubscribe = subscribeTickets((rows) => {
      const fresh = (rows || []).find(o => o.id === id);
      if (fresh) setKitchenOrder(fresh);
    });

    const poll = setInterval(async () => {
      if (streamHealthy()) return;           // the stream is doing the work
      try {
        const r = await coursingAPI.openOrders({ tableNumber: table || undefined });
        const fresh = (r.data || []).find(o => o.id === id);
        if (fresh) setKitchenOrder(fresh);
      } catch {}
    }, 15000);

    return () => { unsubscribe(); clearInterval(poll); };
  }, [kitchenOrder?.id, kitchenOrder?.tableNumber, coursingOn]);

  const setLineCourse = (lineId, course) =>
    setCourseOverrides(prev => ({ ...prev, [lineId]: course }));
  const setLineSeat = (lineId, seat) =>
    setSeatOverrides(prev => ({ ...prev, [lineId]: seat }));

  const toKitchenItem = (i) => ({
    productId: i.productId || i.id, productName: i.name, quantity: i.quantity,
    category: i.category, notes: i.notes || null,
    modifiers: i.selectedModifiers || [],
    course: lineCourse(i, coursingConfig),
    seat: useSeats ? (i.seat ?? null) : null,
  });

  const sendCartToKitchen = async (straightFire = false) => {
    if (coursingBusy) return;
    // Only the lines not already on the ticket go up — re-sending the whole
    // cart would double every dish the kitchen is already cooking.
    const outgoing = kitchenOrder ? pendingLines : cartWithCourses;
    if (!outgoing.length) return;
    if (tableBlocked) {
      toast({ title: 'Unknown table', description: tableCheck.message, variant: 'destructive' });
      return;
    }
    setCoursingBusy(true);
    try {
      const payload = {
        items: outgoing.map(toKitchenItem),
        // Survives the offline queue, so a replay of a request whose response
        // was lost returns the existing ticket instead of doubling the order.
        clientKey: (typeof crypto !== 'undefined' && crypto.randomUUID)
          ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        orderType, straightFire,
        tableNumber: orderType === 'dine-in' ? tableNumber : null,
        guestName: orderType === 'takeaway' ? walkInName : (selectedCustomer?.name || null),
      };
      const r = kitchenOrder
        ? await courseActionResilient('addRound', { orderId: kitchenOrder.id, payload },
            () => coursingAPI.addRound(kitchenOrder.id, payload))
        : await courseActionResilient('sendToKitchen', { payload },
            () => coursingAPI.sendToKitchen(payload));
      if (r.queuedOffline) {
        toast({ title: 'Saved offline',
                description: 'The kitchen gets this order as soon as the connection is back.' });
        setSentQty(prev => {
          const next = { ...prev };
          outgoing.forEach(i => { next[i.id] = (next[i.id] || 0) + i.quantity; });
          return next;
        });
        return;
      }
      setKitchenOrder(r.data);
      setSentQty(prev => {
        const next = { ...prev };
        outgoing.forEach(i => { next[i.id] = (next[i.id] || 0) + i.quantity; });
        return next;
      });
      toast({
        title: kitchenOrder ? `Added to ticket (round ${r.data?.rounds || 2})`
             : straightFire ? 'Fired to kitchen' : 'Sent to kitchen',
        description: straightFire
          ? 'All courses fired at once.'
          : 'Later courses are held until you fire them.',
      });
    } catch (err) {
      toast({ title: 'Could not send to kitchen', description: err.response?.data?.detail || 'Try again', variant: 'destructive' });
    } finally { setCoursingBusy(false); }
  };

  const courseAction = async (courseKey, kind, fn, verb) => {
    if (!kitchenOrder) return;
    setCoursingBusy(true);
    try {
      const r = await courseActionResilient(kind, { orderId: kitchenOrder.id, course: courseKey },
        () => fn(kitchenOrder.id, courseKey));
      if (r.queuedOffline) {
        toast({ title: `${courseLabel(courseKey, coursingConfig)} queued`,
                description: 'Offline — the kitchen is told the moment the connection returns.' });
        return;
      }
      setKitchenOrder(r.data);
      toast({ title: `${courseLabel(courseKey, coursingConfig)} ${verb}` });
    } catch (err) {
      toast({
        title: `${verb} failed`,
        description: err.response?.status === 403
          ? 'Needs the Fire / Hold Courses permission.' : undefined,
        variant: 'destructive',
      });
    } finally { setCoursingBusy(false); }
  };
  const fireCourseFromCart  = (k) => courseAction(k, 'fire',  kitchenAPI.fireCourse, 'fired');
  const holdCourseFromCart  = (k) => courseAction(k, 'hold',  kitchenAPI.holdCourse, 'held');
  const serveCourseFromCart = (k) => courseAction(k, 'serve', kitchenAPI.serveCourse, 'served');

  /**
   * Take some of a line back off the kitchen ticket.
   *
   * Removing a line on the POS used to leave the kitchen cooking it. Anything
   * that already went up has to be cancelled explicitly, and the station that
   * was making it gets a void docket.
   */
  const voidFromKitchen = useCallback(async (item, qty) => {
    const already = sentQty[item.id] || 0;
    const take = Math.min(already, qty);
    if (!kitchenOrder || take <= 0) return;
    try {
      const voidPayload = {
        items: [{
          productId: item.productId || item.id, productName: item.name,
          quantity: take, course: lineCourse(item, coursingConfig),
          seat: item.seat ?? null,
        }],
      };
      const r = await courseActionResilient('void', { orderId: kitchenOrder.id, payload: voidPayload },
        () => coursingAPI.voidItems(kitchenOrder.id, voidPayload));
      if (r.queuedOffline) {
        toast({ title: 'Void queued',
                description: 'Offline — the station is told the moment the connection returns.' });
        return;
      }
      if (r.data?.order) setKitchenOrder(r.data.order);
      setSentQty(prev => {
        const next = { ...prev };
        next[item.id] = Math.max(0, (next[item.id] || 0) - take);
        if (next[item.id] === 0) delete next[item.id];
        return next;
      });
      toast({
        title: `Voided ${take} × ${item.name}`,
        description: r.data?.voidPrinted
          ? 'Void docket sent to the station that was cooking it.'
          : 'It had not been fired yet — nothing to cancel at the pass.',
      });
    } catch (err) {
      toast({
        title: 'Could not void from the kitchen',
        description: err.response?.status === 403
          ? 'Needs the Comp / Void permission.'
          : (err.response?.data?.detail || 'The kitchen may still be making it.'),
        variant: 'destructive',
      });
    }
  }, [kitchenOrder, sentQty, coursingConfig, toast]);

  // Removing or reducing a cart line has to reach the kitchen too, not just
  // the bill. Wraps the plain cart handlers rather than replacing them so
  // non-coursing venues keep the exact behaviour they had.
  const removeFromCartCoursed = useCallback((lineId) => {
    const item = cart.find(i => i.id === lineId);
    if (item && (sentQty[lineId] || 0) > 0) voidFromKitchen(item, sentQty[lineId]);
    removeFromCart(lineId);
  }, [cart, sentQty, voidFromKitchen, removeFromCart]);

  const updateQuantityCoursed = useCallback((lineId, qty) => {
    const item = cart.find(i => i.id === lineId);
    const sent = sentQty[lineId] || 0;
    if (item && sent > 0 && qty < sent) voidFromKitchen(item, sent - qty);
    updateQuantity(lineId, qty);
  }, [cart, sentQty, voidFromKitchen, updateQuantity]);

  // Wave 2 — Fetch AI upsell suggestions whenever the cart changes (debounced)
  useEffect(() => {
    if (!cart || cart.length === 0) { setUpsells([]); return; }
    const t = setTimeout(async () => {
      try {
        setUpsellLoading(true);
        const r = await aiWave2API.upsell(cart.map(i => ({ productId: i.id, name: i.name, quantity: i.quantity, price: i.price })));
        setUpsells(r.data?.suggestions || []);
      } catch { setUpsells([]); }
      finally { setUpsellLoading(false); }
    }, 1200);
    return () => clearTimeout(t);
  }, [cart]);

  // v26 — auto-apply scheduled promotions whenever the cart changes.
  // Manually selected vouchers stay sticky (keyed by voucherId).
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      // Drop stale auto-promotions before re-evaluating
      (appliedDiscounts || [])
        .filter(d => d.promotionId)
        .forEach(d => removeDiscount(d.promotionId));
      if (!cart || cart.length === 0) return;
      try {
        const items = cart.map(i => ({
          productId: i.id, id: i.id, name: i.name, price: i.price, quantity: i.quantity, category: i.category,
        }));
        const r = await v26API.applyPromos(items, orderType);
        if (cancelled) return;
        (r.data?.applied || []).forEach(p => addDiscount({
          promotionId: p.promotionId, label: p.label, discount: p.discount, auto: true,
        }));
      } catch {}
    };
    run();
    return () => { cancelled = true; };
    // Intentionally only depend on cart contents + orderType — avoids feedback loop with appliedDiscounts.
    // orderType is included so switching dine-in <-> takeaway immediately drops/re-adds
    // channel-restricted promos (e.g. a dine-in-only Happy Hour) instead of leaving a stale one applied.
  }, [cart, orderType]);  // eslint-disable-line

  // Push live cart to the customer-facing display (debounced ~400ms) — also
  // carries split-payment progress while a split is in flight, so a guest
  // watching the screen can see their own share and whether it's been paid,
  // not just the whole table's undifferentiated total.
  useEffect(() => {
    const t = setTimeout(() => {
      v26API.cfdPush({
        cart: cart.map(i => ({ id: i.id, name: i.name, price: i.price, quantity: i.quantity, image: i.image, translations: i.translations })),
        selectedCustomer: selectedCustomer ? { id: selectedCustomer.id, name: selectedCustomer.name, membershipTier: selectedCustomer.membershipTier } : null,
        tableNumber, walkInName, orderType,
        splitInProgress: paymentView === 'split',
        splitParts: paymentView === 'split'
          ? splitParts.map(s => ({ payerName: s.payerName, amount: s.amount, status: s.status }))
          : [],
      }).catch(() => {});
    }, 400);
    return () => clearTimeout(t);
  }, [cart, selectedCustomer, tableNumber, walkInName, orderType, paymentView, splitParts]);

  // Live-update products & categories every 12s + on tab focus so any edit done in
  // another window reflects without a manual refresh.
  useEffect(() => {
    const refresh = async () => {
      try {
        const [p, c] = await Promise.all([productsAPI.getAll(), v26API.activePromos?.()]);
        if (Array.isArray(p?.data)) setProducts(p.data);
        if (Array.isArray(c?.data)) setActivePromos(c.data);
      } catch {}
    };
    refresh();
    const id = setInterval(refresh, 12000);
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    return () => { clearInterval(id); window.removeEventListener('focus', onFocus); };
  }, []);

  // Load available vouchers once when discount picker opens — both the v26
  // promo-code system AND commerce_v29's universal voucher engine (campaign/
  // referral/refund/promotion-issued codes). The picker used to only ever
  // show v26's list, so a customer's own campaign voucher was invisible
  // here even after the scan/type flow was taught to accept the code.
  useEffect(() => {
    if (!showDiscountPicker) return;
    v26API.listVouchers().then(r => setAvailableVouchers((r.data || []).map(v => ({ ...v, _source: 'v26' })))).catch(() => {});
    const params = { status: 'active' };
    if (selectedCustomer?.id) params.customer_id = selectedCustomer.id;
    finalizeAPI.listVouchers(params).then(r => setUniversalVouchers(
      (r.data || [])
        .filter(v => !v.customerId || v.customerId === selectedCustomer?.id)
        .map(v => ({
          id: v.id, name: v.label, manualCode: v.code,
          discountType: v.valueType === 'percentage' ? 'percent' : 'fixed',
          value: v.value, residualValue: v.residualValue,
          active: v.status === 'active' || v.status === 'partial',
          _source: 'v29',
        }))
    )).catch(() => {});
  }, [showDiscountPicker, selectedCustomer]);

  useEffect(() => {
    if (cartTab !== 'individual') return;
    loadDrawerHistory();
    loadKitchenEta();
  }, [cartTab]);

  const applyManualCode = async (codeOverride) => {
    const code = (codeOverride ?? voucherCode ?? '').trim().toUpperCase();
    if (!code) return;
    setVoucherLoading(true);
    const items = cart.map(i => ({ productId: i.id, id: i.id, name: i.name, price: i.price, quantity: i.quantity, category: i.category }));
    try {
      const r = await v26API.applyVoucher(code, items);
      const v = r.data?.voucher || {};
      addDiscount({ voucherId: v.id, label: `${v.name} · ${r.data.message}`, discount: r.data.discount, code });
      toast({ title: 'Voucher applied', description: r.data.message });
      setVoucherCode('');
      setShowDiscountPicker(false);
      setVoucherLoading(false);
      return;
    } catch {
      // Not a v26 promo code — fall through and check the universal voucher
      // engine (commerce_v29) below. Campaign/referral/refund-issued codes
      // live in db.vouchers, a completely separate system this scan flow
      // never used to check at all, so those codes just silently "didn't
      // work" at the register no matter how valid they were.
    }
    try {
      const subtotal = items.reduce((s, i) => s + i.price * i.quantity, 0);
      const r2 = await finalizeAPI.validateVoucher({ code, cart: items, customerId: selectedCustomer?.id || undefined });
      if (!r2.data?.valid) throw new Error(r2.data?.reason || 'Invalid code');
      const v = r2.data.voucher;
      // Simplified vs. the full server-side redemption math (which also
      // scopes amount-type discounts to eligibleItems/eligibleCategories) —
      // good enough to make an otherwise-inapplicable code usable at all.
      const discount = v.valueType === 'percentage'
        ? Math.round(subtotal * (Number(v.value) / 100) * 100) / 100
        : Math.min(Number(v.value) || 0, v.partialRedeemable ? Number(v.residualValue ?? v.value) : Number(v.value));
      if (discount <= 0) throw new Error('Voucher has no remaining value');
      addDiscount({ voucherId: v.id, label: `${v.label} · -$${discount.toFixed(2)}`, discount, code });
      toast({ title: 'Voucher applied', description: `-$${discount.toFixed(2)}` });
      setVoucherCode('');
      setShowDiscountPicker(false);
    } catch (e2) {
      toast({ title: 'Could not apply', description: e2?.response?.data?.detail || e2.message || 'Invalid code', variant: 'destructive' });
    } finally { setVoucherLoading(false); }
  };

  // Scanning fills the input (so staff sees what was read) and applies it —
  // same server-side validation path as a hand-typed code.
  const handleScannedVoucher = (rawValue) => {
    const code = rawValue.trim().toUpperCase();
    setVoucherCode(code);
    applyManualCode(code);
  };

  const applyAvailableVoucher = async (v) => {
    const items = cart.map(i => ({ productId: i.id, id: i.id, name: i.name, price: i.price, quantity: i.quantity, category: i.category }));
    if (v._source === 'v29') {
      // Same simplified math as the manual-code fallback in applyManualCode
      // — good enough for a picker tap, not a byte-for-byte match with what
      // /vouchers/redeem computes server-side (eligibleItems/Categories
      // scoping isn't recomputed client-side).
      const subtotal = items.reduce((s, i) => s + i.price * i.quantity, 0);
      const discount = v.discountType === 'percent'
        ? Math.round(subtotal * (Number(v.value) / 100) * 100) / 100
        : Math.min(Number(v.value) || 0, Number(v.residualValue ?? v.value));
      if (discount <= 0) {
        toast({ title: 'Could not apply', description: 'Voucher has no remaining value', variant: 'destructive' });
        return;
      }
      addDiscount({ voucherId: v.id, label: `${v.name} · -$${discount.toFixed(2)}`, discount, code: v.manualCode });
      toast({ title: 'Applied', description: `-$${discount.toFixed(2)}` });
      setShowDiscountPicker(false);
      return;
    }
    try {
      const r = await v26API.applyVoucher(v.manualCode || v.barcode || v.id, items);
      addDiscount({ voucherId: v.id, label: `${v.name} · ${r.data.message}`, discount: r.data.discount, code: v.manualCode });
      toast({ title: 'Applied', description: r.data.message });
      setShowDiscountPicker(false);
    } catch (e) {
      toast({ title: 'Could not apply', description: e?.response?.data?.detail || 'Conditions not met', variant: 'destructive' });
    }
  };

  // Look up a gift card, then auto-apply as a tender capped at the balance due.
  const applyGiftCard = async () => {
    const code = (giftCodeInput || '').trim().toUpperCase();
    if (!code) return;
    setGiftLoading(true);
    try {
      const r = await v26API.lookupGift(code);
      const card = r.data || {};
      if (card.status !== 'active') {
        toast({ title: 'Card not active', description: `Status: ${card.status}. Use after activation.`, variant: 'destructive' });
        return;
      }
      const balance = Number(card.currentBalance ?? card.amount ?? 0);
      if (balance <= 0) {
        toast({ title: 'Empty card', description: 'Balance is $0.00', variant: 'destructive' });
        return;
      }
      // Tender = min(balance, current balance due)
      const totalsNow = calculateTotal();
      const balanceDue = Number(totalsNow.balanceDue || totalsNow.total) || 0;
      const tender = Math.min(balance, balanceDue);
      if (tender <= 0) {
        toast({ title: 'No balance due', description: 'Cart already covered by other tenders', variant: 'destructive' });
        return;
      }
      addGiftCard({ code: card.code, giftCardId: card.id, balance, amount: tender });
      toast({ title: 'Gift card applied', description: `$${tender.toFixed(2)} (balance $${balance.toFixed(2)})` });
      setGiftCodeInput('');
      setShowDiscountPicker(false);
    } catch (e) {
      toast({ title: 'Gift card error', description: e?.response?.data?.detail || 'Not found', variant: 'destructive' });
    } finally { setGiftLoading(false); }
  };

  const fetchData = async () => {
    try {
      // Run all initial fetches in parallel for max speed
      const [productsRes, promotionsRes, customersRes, catsRes, modsRes, loyaltyRes, labelsRes, trainingRes] = await Promise.allSettled([
        productsAPI.getAll(),
        promotionsAPI.getActive(),
        customersAPI.getAll(),
        itemsSystemAPI.getCategories(),
        itemsSystemAPI.getModifiers(),
        loyaltyEngineAPI.getConfig(),
        v15API.getLabels(localStorage.getItem('nua_lang') || 'en'),
        advancedAPI.getTrainingMode(),
      ]);
      const buildCategoryList = (raw) => {
        const active = (raw || [])
          .filter(c => c.active !== false)
          .sort((a, b) => (a.sortOrder ?? 99) - (b.sortOrder ?? 99))
          .map(c => ({ id: c.id, name: c.name, icon: c.icon || 'Tag', color: c.color || '#6366f1' }));
        return [{ id: 'all', name: 'All', icon: 'Sparkles', color: '#6366f1' }, ...active];
      };

      if (productsRes.status === 'fulfilled') setProducts(productsRes.value.data || []);
      if (promotionsRes.status === 'fulfilled') setPromotions(promotionsRes.value.data || []);
      if (customersRes.status === 'fulfilled') setCustomers(customersRes.value.data || []);
      if (catsRes.status === 'fulfilled' && Array.isArray(catsRes.value?.data)) {
        setCategories(buildCategoryList(catsRes.value.data));
      } else if (catsRes.status === 'rejected') {
        console.error('Failed to load categories', catsRes.reason);
        toast({ title: 'Categories failed to load', description: 'Showing "All" only — check your connection and refresh.', variant: 'destructive' });
      }

      // The menu is the one thing the floor cannot work without. A dropped
      // connection used to mean an empty product grid until it came back;
      // now the last-known menu renders instead, with a banner rather than
      // a silent substitution, and the actual re-fetch (not just the cache
      // write) resumes the moment the network genuinely returns.
      if (productsRes.status === 'fulfilled' && catsRes.status === 'fulfilled') {
        cacheCatalogue(productsRes.value.data || [], catsRes.value.data || []).catch(() => {});
        setOfflineMenu(null);
      } else if (productsRes.status === 'rejected' && isNetworkFailure(productsRes.reason)) {
        const cached = await getCachedCatalogue();
        if (cached.products.length) {
          setProducts(cached.products);
          setCategories(buildCategoryList(cached.categories));
          setOfflineMenu({ cachedAt: cached.cachedAt });
          toast({ title: "You're offline", description: `Showing the menu as of ${cached.cachedAt ? new Date(cached.cachedAt).toLocaleTimeString() : 'last sync'}.`, variant: 'destructive' });
        }
      }
      if (modsRes.status === 'fulfilled' && Array.isArray(modsRes.value?.data)) {
        setModifiers(modsRes.value.data);
      }
      if (loyaltyRes.status === 'fulfilled') setLoyaltyCfg(loyaltyRes.value.data || { minRedeem: 10, redeemRate: 0.01 });
      if (labelsRes.status === 'fulfilled') setLabels(labelsRes.value.data || {});
      if (trainingRes.status === 'fulfilled') setTrainingMode(trainingRes.value.data?.enabled || false);
    } catch (error) {
      console.error('Error fetching data:', error);
      toast({ title: "Error", description: "Failed to load data.", variant: "destructive" });
    }
  };

  const filteredProducts = products.filter(p => {
    // A variant-grouping row (e.g. "T-Shirt") isn't sold directly once it
    // has real variants under it — only the variants themselves (their own
    // Product rows, each with parentId set to this one) are sellable.
    if (p.hasVariants) return false;
    const term = searchTerm.toLowerCase();
    return (selectedCategory === 'All' || p.category === selectedCategory) &&
      (p.name.toLowerCase().includes(term) || (p.category || '').toLowerCase().includes(term) ||
       (p.sku || '').toLowerCase().includes(term) || (p.barcode || '') === searchTerm);
  });

  // A barcode scanner types the code then fires Enter — if what's in the
  // search box exactly matches one product's barcode (or SKU), add it
  // straight to cart instead of making staff hunt for it in the grid.
  const handleSearchKeyDown = (e) => {
    if (e.key !== 'Enter' || !searchTerm.trim()) return;
    const code = searchTerm.trim();
    const hit = products.find(p => !p.hasVariants && (p.barcode === code || p.sku === code));
    if (hit) {
      addToCart(hit);
      setSearchTerm('');
      toast({ title: 'Added', description: hit.name });
    }
  };

  // Group products by category for "All" view (category-wise display)
  const groupedByCategory = React.useMemo(() => {
    const groups = {};
    filteredProducts.forEach(p => {
      const cat = p.category || 'Uncategorized';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(p);
    });
    return groups;
  }, [filteredProducts]);

  const totalsRaw = calculateTotal();
  const redeemDiscount = pointsToRedeem >= (loyaltyCfg.minRedeem || 10) ? pointsToRedeem * (loyaltyCfg.redeemRate || 0.01) : 0;
  const totals = redeemDiscount > 0
    ? { ...totalsRaw, total: Math.max(0, parseFloat(totalsRaw.total) - redeemDiscount).toFixed(2),
        balanceDue: Math.max(0, parseFloat(totalsRaw.balanceDue || totalsRaw.total) - redeemDiscount).toFixed(2),
        pointsDiscount: redeemDiscount.toFixed(2) }
    : totalsRaw;
  // The amount we charge through the chosen payment method = balance due (after gift cards).
  const totalNum = parseFloat(totals.balanceDue || totals.total) || 0;
  const grossTotal = parseFloat(totals.total) || 0;

  // Settle gift cards after a successful payment: activate sold-cards, redeem tenders.
  const settleGiftCards = async (txId) => {
    // The sale is already recorded complete by the time this runs — a failure
    // here can no longer be rolled back automatically, so every failure is
    // surfaced loudly (not console.warn'd away) for manual reconciliation.
    const failures = [];
    for (const card of (pendingGiftActivations || [])) {
      try { await v26API.activateGift(card.code, { transactionId: txId }); }
      catch (e) { failures.push(`Card ${card.code} did not activate (${e?.response?.data?.detail || 'network error'})`); }
    }
    for (const gc of (appliedGiftCards || [])) {
      try {
        if (gc.amount > 0) await v26API.redeemGiftPartial(gc.code, gc.amount, txId);
      } catch (e) { failures.push(`Card ${gc.code} was not debited $${gc.amount.toFixed(2)} (${e?.response?.data?.detail || 'network error'})`); }
    }
    // Store credit tender — settle after the sale has actually gone through,
    // same as gift cards, so a failed payment never touches the balance.
    if (storeCreditApplied > 0 && selectedCustomer?.id) {
      try { await customersAPI.redeemStoreCredit(selectedCustomer.id, storeCreditApplied); }
      catch (e) { failures.push(`Store credit of $${storeCreditApplied.toFixed(2)} was not deducted (${e?.response?.data?.detail || 'network error'})`); }
    }
    if (failures.length > 0) {
      toast({
        title: `Sale completed, but ${failures.length} tender${failures.length === 1 ? '' : 's'} need manual reconciliation`,
        description: failures.join(' · '),
        variant: 'destructive',
      });
    }
  };

  const canOpenDrawer = user?.role === 'owner' || hasPermission?.('cash-drawer');

  const loadDrawerHistory = async () => {
    if (!canOpenDrawer) return;
    try { const r = await v15API.getDrawerEvents(); setDrawerHistory(r.data || []); }
    catch { /* history is a nice-to-have, not critical */ }
  };

  const handleOpenDrawer = async () => {
    setDrawerBusy(true);
    try {
      await v15API.openDrawer({ reason: drawerReason, note: drawerNote, location: currentLocation });
      toast({ title: 'Drawer opened', description: 'Logged for the owner — reason: ' + drawerReason.replace('_', ' ') });
      setDrawerNote('');
      loadDrawerHistory();
    } catch (e) {
      toast({ title: 'Could not open drawer', description: e?.response?.data?.detail || 'Failed', variant: 'destructive' });
    } finally { setDrawerBusy(false); }
  };

  const loadKitchenEta = async () => {
    try { const r = await kitchenAPI.getNextOrderETA(); setKitchenEta(r.data); }
    catch { /* rough gauge only, not critical */ }
  };

  const jumpToDiscounts = () => { setCartTab('cart'); setShowDiscountPicker(true); };

  const handleQuickCompVoid = async () => {
    if (!compVoidForm.reason.trim()) { toast({ title: 'Reason required', variant: 'destructive' }); return; }
    if (!compVoidForm.amount || parseFloat(compVoidForm.amount) <= 0) { toast({ title: 'Amount must be greater than 0', variant: 'destructive' }); return; }
    setCompVoidBusy(true);
    try {
      await itemsSystemAPI.createCompVoid({
        ...compVoidForm, amount: parseFloat(compVoidForm.amount), transactionId: lastTxnId || undefined,
      });
      toast({ title: `${compVoidForm.type === 'comp' ? 'Comp' : 'Void'} recorded` });
      setShowCompVoidQuick(false);
      setCompVoidForm({ type: 'comp', reason: '', amount: '', printVoid: false });
    } catch (e) {
      toast({ title: 'Failed to record', description: e?.response?.data?.detail || 'Failed', variant: 'destructive' });
    } finally { setCompVoidBusy(false); }
  };

  const openTablesDialog = async (mode) => {
    setTablesDialogMode(mode);
    setMovingTab(null); setMergeSelection([]); setSplittingTab(null); setSplitWays(2);
    try { const r = await v15API.getTabs(); setOpenTabs(r.data || []); setShowTabsDialog(true); }
    catch { toast({ title: 'Failed to load open tabs', variant: 'destructive' }); }
  };

  const handleMoveTable = async (tabId) => {
    if (!moveTargetTable.trim()) { toast({ title: 'Enter a table number', variant: 'destructive' }); return; }
    try {
      await v15API.updateTab(tabId, { tableNumber: moveTargetTable.trim() });
      toast({ title: `Moved to table ${moveTargetTable.trim()}` });
      setMovingTab(null); setMoveTargetTable('');
      const r = await v15API.getTabs(); setOpenTabs(r.data || []);
    } catch (e) { toast({ title: 'Failed to move table', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };

  const handleMergeTables = async () => {
    if (mergeSelection.length < 2) { toast({ title: 'Select at least 2 tabs to merge', variant: 'destructive' }); return; }
    const [primary, ...rest] = mergeSelection;
    try {
      for (const otherId of rest) { await v15API.mergeTabs(primary, otherId); }
      toast({ title: `Merged ${mergeSelection.length} tables into one check` });
      setMergeSelection([]);
      const r = await v15API.getTabs(); setOpenTabs(r.data || []);
    } catch (e) { toast({ title: 'Failed to merge tables', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };

  const handleSplitTable = async (tabId) => {
    try {
      const r = await v15API.splitTab(tabId, splitWays);
      toast({ title: `Split into ${r.data?.tabs?.length || splitWays} checks` });
      setSplittingTab(null);
      const r2 = await v15API.getTabs(); setOpenTabs(r2.data || []);
    } catch (e) { toast({ title: 'Failed to split', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };

  // Discounts applied on screen, in the shape POST /transactions records
  // (backend recomputes totals from these — keep in sync with calculateTotal).
  const buildDiscountPayload = () => ({
    appliedDiscounts: (appliedDiscounts || []).map(d => ({
      label: d.label || '', amount: Number(d.discount) || 0,
      promotionId: d.promotionId || null, voucherId: d.voucherId || null, code: d.code || null,
    })),
    pointsRedeemed: pointsToRedeem || 0,
    pointsDiscount: redeemDiscount || 0,
  });

  // ---- Standard checkout ----
  const handleCheckout = async (paymentMethod) => {
    if (loading) return;
    // A dine-in sale must land on a table that exists — otherwise the docket
    // sends food to a table nobody is sitting at.
    if (tableBlocked) {
      toast({ title: 'Unknown table', description: tableCheck.message, variant: 'destructive' });
      return;
    }
    if (trainingMode) {
      toast({ title: "Training Mode", description: "Transaction simulated — no real charge was made.", variant: "default" });
      resetPayment();
      clearCart();
      return;
    }
    setLoading(true);
    try {
      const res = await createTransactionResilient({
        items: cart.map(item => toTxItem(item, true)),
        paymentMethod, customerId: selectedCustomer?.id || null, location: currentLocation, cashier: currentUser.name,
        orderType, tableNumber: orderType === 'dine-in' ? tableNumber : null, walkInName: orderType === 'takeaway' ? walkInName : null,
        ...buildDiscountPayload(),
      });
      const queuedOffline = !!res.data?.queuedOffline;
      setLastTxnId(res.data?.id || null);
      if (queuedOffline) {
        // No connectivity right now — the sale is saved locally and will
        // sync automatically. Skip loyalty/printer/gift-card side-effects
        // (they need the server) and let the background flush handle them
        // once this transaction actually lands.
        toast({ title: "Saved offline", description: `$${totals.total} sale queued — will sync when back online.` });
        refreshOfflineQueue();
      } else {
        // Loyalty redeem + earn both happen atomically inside the
        // /transactions POST itself now (pointsRedeemed/pointsDiscount are
        // already in buildDiscountPayload() above) — no follow-up call here.
        // The old separate calls raced this response and wrote to a
        // different balance field than the one redemption/receipts read
        // from, so a failed follow-up could silently keep a customer's
        // points after they'd already gotten the discount.
        toast({ title: "Transaction Complete!", description: `Payment of $${totals.total} via ${paymentMethod}` });
        // Auto-route items to category printers
        try { await gamificationAPI.sendToPrinters({ items: cart.map(i => ({ productName: i.name, category: i.category, quantity: i.quantity })), orderId: res.data?.id, tableNumber: orderType === 'dine-in' ? tableNumber : null }); } catch {}
        if (orderType === 'dine-in' && tableCheck.status === 'ok') {
          try {
            if (kitchenOrder) {
              // A coursed table has been sitting there all meal. Paying closes
              // the kitchen ticket and hands the table back — without this the
              // floor plan filled up over a service and never drained, and the
              // next party's first order joined the previous party's ticket.
              await coursingAPI.settle({ tableNumber, transactionId: res.data?.id });
              setKitchenOrder(null);
              setSentQty({});
            } else {
              // Pay-at-counter dine-in: they're sitting down now, so the table
              // becomes occupied rather than free.
              await floorPlansAPI.occupyByNumber(tableNumber, res.data?.id);
            }
            loadFloorTables();
          } catch { /* the sale is already recorded — don't fail it on this */ }
        }
        // Settle gift cards: activate any pending-sold cards + redeem applied tenders.
        await settleGiftCards(res.data?.id);
      }
      resetPayment();
      clearCart();
      setPointsToRedeem(0);
      try { const r = await productsAPI.getAll(); setProducts(r.data); } catch {}
    } catch (error) {
      toast({ title: "Error", description: "Transaction failed.", variant: "destructive" });
    } finally { setLoading(false); }
  };

  // ---- QR / UPI flow ----
  const handleGenerateQR = async (method) => {
    setLoading(true);
    try {
      const res = await paymentAPI.generateQR({ amount: totalNum, method });
      setQrData(res.data);
      setPaymentView(method === 'upi' ? 'upi' : 'qr');
    } catch {
      toast({ title: "Error", description: "Failed to generate QR code.", variant: "destructive" });
    } finally { setLoading(false); }
  };

  // ---- Stripe Checkout ----
  // Stripe redirects the whole browser away and back — nothing in this
  // component's React state (cart, discounts, table…) survives that round
  // trip. So the full sale payload (same shape POST /transactions takes)
  // travels WITH the checkout session and gets rung up server-side once
  // Stripe confirms payment, instead of relying on this tab still being
  // open and in the right state when the guest returns.
  //
  // But if the guest backs out WITHOUT paying (browser back, closing the
  // Stripe tab, etc.), there was previously nothing to come back to — the
  // cart was just gone, indistinguishable from never having rung anything
  // up, and the cashier had to rebuild it from scratch to charge a
  // different way. An auto-hold tab (the same pos_tabs mechanism the
  // manual "Hold" button uses) is created right before the redirect so the
  // sale can be resumed or explicitly cancelled instead — see the
  // heldCheckoutTabs banner below. If payment does succeed, the finalize
  // path (_finalize_pos_sale_if_applicable, integrations.py) deletes this
  // hold once the real transaction lands, so it never lingers after a
  // completed sale.
  const handleStripeCheckout = async () => {
    if (tableBlocked) {
      toast({ title: 'Unknown table', description: tableCheck.message, variant: 'destructive' });
      return;
    }
    if (cart.length === 0) { toast({ title: 'Cart empty', variant: 'destructive' }); return; }
    setLoading(true);
    let holdTabId = null;
    try {
      // Reused across a manual retry of the exact same cart (a double-click,
      // or clicking Pay again after a dropped response) so the backend can
      // dedup and return the original checkout session instead of creating
      // a second live one — see services/payment_idempotency.py. Keyed off
      // the total, not just generated once per mount, so a genuinely
      // different cart after a failed attempt gets its own fresh key.
      if (stripeIdemRef.current.total !== totalNum) {
        stripeIdemRef.current = {
          total: totalNum,
          key: (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID() : `sc-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        };
      }

      const holdRes = await v15API.createTab({
        name: `Card (Stripe) — ${new Date().toLocaleTimeString()}`,
        cart, selectedCustomer, tableNumber: orderType === 'dine-in' ? tableNumber : null,
        autoHold: true, checkoutProvider: 'stripe',
      });
      holdTabId = holdRes.data?.id;

      const res = await stripeAPI.createCheckout({
        originUrl: window.location.origin,
        amount: totalNum,
        idempotencyKey: stripeIdemRef.current.key,
        heldTabId: holdTabId,
        sale: {
          items: cart.map(item => toTxItem(item, true)),
          paymentMethod: 'Stripe',
          customerId: selectedCustomer?.id || null, location: currentLocation, cashier: currentUser.name,
          orderType, tableNumber: orderType === 'dine-in' ? tableNumber : null,
          ...buildDiscountPayload(),
        },
      });
      if (res.data.url) {
        window.location.href = res.data.url;
        return; // page is unloading — don't fall through to setLoading(false)
      }
      throw new Error('No checkout URL returned');
    } catch {
      // Checkout session never actually started — don't leave an orphaned
      // hold with nothing to resume it into.
      if (holdTabId) { try { await v15API.deleteTab(holdTabId); } catch {} }
      toast({ title: "Error", description: "Failed to initiate Stripe checkout.", variant: "destructive" });
      setLoading(false);
    }
  };

  // ---- Crypto Checkout (Bitcoin + USDC via Coinbase Commerce) ----
  // Same "redirect away, redirect back" shape as Stripe above — the sale
  // payload travels with the checkout charge and gets rung up server-side
  // once Coinbase confirms payment, not by this tab still being open. Same
  // auto-hold-before-redirect as handleStripeCheckout, for the same reason.
  const handleCryptoCheckout = async () => {
    if (tableBlocked) {
      toast({ title: 'Unknown table', description: tableCheck.message, variant: 'destructive' });
      return;
    }
    if (cart.length === 0) { toast({ title: 'Cart empty', variant: 'destructive' }); return; }
    setLoading(true);
    let holdTabId = null;
    try {
      // Same double-click/retry dedup as handleStripeCheckout above.
      if (cryptoIdemRef.current.total !== totalNum) {
        cryptoIdemRef.current = {
          total: totalNum,
          key: (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID() : `cc-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        };
      }

      const holdRes = await v15API.createTab({
        name: `Crypto — ${new Date().toLocaleTimeString()}`,
        cart, selectedCustomer, tableNumber: orderType === 'dine-in' ? tableNumber : null,
        autoHold: true, checkoutProvider: 'crypto',
      });
      holdTabId = holdRes.data?.id;

      const res = await cryptoAPI.createCheckout({
        originUrl: window.location.origin,
        amount: totalNum,
        idempotencyKey: cryptoIdemRef.current.key,
        heldTabId: holdTabId,
        sale: {
          items: cart.map(item => toTxItem(item, true)),
          paymentMethod: 'Crypto',
          customerId: selectedCustomer?.id || null, location: currentLocation, cashier: currentUser.name,
          orderType, tableNumber: orderType === 'dine-in' ? tableNumber : null,
          ...buildDiscountPayload(),
        },
      });
      if (res.data.url) {
        window.location.href = res.data.url;
        return;
      }
      throw new Error('No checkout URL returned');
    } catch (err) {
      if (holdTabId) { try { await v15API.deleteTab(holdTabId); } catch {} }
      toast({ title: "Error", description: err.response?.data?.detail || "Failed to initiate crypto checkout.", variant: "destructive" });
      setLoading(false);
    }
  };

  const handleConfirmQRPayment = async () => {
    if (!qrData?.paymentId) return;
    setLoading(true);
    try {
      await paymentAPI.confirm(qrData.paymentId);
      const res = await transactionsAPI.create({
        items: cart.map(item => toTxItem(item)),
        paymentMethod: paymentView === 'upi' ? 'UPI' : 'QR Code',
        customerId: selectedCustomer?.id || null, location: currentLocation, cashier: currentUser.name,
        ...buildDiscountPayload(),
      });
      toast({ title: "Payment Confirmed!", description: `$${totalNum.toFixed(2)} received via ${paymentView === 'upi' ? 'UPI' : 'QR Code'}` });
      await settleGiftCards(res.data?.id);
      resetPayment(); clearCart();
      const r = await productsAPI.getAll(); setProducts(r.data);
    } catch {
      toast({ title: "Error", description: "Confirmation failed.", variant: "destructive" });
    } finally { setLoading(false); }
  };

  // ---- Split payment flow ----
  /**
   * Split the bill the way the table actually ate it: one part per seat that
   * ordered something, each owing what that seat had.
   *
   * This is the reason venues turn seat ordering on — capturing the seat and
   * then splitting evenly anyway defeats the point. Anything with no seat
   * (shared plates, a bottle for the table) is spread across the seats, since
   * dropping it would leave the parts short of the bill.
   */
  const initSeatSplitParts = useCallback(() => {
    const bySeat = new Map();
    let unseated = 0;
    cartWithCourses.forEach(i => {
      const line = (i.price || 0) * (i.quantity || 0);
      if (i.seat == null) { unseated += line; return; }
      if (!bySeat.has(i.seat)) bySeat.set(i.seat, { amount: 0, items: [] });
      const b = bySeat.get(i.seat);
      b.amount += line;
      b.items.push({ name: i.name, quantity: i.quantity });
    });
    if (bySeat.size === 0) return false;

    const seatsList = [...bySeat.keys()].sort((a, b) => a - b);
    const share = unseated / seatsList.length;
    // Scale to the payable total so discounts, surcharge and GST-inclusive
    // rounding all land on the parts rather than leaving a stray few cents.
    const gross = seatsList.reduce((s, k) => s + bySeat.get(k).amount, 0) + unseated;
    const scale = gross > 0 ? totalNum / gross : 1;

    const parts = seatsList.map(seat => {
      const b = bySeat.get(seat);
      return {
        payerName: `Seat ${seat}`,
        seat,
        seatItems: b.items,
        amount: Math.round((b.amount + share) * scale * 100) / 100,
        method: 'Card',
        status: 'pending',
      };
    });
    // Put any rounding difference on the first part so the parts sum exactly.
    const sum = parts.reduce((s, p) => s + p.amount, 0);
    const drift = Math.round((totalNum - sum) * 100) / 100;
    if (drift !== 0 && parts.length) {
      parts[0].amount = Math.round((parts[0].amount + drift) * 100) / 100;
    }
    setSplitParts(parts);
    setSplitCount(parts.length);
    return true;
  }, [cartWithCourses, totalNum]);

  const initSplitParts = useCallback((count, mode) => {
    const perPerson = Math.floor((totalNum / count) * 100) / 100;
    const remainder = Math.round((totalNum - perPerson * count) * 100) / 100;
    const parts = Array.from({ length: count }, (_, i) => ({
      payerName: `Guest ${i + 1}`,
      amount: i === 0 ? perPerson + remainder : perPerson,
      method: 'Card',
      status: 'pending',
    }));
    setSplitParts(parts);
  }, [totalNum]);

  const handleStartSplit = () => {
    setPaymentView('split');
    initSplitParts(splitCount, splitMode);
  };

  const updateSplitPart = (idx, field, value) => {
    setSplitParts(prev => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
  };

  /** "By item" split — rebuild each guest's amount from itemAssignments.
   *  Preserves payerName/method/status already on splitParts (keyed by
   *  index) so re-assigning one item doesn't blank out names already typed
   *  or drop a guest who's already paid. Unassigned quantity is spread
   *  evenly across guests, same as the seat-based split, so the parts
   *  always sum to the bill even mid-assignment. */
  const recalcItemSplitParts = useCallback((assignments, count) => {
    setSplitParts(prev => {
      const guestAmounts = Array.from({ length: count }, () => 0);
      const guestItems = Array.from({ length: count }, () => []);
      let unassignedValue = 0;
      let grossValue = 0;
      cartWithCourses.forEach(item => {
        const unitPrice = item.price || 0;
        const qty = item.quantity || 0;
        grossValue += unitPrice * qty;
        const perGuest = assignments[item.id] || {};
        let assignedQty = 0;
        for (let g = 0; g < count; g++) {
          const q = perGuest[g] || 0;
          if (q > 0) {
            guestAmounts[g] += unitPrice * q;
            guestItems[g].push({ name: item.name, quantity: q });
            assignedQty += q;
          }
        }
        unassignedValue += unitPrice * Math.max(0, qty - assignedQty);
      });
      const share = count > 0 ? unassignedValue / count : 0;
      const scale = grossValue > 0 ? totalNum / grossValue : 1;
      const parts = Array.from({ length: count }, (_, i) => {
        const existing = prev[i];
        return {
          payerName: existing?.payerName || `Guest ${i + 1}`,
          method: existing?.method || 'Card',
          status: existing?.status === 'confirmed' ? 'confirmed' : 'pending',
          assignedItems: guestItems[i],
          amount: Math.round((guestAmounts[i] + share) * scale * 100) / 100,
        };
      });
      const sum = parts.reduce((s, p) => s + p.amount, 0);
      const drift = Math.round((totalNum - sum) * 100) / 100;
      if (drift !== 0 && parts.length) parts[0].amount = Math.round((parts[0].amount + drift) * 100) / 100;
      return parts;
    });
  }, [cartWithCourses, totalNum]);

  /** Move one unit of a cart line's quantity onto/off a guest. Clamped so the
   *  total assigned for that line can never exceed its cart quantity. */
  const adjustItemAssignment = (lineId, guestIdx, delta) => {
    setItemAssignments(prev => {
      const item = cartWithCourses.find(i => i.id === lineId);
      if (!item) return prev;
      const perGuest = { ...(prev[lineId] || {}) };
      const assignedToOthers = Object.entries(perGuest)
        .reduce((s, [g, q]) => s + (Number(g) === guestIdx ? 0 : (q || 0)), 0);
      const current = perGuest[guestIdx] || 0;
      const next = Math.max(0, Math.min((item.quantity || 0) - assignedToOthers, current + delta));
      perGuest[guestIdx] = next;
      const updated = { ...prev, [lineId]: perGuest };
      recalcItemSplitParts(updated, splitCount);
      return updated;
    });
  };

  const recalcEqualSplit = (count) => {
    setSplitCount(count);
    if (splitMode === 'equal') initSplitParts(count, 'equal');
    else if (splitMode === 'items') recalcItemSplitParts(itemAssignments, count);
  };

  const splitPaid = splitParts.filter(s => s.status === 'confirmed').reduce((sum, s) => sum + s.amount, 0);
  const splitRemaining = Math.max(0, Math.round((totalNum - splitPaid) * 100) / 100);

  const handlePaySplit = async (idx) => {
    const part = splitParts[idx];
    // ---- Validation: catch wrong / missing / overshoot amounts BEFORE we charge.
    const amt = Number(part.amount) || 0;
    if (amt <= 0) {
      toast({ title: "Invalid amount", description: `Split #${idx + 1} must be greater than $0.`, variant: "destructive" });
      return;
    }
    // Tolerate 1¢ rounding noise, but reject anything that overshoots the bill.
    if (amt > splitRemaining + 0.005) {
      toast({
        title: "Amount exceeds remaining",
        description: `Only $${splitRemaining.toFixed(2)} remaining — Split #${idx + 1} is $${amt.toFixed(2)}.`,
        variant: "destructive",
      });
      return;
    }
    setActiveSplitIndex(idx);
    setLoading(true);
    try {
      if (part.method === 'UPI' || part.method === 'QR Code') {
        // NEW: generate the QR, then SHOW it to the guest. Nothing is marked
        // paid until the cashier taps "Confirm Payment Received" in the dialog.
        const res = await paymentAPI.generateQR({
          amount: part.amount,
          method: part.method === 'UPI' ? 'upi' : 'qr_code',
        });
        setSplitQrData({ ...res.data, method: part.method, splitIndex: idx });
        setSplitQrView(part.method === 'UPI' ? 'upi' : 'qr');
        setLoading(false);
        return; // wait for cashier to confirm in the dialog
      }
      // Card / Cash — no external QR needed, mark straight away.
      await finaliseSplitPart(idx);
    } catch {
      toast({ title: "Error", description: "Split payment failed.", variant: "destructive" });
      setLoading(false);
      setActiveSplitIndex(null);
    }
  };

  /** Second half of the split-QR / split-UPI flow: called once the cashier
   *  taps "Confirm Payment Received" inside the QR/UPI dialog. */
  const confirmSplitQr = async () => {
    if (splitQrData == null) return;
    const idx = splitQrData.splitIndex;
    setLoading(true);
    try {
      if (splitQrData.paymentId) {
        try { await paymentAPI.confirm(splitQrData.paymentId); } catch { /* backend may already be confirmed; not fatal */ }
      }
      setSplitQrView(null);
      setSplitQrData(null);
      await finaliseSplitPart(idx);
    } catch {
      toast({ title: "Error", description: "Could not confirm QR payment.", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const cancelSplitQr = () => {
    // Guest didn't scan / cashier bailed out — leave the split part pending.
    setSplitQrView(null);
    setSplitQrData(null);
    setActiveSplitIndex(null);
    setLoading(false);
  };

  /** Common tail — mark the split part paid, check overall balance, and if
   *  every part is confirmed, create the transaction and reset. */
  const finaliseSplitPart = async (idx) => {
    setSplitParts(prev => {
      const next = [...prev];
      next[idx] = { ...next[idx], status: 'confirmed' };
      return next;
    });
    const paidPart = splitParts[idx];
    toast({ title: `Split #${idx + 1} Paid`, description: `$${Number(paidPart.amount).toFixed(2)} from ${paidPart.payerName}` });

    // A seat that pays and leaves at eight shouldn't still read as owing at
    // ten. Settle just their items now; the ticket itself stays open for the
    // rest of the table and only closes once every seat has paid.
    if (paidPart.seat != null && kitchenOrder) {
      try {
        await coursingAPI.settle({
          tableNumber, orderId: kitchenOrder.id, seats: [paidPart.seat], releaseTable: false,
        });
      } catch { /* the guest has paid — never block on the tidy-up */ }
    }

    const updatedParts = splitParts.map((s, i) => i === idx ? { ...s, status: 'confirmed' } : s);
    const allPaid = updatedParts.every(s => s.status === 'confirmed');
    if (allPaid) {
      const totalPaid = updatedParts.reduce((sum, s) => sum + Number(s.amount || 0), 0);
      if (Math.abs(totalPaid - totalNum) > 0.01) {
        toast({
          title: "Split doesn't balance",
          description: `Collected $${totalPaid.toFixed(2)} vs bill $${totalNum.toFixed(2)}. Adjust amounts before closing.`,
          variant: "destructive",
        });
        setSplitParts(prev => {
          const next = [...prev];
          next[idx] = { ...next[idx], status: 'pending' };
          return next;
        });
        setActiveSplitIndex(null);
        return;
      }
      try {
        const res = await transactionsAPI.create({
          items: cart.map(item => toTxItem(item)),
          paymentMethod: 'Split Payment',
          customerId: selectedCustomer?.id || null, location: currentLocation, cashier: currentUser.name,
          splitDetails: updatedParts.map(s => ({
            payerName: s.payerName, amount: s.amount, method: s.method,
            items: (s.assignedItems || s.seatItems || []).map(i => ({ name: i.name, quantity: i.quantity })),
            customerId: s.customerId || null,
            pointsRedeemed: s.customerId ? (Number(s.pointsRedeemed) || 0) : 0,
          })),
          ...buildDiscountPayload(),
        });
        toast({ title: "All Splits Paid!", description: `Total $${totalNum.toFixed(2)} collected` });
        await settleGiftCards(res.data?.id);
        setTimeout(() => { resetPayment(); clearCart(); }, 1200);
        productsAPI.getAll().then(r => setProducts(r.data));
      } catch {
        toast({ title: "Error", description: "Could not finalise transaction.", variant: "destructive" });
      }
    }
    setActiveSplitIndex(null);
  };

  const resetPayment = () => {
    setShowPayment(false); setPaymentView('methods'); setQrData(null);
    setSplitParts([]); setSplitCount(2); setSplitMode('equal');
    setSplitQrData(null); setSplitQrView(null);
    setCashTendered(0); setShowCashChange(false);
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    toast({ title: "Copied!", description: "UPI ID copied to clipboard" });
  };

  return (
    <div
      className={`flex flex-col ${posLayout.cartPosition === 'left' ? 'lg:flex-row-reverse' : 'lg:flex-row'} gap-4 h-[calc(100vh-7rem)] -m-6 p-4 transition-colors`}
      style={{ backgroundColor: theme.background, '--pos-tile-min': posLayout.tileSize === 'compact' ? '96px' : posLayout.tileSize === 'large' ? '168px' : '130px' }}
      data-testid="pos-terminal"
    >
      {/* Training Mode Banner */}
      {trainingMode && (
        <div className="fixed top-0 left-0 right-0 z-40 bg-amber-500 text-white text-center py-2 text-sm font-semibold"
          data-testid="training-mode-banner">
          TRAINING MODE — Transactions are simulated, no real charges
        </div>
      )}
      {/* Offline menu banner — light-on-dark-amber text, not white-on-amber,
          for the same reason dark mode's --primary-foreground was fixed:
          this is exactly the message someone needs to actually read. */}
      {offlineMenu && (
        <div className={`${trainingMode ? 'fixed top-9' : 'fixed top-0'} left-0 right-0 z-40 bg-amber-100 text-amber-900 text-center py-2 text-sm font-semibold`}
          data-testid="offline-menu-banner">
          You're offline — showing the menu as of{' '}
          {offlineMenu.cachedAt ? new Date(offlineMenu.cachedAt).toLocaleTimeString() : 'last sync'}
        </div>
      )}
      {/* Products Grid — smaller cards, category-wise */}
      {/* min-h-0 is required here: a flex-col child won't shrink below its
          content's natural height otherwise, so the overflow-y-auto grid
          below never actually constrains — the category bar gets pushed
          around and the whole page scrolls instead of just the grid. */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <div className="mb-3">
          {/* Compact status bar replaces the bulky "POS Terminal" title */}
          <div data-testid="pos-title">
            <POSHeaderBar themeColor={theme.primary} />
          </div>
          {queuedCount > 0 && (
            <div className="mb-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-700 text-xs font-medium" data-testid="offline-queue-banner">
              <WifiOff size={14} />
              {queuedCount} sale{queuedCount === 1 ? '' : 's'} saved offline — syncing when back online…
            </div>
          )}
          {/* A sale sent to Stripe/Crypto checkout that came back without
              paying — held, not lost. See handleStripeCheckout /
              handleCryptoCheckout and loadHeldCheckouts. */}
          {heldCheckoutTabs.length > 0 && (
            <div className="mb-3 space-y-1.5" data-testid="held-checkout-banner">
              {heldCheckoutTabs.map(tab => (
                <div key={tab.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-orange-50 border border-orange-300 text-orange-800 text-xs font-medium">
                  <Clock size={14} className="flex-shrink-0" />
                  <span className="flex-1">
                    Held sale pending {tab.checkoutProvider === 'crypto' ? 'crypto' : 'Stripe'} payment —{' '}
                    {(tab.cart || []).reduce((n, i) => n + (i.quantity || 0), 0)} item(s)
                    {tab.tableNumber ? ` · table ${tab.tableNumber}` : ''}
                  </span>
                  <Button size="sm" className="h-7 px-2.5 text-xs" style={{ backgroundColor: theme.primary }}
                    onClick={() => resumeHeldCheckout(tab)} data-testid={`resume-held-${tab.id}`}>
                    Resume
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 px-2.5 text-xs text-orange-700 border-orange-300"
                    onClick={() => cancelHeldCheckout(tab)} data-testid={`cancel-held-${tab.id}`}>
                    Cancel
                  </Button>
                </div>
              ))}
            </div>
          )}
          <div className="relative mb-3 flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={16} />
              <Input placeholder="Search products or scan a barcode..." className="pl-9 h-9" value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)} onKeyDown={handleSearchKeyDown} data-testid="pos-search" />
            </div>
            <VoiceOrderButton
              onAddSuggestions={(suggestions) => {
                suggestions.forEach(s => {
                  const p = products.find(pp => pp.id === s.productId);
                  if (p) { for (let i = 0; i < s.quantity; i++) addToCart(p); }
                });
              }}
              onExtendedAction={(act) => {
                if (act.action === 'void_last_item' && cart.length > 0) {
                  removeFromCart(cart[cart.length - 1].id);
                }
              }}
            />
            {posLayout.quickActions.hold && (
              <Button variant="outline" className="h-9 px-3" onClick={async () => {
                if (cart.length === 0) { toast({ title: 'Cart empty', variant: 'destructive' }); return; }
                try {
                  await v15API.createTab({ name: `Tab ${new Date().toLocaleTimeString()}`, cart, selectedCustomer });
                  toast({ title: 'Order held', description: 'Recall from "Tabs" button' });
                  clearCart();
                } catch { toast({ title: 'Hold failed', variant: 'destructive' }); }
              }} data-testid="hold-order-btn">Hold</Button>
            )}
            {posLayout.quickActions.tabs && (
              <Button variant="outline" className="h-9 px-3" onClick={async () => {
                try { setTablesDialogMode('view'); const r = await v15API.getTabs(); setOpenTabs(r.data || []); setShowTabsDialog(true); } catch {}
              }} data-testid="recall-tab-btn">Tabs</Button>
            )}
          </div>
          {activePromos.length > 0 && (
            <div className="flex gap-1.5 overflow-x-auto pb-1.5" data-testid="active-promos-strip">
              <span className="text-[10px] font-bold uppercase tracking-wider text-amber-700 flex items-center bg-amber-100 px-2 rounded-full shrink-0">
                🔥 Live now
              </span>
              {activePromos.map(p => (
                <span key={p.id}
                  className="text-[11px] font-semibold whitespace-nowrap px-2.5 py-1 rounded-full border shrink-0"
                  style={{ background: `${theme.primary}10`, borderColor: `${theme.primary}40`, color: theme.primary }}
                  title={`${p.discount}% off · ${(p.activeDays || []).join(',') || 'all days'} ${p.startTime || ''}–${p.endTime || ''}`}
                  data-testid={`active-promo-${p.id}`}>
                  {p.name} · {p.discount}% off
                </span>
              ))}
            </div>
          )}
          {/* Category bar — compact pills, max 6 visible + "More" overflow panel.
              A category picked from the overflow is promoted into the visible
              row, so frequent switches stay one tap away. */}
          {(() => {
            const MAX_VISIBLE = 6;
            const all = categories[0];                    // 'All' is always first
            const rest = categories.slice(1);
            let visible = rest.slice(0, MAX_VISIBLE);
            let overflow = rest.slice(MAX_VISIBLE);
            if (overflow.length === 1) { visible = rest; overflow = []; }
            const selInOverflow = overflow.find(c => c.name === selectedCategory);
            if (selInOverflow) {
              overflow = [visible[visible.length - 1], ...overflow.filter(c => c.name !== selectedCategory)];
              visible = [...visible.slice(0, -1), selInOverflow];
            }
            const pill = (cat) => {
              const active = selectedCategory === cat.name;
              const bg = cat.color || theme.primary;
              return (
                <button key={cat.id || cat.name}
                  onClick={() => { setSelectedCategory(cat.name); setShowMoreCats(false); }}
                  // min-h-11 (44px) — the WCAG/HIG floor for a touch target,
                  // tapped a few hundred times a shift by hands that are
                  // frequently wet or gloved. Text color is computed per
                  // button rather than hardcoded white: category colors are
                  // owner-configurable, so a fixed color would read fine on
                  // some and vanish on others.
                  className={`flex items-center gap-1.5 px-3.5 min-h-11 rounded-full whitespace-nowrap transition-all flex-shrink-0 text-xs font-semibold ${active ? 'shadow-md' : 'bg-white text-gray-700 border hover:border-gray-400'}`}
                  style={active ? { backgroundColor: bg, color: readableTextColor(bg) }
                                : { borderColor: `${bg}40` }}
                  data-testid={`pos-cat-${cat.name}`}>
                  <CategoryIcon name={cat.icon} size={14} />
                  {cat.name}
                </button>
              );
            };
            return (
              <div className="relative">
                <div className="flex gap-1.5 overflow-x-auto pb-1.5 items-center">
                  {pill(all)}
                  {visible.map(pill)}
                  {overflow.length > 0 && (
                    <button onClick={() => setShowMoreCats(v => !v)}
                      className={`flex items-center gap-1 px-3.5 min-h-11 rounded-full text-xs font-semibold border flex-shrink-0 transition-all ${showMoreCats ? '' : 'bg-gray-50 text-gray-600 hover:border-gray-400'}`}
                      style={showMoreCats ? { backgroundColor: theme.primary, color: readableTextColor(theme.primary) } : {}}
                      data-testid="pos-cat-more">
                      More · {overflow.length} {showMoreCats ? '▴' : '▾'}
                    </button>
                  )}
                </div>
                {showMoreCats && overflow.length > 0 && (
                  <div className="absolute z-30 mt-1 left-0 right-0 bg-white border rounded-xl shadow-lg p-3 grid gap-1.5 [grid-template-columns:repeat(auto-fill,minmax(140px,1fr))]"
                    data-testid="pos-cat-overflow">
                    {overflow.map(cat => (
                      <button key={cat.id || cat.name}
                        onClick={() => { setSelectedCategory(cat.name); setShowMoreCats(false); }}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold text-gray-700 hover:bg-gray-50 border border-transparent hover:border-gray-200 text-left"
                        data-testid={`pos-cat-overflow-${cat.name}`}>
                        <span className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
                          style={{ background: `${cat.color || theme.primary}15`, color: cat.color || theme.primary }}>
                          <CategoryIcon name={cat.icon} size={14} />
                        </span>
                        {cat.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
        <div className="flex-1 overflow-y-auto pr-1">
          {selectedCategory === 'All' ? (
            products.length === 0 ? (
              // Skeleton loader while products fetch — fluid grid
              <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(var(--pos-tile-min,130px),1fr))]" data-testid="pos-skeleton">
                {[...Array(12)].map((_, i) => (
                  <div key={i} className="bg-white rounded-lg border overflow-hidden animate-pulse">
                    <div className="w-full h-20 bg-gray-200" />
                    <div className="p-2 space-y-1">
                      <div className="h-3 bg-gray-200 rounded" />
                      <div className="h-3 bg-gray-100 rounded w-2/3" />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
            // Category-wise grouped view — fluid grid that adapts to viewport.
            <div className="space-y-5">
              {Object.entries(groupedByCategory).map(([cat, prods]) => {
                const meta = categories.find(c => c.name === cat);
                const collapsed = collapsedCats.includes(cat);
                return (
                <div key={cat} data-testid={`pos-category-section-${cat}`}>
                  <button
                    onClick={() => setCollapsedCats(cs => cs.includes(cat) ? cs.filter(x => x !== cat) : [...cs, cat])}
                    className="flex items-center gap-2 mb-2 sticky top-0 bg-gray-50 py-1.5 z-[1] w-full"
                    data-testid={`collapse-toggle-${cat}`}>
                    <span className="text-gray-400 text-xs">{collapsed ? '▶' : '▼'}</span>
                    {meta && <div className="w-6 h-6 rounded-md flex items-center justify-center text-white" style={{ background: meta.color }}><CategoryIcon name={meta.icon} size={13} /></div>}
                    <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">{cat}</h3>
                    <span className="text-[10px] text-gray-400">{prods.length} items</span>
                    <div className="flex-1 border-b border-dashed"></div>
                  </button>
                  {!collapsed && (
                  <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(var(--pos-tile-min,130px),1fr))]">
                    {prods.map(product => (
                      <button key={product.id}
                        onClick={() => handleProductClick(product)}
                        disabled={product.eightySixed}
                        className={`bg-white rounded-lg border transition-all overflow-hidden text-left active:scale-95 relative ${product.eightySixed ? 'opacity-50 cursor-not-allowed' : 'hover:shadow-md hover:-translate-y-0.5'}`}
                        data-testid={`product-${product.id}`}
                        data-product-card={product.id}>
                        <img src={product.image || 'https://placehold.co/200x100/e5e7eb/9ca3af?text=NUA'} alt={product.name} className="w-full h-20 object-cover" />
                        {product.eightySixed && (
                          <span className="absolute top-1 right-1 bg-red-600 text-white text-[10px] font-bold px-1.5 py-0.5 rounded">86</span>
                        )}
                        <div className="p-2">
                          <h3 className="font-medium text-xs leading-tight line-clamp-1" style={{ color: theme.text }}>{product.name}</h3>
                          <div className="flex items-center justify-between mt-1">
                            <span className="flex items-center gap-1">
                              <span className="text-sm font-bold" style={{ color: theme.primary }}>${product.price.toFixed(2)}</span>
                              {(product.modifierIds || []).length > 0 && (
                                <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: theme.secondary }} data-testid={`pos-prod-mod-hint-${product.id}`} title="Has options" />
                              )}
                            </span>
                            <span className="text-[9px] text-gray-400">{product.stock}</span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                  )}
                </div>
              );})}
            </div>
            )
          ) : (
            // Single category compact grid — fluid
            <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(var(--pos-tile-min,130px),1fr))]">
              {filteredProducts.map(product => (
                <button key={product.id}
                  onClick={() => handleProductClick(product)}
                  disabled={product.eightySixed}
                  className={`bg-white rounded-lg border transition-all overflow-hidden text-left active:scale-95 relative ${product.eightySixed ? 'opacity-50 cursor-not-allowed' : 'hover:shadow-md hover:-translate-y-0.5'}`}
                  data-testid={`product-${product.id}`}
                  data-product-card={product.id}>
                  <img src={product.image || 'https://placehold.co/200x100/e5e7eb/9ca3af?text=NUA'} alt={product.name} className="w-full h-20 object-cover" />
                  {product.eightySixed && (
                    <span className="absolute top-1 right-1 bg-red-600 text-white text-[10px] font-bold px-1.5 py-0.5 rounded">86</span>
                  )}
                  <div className="p-2">
                    <h3 className="font-medium text-xs leading-tight line-clamp-1" style={{ color: theme.text }}>{product.name}</h3>
                    <div className="flex items-center justify-between mt-1">
                      <span className="flex items-center gap-1">
                        <span className="text-sm font-bold" style={{ color: theme.primary }}>${product.price.toFixed(2)}</span>
                        {(product.modifierIds || []).length > 0 && (
                          <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: theme.secondary }} data-testid={`pos-prod-mod-hint-flat-${product.id}`} title="Has options" />
                        )}
                      </span>
                      <span className="text-[9px] text-gray-400">{product.stock}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Active Promotions — only ones that can actually fire for the
            current order type, so a dine-in-only Happy Hour doesn't show as
            "active" while ringing up a takeaway sale it will never apply to. */}
        {promotions.filter(p => p.active && (!p.channels?.length || p.channels.includes(orderType))).length > 0 && (
          <div className="mt-2 p-2.5 bg-gradient-to-r from-yellow-50 to-orange-50 rounded-lg border border-yellow-200">
            <div className="flex gap-2 overflow-x-auto items-center">
              <h3 className="text-[10px] font-bold uppercase text-yellow-700 whitespace-nowrap">Promotions</h3>
              {promotions.filter(p => p.active && (!p.channels?.length || p.channels.includes(orderType))).map(promo => (
                <div key={promo.id} className="bg-white px-3 py-1.5 rounded-md border text-xs whitespace-nowrap">
                  <span className="font-medium">{promo.name}</span>
                  <span className="ml-2 font-bold" style={{ color: theme.accent }}>{promo.discount}% OFF</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Modifier picker — docked next to the cart when a product with
          attached modifierIds is tapped, instead of a full-screen popup, so
          the cart stays visible while modifiers are picked. Also opens (in
          edit mode) when an existing cart line with modifiers is tapped. */}
      <ModifierPanel
        product={modifierSheetProduct}
        modifiers={modifiers}
        open={!!modifierSheetProduct}
        onClose={() => { setModifierSheetProduct(null); setEditingLineId(null); }}
        themeColor={theme.primary}
        initialSelections={editingLineId ? modifierSheetProduct?.selectedModifiers || [] : null}
        confirmLabel={editingLineId ? 'Update' : 'Add'}
        onConfirm={(selections, extra) => {
          if (editingLineId) {
            updateCartItemModifiers(editingLineId, selections, extra);
            toast({ title: 'Updated', description: `${modifierSheetProduct.name} modifiers changed` });
          } else {
            addToCart(modifierSheetProduct, 1, selections, extra);
            toast({ title: 'Added', description: `${modifierSheetProduct.name} with ${selections.length} option${selections.length !== 1 ? 's' : ''}` });
          }
          setModifierSheetProduct(null);
          setEditingLineId(null);
        }}
      />

      {/* Cart Panel — bigger for easier billing */}
      {/* Same min-h-0 fix as the products column — the cart-items list below
          uses flex-1 overflow-y-auto and needs this to actually scroll. */}
      <div className="w-full lg:w-[440px] flex-shrink-0 flex flex-col min-h-0 border bg-white rounded-xl shadow-sm p-4" data-testid="pos-cart-panel">
        {/* Cart / staff tabs — the second tab is named after whoever is
            logged in and surfaces their own quick actions. */}
        <div className="flex gap-1 mb-3 border-b">
          <button
            className="px-3 py-1.5 text-sm font-semibold rounded-t transition-colors"
            style={cartTab === 'cart' ? { color: theme.primary, borderBottom: `2px solid ${theme.primary}` } : { color: '#6B7280' }}
            onClick={() => setCartTab('cart')} data-testid="cart-tab-cart">
            {labels.cart || 'Current Order'}
          </button>
          <button
            className="px-3 py-1.5 text-sm font-semibold rounded-t transition-colors flex items-center gap-1.5"
            style={cartTab === 'individual' ? { color: theme.primary, borderBottom: `2px solid ${theme.primary}` } : { color: '#6B7280' }}
            onClick={() => setCartTab('individual')} data-testid="cart-tab-individual">
            <User size={14} /> {user?.name || currentUser?.name || 'Staff'}
          </button>
        </div>
        {cartTab === 'individual' ? (
          <div className="flex-1 overflow-y-auto space-y-4" data-testid="individual-panel">
            <Card><CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-full flex items-center justify-center text-white font-bold text-lg" style={{ background: theme.primary }}>
                  {(user?.name || currentUser?.name || '?').charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="font-bold" data-testid="individual-name">{user?.name || currentUser?.name || 'Staff'}</p>
                  <p className="text-xs text-gray-500 capitalize">{user?.role} · {currentLocation}</p>
                </div>
              </div>
            </CardContent></Card>

            {/* Quick kitchen-timing readout — for "how long for takeaway?" at the counter */}
            <Card><CardContent className="p-4">
              <h3 className="font-semibold text-sm mb-2 flex items-center gap-2"><Clock size={16} style={{ color: theme.primary }} /> Kitchen Timing</h3>
              {kitchenEta ? (
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-2xl font-bold" style={{ color: theme.primary }} data-testid="kitchen-eta-minutes">~{kitchenEta.estimatedWaitMinutes}m</p>
                    <p className="text-[11px] text-gray-400">estimate for a new takeaway right now</p>
                  </div>
                  <div className="text-right text-xs text-gray-500">
                    <p>{kitchenEta.queueDepth} order{kitchenEta.queueDepth === 1 ? '' : 's'} ahead</p>
                    <p>{kitchenEta.ordersCompletedToday > 0 ? `${kitchenEta.avgOrderMinutes}m avg today` : 'no completions yet today'}</p>
                  </div>
                </div>
              ) : <p className="text-sm text-gray-400">Loading…</p>}
            </CardContent></Card>

            {/* Quick options — the front-of-house actions a staff member reaches for most */}
            <Card><CardContent className="p-4">
              <h3 className="font-semibold text-sm mb-3">Quick Options</h3>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" className="justify-start" onClick={jumpToDiscounts} data-testid="quick-discounts-btn">
                  <Percent size={14} className="mr-1.5" /> Discounts
                </Button>
                <Button variant="outline" className="justify-start" onClick={() => setShowCompVoidQuick(true)} data-testid="quick-compvoid-btn">
                  <Ban size={14} className="mr-1.5" /> Void &amp; Comp
                </Button>
                <Button variant="outline" className="justify-start" onClick={() => openTablesDialog('move')} data-testid="quick-move-table-btn">
                  <ArrowRightLeft size={14} className="mr-1.5" /> Move Table
                </Button>
                <Button variant="outline" className="justify-start" onClick={() => openTablesDialog('merge')} data-testid="quick-merge-table-btn">
                  <Combine size={14} className="mr-1.5" /> Merge Table
                </Button>
                <Button variant="outline" className="justify-start col-span-2" onClick={() => openTablesDialog('split')} data-testid="quick-split-table-btn">
                  <SplitSquareHorizontal size={14} className="mr-1.5" /> Split Table / Check
                </Button>
              </div>
            </CardContent></Card>

            <Card><CardContent className="p-4">
              <h3 className="font-semibold text-sm mb-3 flex items-center gap-2"><DollarSign size={16} style={{ color: theme.primary }} /> Cash Drawer</h3>
              {canOpenDrawer ? (
                <div className="space-y-2">
                  <select className="w-full p-2 border rounded-md text-sm" value={drawerReason} onChange={e => setDrawerReason(e.target.value)} data-testid="drawer-reason">
                    <option value="change">Making change</option>
                    <option value="note_to_coin">Exchange notes for coins</option>
                    <option value="float_check">Float check</option>
                    <option value="other">Other</option>
                  </select>
                  <Input placeholder="Note (optional)" value={drawerNote} onChange={e => setDrawerNote(e.target.value)} data-testid="drawer-note" />
                  <Button className="w-full" style={{ background: theme.primary }} onClick={handleOpenDrawer} disabled={drawerBusy} data-testid="open-drawer-btn">
                    {drawerBusy ? 'Opening…' : 'Open Drawer'}
                  </Button>
                  <p className="text-[11px] text-gray-400">Every open is logged with your name, time, and reason for the owner to review.</p>
                  {drawerHistory.length > 0 && (
                    <div className="mt-3 border-t pt-2 space-y-1.5 max-h-40 overflow-y-auto" data-testid="drawer-history">
                      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Recent opens</p>
                      {drawerHistory.slice(0, 10).map(ev => (
                        <div key={ev.id} className="text-xs flex justify-between text-gray-600">
                          <span>{ev.staffName} · {ev.reason.replace('_', ' ')}</span>
                          <span className="text-gray-400">{new Date(ev.openedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-400">
                  You don't have access to open the cash drawer yet — ask the owner to grant it in Settings &gt; Permissions.
                </p>
              )}
            </CardContent></Card>
          </div>
        ) : (
        <>
        {/* Scrollable body — everything that can stack up (customer card,
            "Your Usual", cart items, AI upsell strip, totals, discount
            picker, and the payment method/cash sub-views) used to sit in
            plain flex flow with only the cart-items list itself scrollable.
            On a short viewport, a selected customer + "Your Usual" +
            AI-suggested upsells could push the cart items to zero height
            and shove the Send to Table / Proceed to Payment buttons clean
            off the bottom of the panel with no way to scroll to them —
            they weren't just hidden, they were unreachable. Wrapping the
            whole body in one scrollable region and pinning the action
            buttons below it (outside this div, so they're a fixed flex
            sibling) fixes both: everything above is always reachable by
            scrolling, and the buttons are always visible without needing
            to. */}
        <div className="flex-1 overflow-y-auto min-h-0 -mr-1 pr-1">
        {/* Customer Selection */}
        <Card className="mb-4"><CardContent className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <User size={18} style={{ color: theme.primary }} />
            <span className="font-medium text-sm">Customer</span>
          </div>
          {selectedCustomer ? (
            <div>
              <div className="flex items-center justify-between">
                <div><p className="font-medium">{selectedCustomer.name}</p><p className="text-xs text-gray-500">{selectedCustomer.membershipTier} Member {pointsBalance !== null && <span className="ml-1 text-amber-600 font-semibold">⭐ {pointsBalance} pts</span>}</p></div>
                <Button variant="ghost" size="sm" onClick={() => { setSelectedCustomer(null); setPointsBalance(null); setPointsToRedeem(0); setWallet(null); setStoreCreditApplied(0); }}>Remove</Button>
              </div>
              {/* Wallet: store credit + vouchers + occasion offers */}
              {wallet && (wallet.storeCredit > 0 || (wallet.vouchers || []).length > 0) && (
                <div className="mt-2 p-2 rounded-lg border border-emerald-200 bg-emerald-50/60 space-y-1.5" data-testid="customer-wallet">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-700">Wallet</p>
                  <div className="flex flex-wrap gap-1.5">
                    {wallet.storeCredit > 0 && (
                      <button
                        onClick={() => {
                          if (storeCreditApplied > 0) { setStoreCreditApplied(0); return; }
                          const dueBeforeCredit = totalNum + (Number(storeCreditApplied) || 0);
                          setStoreCreditApplied(Number(Math.min(wallet.storeCredit, dueBeforeCredit).toFixed(2)));
                        }}
                        className={`text-[11px] font-semibold px-2 py-1 rounded-full transition-all ${storeCreditApplied > 0 ? 'bg-emerald-800 text-white ring-2 ring-emerald-300' : 'bg-emerald-600 text-white hover:bg-emerald-700'}`}
                        title={storeCreditApplied > 0 ? 'Tap to remove store credit tender' : `Tap to apply up to $${wallet.storeCredit.toFixed(2)} credit to this order`}
                        data-testid="wallet-store-credit">
                        💳 ${wallet.storeCredit.toFixed(2)} credit{storeCreditApplied > 0 ? ` · $${Number(storeCreditApplied).toFixed(2)} applied ✓` : ''}
                      </button>
                    )}
                    {(wallet.vouchers || []).map(v => {
                      const applied = (appliedDiscounts || []).some(d => d.voucherId === v.id);
                      return (
                        <button key={v.id} disabled={applied}
                          onClick={() => {
                            addDiscount({ voucherId: v.id, label: `${v.occasion || 'Voucher'} · $${Number(v.amount).toFixed(2)}`, discount: Number(v.amount) || 0 });
                            toast({ title: 'Voucher applied', description: `${v.occasion || v.reason || 'Wallet voucher'} — $${Number(v.amount).toFixed(2)} off` });
                          }}
                          className={`text-[11px] font-semibold px-2 py-1 rounded-full border transition-all ${applied ? 'bg-gray-200 text-gray-400 border-gray-200' : 'bg-white text-emerald-700 border-emerald-300 hover:bg-emerald-100'}`}
                          title={applied ? 'Already applied to this order' : `Tap to apply $${Number(v.amount).toFixed(2)} off`}
                          data-testid={`wallet-voucher-${v.id}`}>
                          {v.occasion ? v.occasion : `🎟 ${v.reason === 'win_back' ? 'We miss you' : 'Voucher'}`} ${Number(v.amount).toFixed(2)}
                          {applied ? ' ✓' : ''}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {pointsBalance !== null && pointsBalance >= loyaltyCfg.minRedeem && (
                <div className="mt-2 p-2 bg-amber-50 rounded text-xs space-y-1" data-testid="points-pay-block">
                  <p className="text-amber-700 font-medium">Points & Pay (1 pt = ${loyaltyCfg.redeemRate} · min {loyaltyCfg.minRedeem})</p>
                  <div className="flex gap-1 items-center">
                    <Input type="number" min={loyaltyCfg.minRedeem} max={pointsBalance} step="10" value={pointsToRedeem || ''} placeholder={`${loyaltyCfg.minRedeem}-${pointsBalance}`} onChange={e => setPointsToRedeem(Math.min(pointsBalance, parseInt(e.target.value) || 0))} className="h-7 text-xs" data-testid="points-input" />
                    <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setPointsToRedeem(pointsBalance)} data-testid="use-all-pts">All</Button>
                  </div>
                  {pointsToRedeem >= loyaltyCfg.minRedeem && <p className="text-green-700 font-semibold" data-testid="redeem-value">Discount: ${(pointsToRedeem * loyaltyCfg.redeemRate).toFixed(2)}</p>}
                </div>
              )}
            </div>
          ) : (
            <>
              <CustomerCombobox
                customers={customers}
                value={null}
                theme={theme}
                onChange={async (c) => {
                  setSelectedCustomer(c);
                  if (c) {
                    try { const r = await loyaltyEngineAPI.getBalance(c.id); setPointsBalance(r.data?.points || 0); } catch {}
                    try { const r = await customersAPI.getWallet(c.id); setWallet(r.data); } catch { setWallet(null); }
                    try { const r = await phaseEFAPI.yourUsual(c.id); setYourUsual(r.data?.items || []); } catch {}
                  } else { setYourUsual([]); }
                }}
              />
              {/* Order-type strip — Dine-in / Takeaway + table picker + walk-in name */}
              <div className="mt-2 space-y-2" data-testid="order-type-strip">
                <div className="flex gap-1.5">
                  {[
                    { k: 'dine-in', label: '🍽️ Dine-in' },
                    { k: 'takeaway', label: '🥡 Takeaway' },
                  ].map(o => (
                    <button key={o.k}
                      onClick={() => { setOrderType(o.k); if (o.k === 'takeaway') setTableNumber(''); }}
                      className={`flex-1 px-2 py-1.5 rounded-md text-xs font-semibold transition ${orderType === o.k ? 'text-white shadow-sm' : 'bg-white border hover:border-gray-400'}`}
                      style={orderType === o.k ? { background: theme.primary } : {}}
                      data-testid={`order-type-${o.k}`}>
                      {o.label}
                    </button>
                  ))}
                </div>
                {orderType === 'dine-in' ? (
                  <TableNumberField
                    value={tableNumber}
                    onChange={setTableNumber}
                    tables={floorTables}
                    configured={floorConfigured}
                  />
                ) : (
                  <div className="flex gap-2 items-center">
                    <span className="text-xs text-gray-500 whitespace-nowrap">Name</span>
                    <Input
                      placeholder="Customer name for takeaway"
                      value={walkInName}
                      onChange={e => setWalkInName(e.target.value)}
                      className="h-8 text-xs flex-1"
                      data-testid="walk-in-name"
                    />
                  </div>
                )}
              </div>
            </>
          )}
        </CardContent></Card>

        {/* Your Usual — predictive suggestions for known customer */}
        {selectedCustomer && yourUsual.length > 0 && (
          <Card className="mb-3 border-amber-200 bg-amber-50" data-testid="your-usual">
            <CardContent className="p-3">
              <p className="text-xs font-bold uppercase tracking-wider text-amber-700 mb-2">⭐ Your Usual</p>
              <div className="flex gap-2 overflow-x-auto">
                {yourUsual.map(p => (
                  <button key={p.id} onClick={() => { const prod = products.find(pp => pp.id === p.id); if (prod) addToCart(prod); }} className="flex-shrink-0 bg-white border rounded-lg p-2 hover:shadow-md transition-all min-w-[110px]" data-testid={`usual-${p.id}`}>
                    {p.image && <img src={p.image} alt={p.name} className="w-full h-12 object-cover rounded mb-1" />}
                    <p className="text-xs font-medium truncate">{p.name}</p>
                    <p className="text-xs text-gray-500">${p.price} · {p.frequency}×</p>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
        {/* A live ticket for this table outranks the cart being empty — after
            a refresh the server has no cart but the food is still coming. */}
        {coursingOn && kitchenOrder && (
          <ReadyBanner courses={ready} onServe={serveCourseFromCart} busy={coursingBusy} />
        )}
        <div className="mb-4">
          {cart.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <ShoppingCart size={48} className="mx-auto mb-3 opacity-50" /><p>Cart is empty</p><p className="text-sm">Tap a product to add</p>
            </div>
          ) : coursingOn ? (
            /* Coursed service: the cart is grouped by course, each group
               carrying its own fire/hold state once the ticket is in. */
            <div className="space-y-3" data-testid="cart-coursed">
              {courseGroups.map(group => (
                <div key={group.key} className="border rounded-md overflow-hidden">
                  <CourseHeader
                    course={group}
                    config={coursingConfig}
                    kitchenOrder={kitchenOrder}
                    onFire={fireCourseFromCart}
                    onHold={holdCourseFromCart}
                    onServe={serveCourseFromCart}
                    busy={coursingBusy}
                  />
                  <div className="space-y-2 p-1.5">
                    {group.items.map(item => (
                      <div key={item.id}>
                        <SwipeableCartItem
                          item={item}
                          theme={theme}
                          onUpdateQty={updateQuantityCoursed}
                          onRemove={removeFromCartCoursed}
                          onRepeat={(it) => { addToCart(it); toast({ title: 'Repeated', description: `Added another ${it.name}` }); }}
                          onEditModifiers={handleEditCartModifiers}
                        />
                        {/* Move a single dish to another course — the kitchen
                            ticket is built from these, not from the category
                            default, once the server has overridden it. */}
                        <div className="flex items-center gap-2 pl-1 pt-0.5">
                          <span className="flex items-center gap-1">
                            <span className="text-[9px] text-gray-400 uppercase tracking-wider">Course</span>
                            <select
                              className="text-[10px] border rounded px-1 py-0.5 bg-white"
                              value={lineCourse(item, coursingConfig)}
                              onChange={e => setLineCourse(item.id, parseInt(e.target.value, 10))}
                              data-testid={`cart-course-select-${item.id}`}
                            >
                              {courseKeys(coursingConfig).map(k => (
                                <option key={k} value={k}>{courseLabel(k, coursingConfig)}</option>
                              ))}
                            </select>
                          </span>
                          {useSeats && (
                            <span data-testid={`cart-seat-wrap-${item.id}`}>
                              <SeatPicker
                                value={item.seat ?? null}
                                seats={seats}
                                onChange={(s) => setLineSeat(item.id, s)}
                              />
                            </span>
                          )}
                          {(sentQty[item.id] || 0) > 0 && (
                            <span className="text-[9px] text-emerald-600" data-testid={`cart-line-sent-${item.id}`}>
                              {(sentQty[item.id] || 0) >= (item.quantity || 0)
                                ? 'on ticket'
                                : `${sentQty[item.id]} of ${item.quantity} on ticket`}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {cart.map(item => (
                <SwipeableCartItem
                  key={item.id}
                  item={item}
                  theme={theme}
                  onUpdateQty={updateQuantity}
                  onRemove={removeFromCart}
                  onRepeat={(it) => { addToCart(it); toast({ title: 'Repeated', description: `Added another ${it.name}` }); }}
                  onEditModifiers={handleEditCartModifiers}
                />
              ))}
            </div>
          )}
        </div>

        {/* Send-to-kitchen / straight fire. Only for coursed service — a
            takeaway counter just takes payment and the docket prints. */}
        {coursingOn && cart.length > 0 && (
          <div className="mb-3">
            <SendToKitchenBar
              config={coursingConfig}
              sent={!!kitchenOrder}
              busy={coursingBusy}
              disabled={tableBlocked}
              pendingItems={pendingCount}
              rounds={kitchenOrder?.rounds || 1}
              onSend={() => sendCartToKitchen(false)}
              onStraightFire={() => sendCartToKitchen(true)}
            />
          </div>
        )}

        {/* Wave 2 — AI Upsell strip */}
        {cart.length > 0 && (upsells.length > 0 || upsellLoading) && (
          <div className="mb-3" data-testid="upsell-strip">
            <div className="text-[10px] font-bold uppercase tracking-widest text-amber-700 mb-1.5 flex items-center gap-1.5">
              <span>✨ AI suggests</span>
              {upsellLoading && <span className="text-gray-400 normal-case font-normal">thinking…</span>}
            </div>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {upsells.map(s => {
                const prod = products.find(p => p.id === s.productId);
                if (!prod) return null;
                return (
                  <button
                    key={s.productId}
                    onClick={() => { addToCart(prod); toast({ title: 'Added', description: s.reason || s.name }); }}
                    className="flex-shrink-0 bg-amber-50 border border-amber-200 rounded-lg p-2 hover:shadow-md hover:-translate-y-0.5 transition-all text-left min-w-[140px] max-w-[180px]"
                    data-testid={`upsell-${s.productId}`}
                  >
                    <div className="text-xs font-semibold text-amber-900 truncate">{s.name}</div>
                    <div className="text-[10px] text-amber-700 line-clamp-2">{s.reason || ''}</div>
                    <div className="text-xs font-bold text-amber-900 mt-1">+${Number(s.price).toFixed(2)}</div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Totals + Loyalty preview */}
        {cart.length > 0 && (
          <Card className="mb-4"><CardContent className="p-4 space-y-2">
            <div className="flex justify-between text-sm"><span>{labels.subtotal || 'Subtotal'}</span><span>${totals.subtotal}</span></div>
            {parseFloat(totals.tierDiscount) > 0 && (
              <div className="flex justify-between text-sm text-purple-700" data-testid="tier-discount-row">
                <span>👑 {selectedCustomer?.membershipTier} member discount</span>
                <span>-${totals.tierDiscount}</span>
              </div>
            )}
            {/* Applied discounts (auto promotions + manual vouchers) */}
            {(appliedDiscounts || []).map((d, i) => {
              const key = d.promotionId || d.voucherId || d.id;
              return (
                <div key={key || i} className="flex justify-between text-sm text-emerald-700" data-testid={`applied-discount-${key}`}>
                  <span className="flex items-center gap-1.5 truncate">
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100">{d.auto ? 'AUTO' : 'VOUCHER'}</span>
                    <span className="truncate">{d.label}</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    -${Number(d.discount).toFixed(2)}
                    {!d.auto && (
                      <button onClick={() => removeDiscount(key)} className="text-emerald-600 hover:text-red-600" data-testid={`remove-discount-${key}`}>×</button>
                    )}
                  </span>
                </div>
              );
            })}
            {totals.pointsDiscount && (
              <div className="flex justify-between text-sm text-green-700" data-testid="points-discount-row">
                <span>⭐ Points redeemed ({pointsToRedeem} pts)</span><span>-${totals.pointsDiscount}</span>
              </div>
            )}
            {(appliedGiftCards || []).map(gc => (
              <div key={gc.code} className="flex justify-between text-sm text-violet-700" data-testid={`gift-tender-${gc.code}`}>
                <span className="flex items-center gap-1.5 truncate">
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-violet-100">GIFT</span>
                  <span className="font-mono truncate">{gc.code}</span>
                </span>
                <span className="flex items-center gap-1.5">
                  -${Number(gc.amount).toFixed(2)}
                  <button onClick={() => removeGiftCard(gc.code)} className="text-violet-600 hover:text-red-600" data-testid={`remove-gift-${gc.code}`}>×</button>
                </span>
              </div>
            ))}
            {parseFloat(totals.storeCreditApplied) > 0 && (
              <div className="flex justify-between text-sm text-emerald-700" data-testid="store-credit-tender">
                <span className="flex items-center gap-1.5">
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100">CREDIT</span>
                  Store credit
                </span>
                <span className="flex items-center gap-1.5">
                  -${totals.storeCreditApplied}
                  <button onClick={() => setStoreCreditApplied(0)} className="text-emerald-600 hover:text-red-600" data-testid="remove-store-credit">×</button>
                </span>
              </div>
            )}
            {selectedCustomer && (
              <div className="flex justify-between text-xs bg-amber-50 -mx-2 px-2 py-1 rounded" data-testid="loyalty-preview">
                <span className="text-amber-700">⭐ Loyalty preview</span>
                <span className="font-bold text-amber-700">+{Math.floor(parseFloat(totals.total))} pts</span>
              </div>
            )}
            {parseFloat(totals.surchargeAmount) > 0 && (
              <div className="flex justify-between text-sm text-amber-700" data-testid="surcharge-row">
                <span>⚡ {totals.surchargeReason || `Surcharge (${totals.surchargePercent}%)`}</span>
                <span>+${totals.surchargeAmount}</span>
              </div>
            )}
            <div className="border-t pt-2 flex justify-between font-bold text-lg"><span>{labels.total || 'Total'}</span><span style={{ color: theme.primary }} data-testid="pos-total">${totals.total}</span></div>
            <div className="flex justify-between text-[11px] text-gray-400" data-testid="gst-included-note">
              <span>{labels.tax || 'GST Included'}</span><span>${totals.gst}</span>
            </div>
            {(appliedGiftCards.length > 0 || parseFloat(totals.storeCreditApplied) > 0) && (
              <div className="flex justify-between text-sm font-semibold text-violet-700" data-testid="pos-balance-due">
                <span>Balance due (after tenders)</span><span>${totals.balanceDue}</span>
              </div>
            )}
            <p className="text-[10px] text-gray-400 text-center pt-1">Prices include GST</p>
          </CardContent></Card>
        )}

        {/* Discount picker — opens above Proceed to Payment */}
        {!showPayment && cart.length > 0 && (
          <Card className="mb-3"><CardContent className="p-3">
            {!showDiscountPicker ? (
              <Button variant="outline" className="w-full" onClick={() => setShowDiscountPicker(true)} data-testid="open-discount-picker">
                🎟️ Apply discount / voucher / gift card
              </Button>
            ) : (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <Input value={voucherCode} onChange={e => setVoucherCode(e.target.value)}
                    placeholder="Voucher code (NUA-XXXX)" className="text-sm" data-testid="voucher-code-input" />
                  <ScanVoucherButton onDetected={handleScannedVoucher} />
                  <Button onClick={() => applyManualCode()} disabled={voucherLoading || !voucherCode} data-testid="apply-voucher-btn" style={{ background: theme.primary }}>
                    {voucherLoading ? '…' : 'Apply'}
                  </Button>
                </div>
                <div className="flex gap-2">
                  <Input value={giftCodeInput} onChange={e => setGiftCodeInput(e.target.value)}
                    placeholder="Gift card code (GC-XXXX)" className="text-sm" data-testid="gift-code-input" />
                  <Button onClick={applyGiftCard} disabled={giftLoading || !giftCodeInput} data-testid="apply-gift-btn"
                    className="bg-violet-600 hover:bg-violet-700 text-white">
                    {giftLoading ? '…' : '🎁 Apply'}
                  </Button>
                </div>
                {(availableVouchers.length > 0 || universalVouchers.length > 0) && (
                  <div className="space-y-1 max-h-44 overflow-y-auto" data-testid="voucher-list">
                    <p className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">Available</p>
                    {[...availableVouchers, ...universalVouchers].filter(v => v.active).map(v => (
                      <button key={`${v._source}-${v.id}`} onClick={() => applyAvailableVoucher(v)}
                        className="w-full text-left p-2 border rounded text-xs hover:bg-amber-50 hover:border-amber-300 transition" data-testid={`voucher-${v.id}`}>
                        <div className="flex justify-between items-center font-semibold">
                          <span className="flex items-center gap-1.5">
                            <span className={`text-[9px] uppercase tracking-wide px-1 py-0.5 rounded font-bold ${v._source === 'v29' ? 'bg-violet-100 text-violet-600' : 'bg-blue-100 text-blue-600'}`}>
                              {v._source === 'v29' ? 'Voucher' : 'Coupon'}
                            </span>
                            {v.name}
                          </span>
                          <span className="text-amber-700">{v.discountType === 'percent' ? `${v.value}%` : `$${v.value}`} off</span>
                        </div>
                        <div className="text-[10px] text-gray-500 font-mono">{v.manualCode}</div>
                      </button>
                    ))}
                  </div>
                )}
                <Button variant="ghost" size="sm" onClick={() => setShowDiscountPicker(false)} className="w-full">Close</Button>
              </div>
            )}
          </CardContent></Card>
        )}
        </div>
        {/* End of scrollable body — the actions below are a fixed flex
            sibling, not part of the scroll region, so they stay visible
            without needing to scroll to them. */}

        {/* Send-to-Table + Payment buttons */}
        {!showPayment && cart.length > 0 && (
          <div className="flex gap-2" data-testid="pos-checkout-actions">
            <Button
              variant="outline"
              className="flex-1 h-14 text-base font-semibold"
              onClick={async () => {
                // Refresh first so table statuses in the picker are current.
                // (This used to read `p.active`, which no floor plan has — the
                // field is `isActive` — so it always fell through to plan [0].)
                await loadFloorTables();
                setSendToTableOpen(true);
              }}
              data-testid="pos-send-to-table">
              Send to Table
            </Button>
            <Button className="flex-1 h-14 text-base font-semibold" style={{ backgroundColor: theme.primary }}
              disabled={tableBlocked}
              title={tableBlocked ? tableCheck.message : undefined}
              onClick={() => {
                // Belt-and-braces: the button is disabled, but a stale table
                // can still be in state if the floor plan changed underneath.
                if (tableBlocked) {
                  toast({ title: 'Unknown table', description: tableCheck.message, variant: 'destructive' });
                  return;
                }
                setShowPayment(true);
              }}
              data-testid="pos-proceed-payment">
              Proceed to Payment
            </Button>
          </div>
        )}
        {tableBlocked && cart.length > 0 && (
          <p className="text-[11px] text-red-600 text-center -mt-2 pb-1" data-testid="pos-table-blocked">
            {tableCheck.message} — fix the table number to take payment.
          </p>
        )}

        {/* Payment Methods Panel + Cash Payment Panel — same fixed-height
            cart panel as the body above, but these two were never given
            their own scroll region either. On a short/embedded viewport
            (e.g. a kiosk tablet with an on-screen keyboard eating vertical
            space) Split Payment / Cancel / Complete Sale could get pushed
            out of the panel with nothing able to scroll to them — this is
            the literal payment step, hit on every sale. */}
        {showPayment && (
        <div className="flex-1 overflow-y-auto min-h-0 -mr-1 pr-1">
        {/* Payment Methods Panel */}
        {paymentView === 'methods' && (
          <div className="space-y-2" data-testid="payment-methods-panel">
            <div className="grid grid-cols-2 gap-2">
              <Button className="h-14 flex-col gap-1" variant="outline" onClick={() => handleCheckout('Card')} data-testid="pay-card">
                <CreditCard size={20} /><span className="text-xs">Card</span>
              </Button>
              <Button className="h-14 flex-col gap-1" variant="outline" onClick={() => { setCashTendered(0); setPaymentView('cash'); }} data-testid="pay-cash">
                <Banknote size={20} /><span className="text-xs">Cash</span>
              </Button>
              <Button className="h-14 flex-col gap-1" variant="outline" onClick={() => handleGenerateQR('qr_code')} data-testid="pay-qr">
                <QrCode size={20} /><span className="text-xs">QR Code</span>
              </Button>
              <Button className="h-14 flex-col gap-1" variant="outline" onClick={() => handleGenerateQR('upi')} data-testid="pay-upi">
                <Smartphone size={20} /><span className="text-xs">UPI</span>
              </Button>
            </div>
            <Button className="w-full h-12 bg-violet-600 hover:bg-violet-700 text-white font-medium"
              onClick={handleStripeCheckout} disabled={loading} data-testid="pay-stripe">
              <CreditCard size={18} className="mr-2" /> Pay with Stripe
            </Button>
            <Button className="w-full h-12 bg-gray-200 text-gray-500 font-medium cursor-not-allowed" disabled
              title="Afterpay / Klarna isn't connected yet" data-testid="pay-bnpl">
              <CreditCard size={18} className="mr-2" /> Pay Later (Afterpay / Klarna) — Coming soon
            </Button>
            <Button className="w-full h-12 bg-orange-500 hover:bg-orange-600 text-white font-medium"
              onClick={handleCryptoCheckout} disabled={loading} data-testid="pay-crypto">
              ₿ Pay with Crypto (BTC / USDC)
            </Button>
            <Button className="w-full h-14 bg-indigo-600 hover:bg-indigo-700 text-white font-medium"
              onClick={handleStartSplit} data-testid="pay-split">
              <SplitSquareHorizontal size={20} className="mr-2" /> Split Payment
            </Button>
            {orderType === 'dine-in' && tableNumber && (
              <Button className="w-full h-12" variant="outline" onClick={() => setSplitLinkOpen(true)} data-testid="pay-split-link">
                <QrCode size={18} className="mr-2" /> Split via Guest Link
              </Button>
            )}
            <Button className="w-full" variant="ghost" onClick={resetPayment} data-testid="pay-cancel">Cancel</Button>
          </div>
        )}

        {/* Cash Payment Panel */}
        {paymentView === 'cash' && (
          <div className="space-y-3" data-testid="cash-payment-panel">
            {!showCashChange ? (
              <>
                <div className="text-center p-3 bg-gray-100 rounded-lg">
                  <p className="text-sm text-gray-500">Amount Due</p>
                  <p className="text-3xl font-bold" style={{ color: theme.primary }}>${totalNum.toFixed(2)}</p>
                </div>
                <p className="text-sm font-medium text-gray-600 text-center">Select amount tendered</p>
                <div className="grid grid-cols-3 gap-2">
                  <Button variant="outline" className="h-12 font-bold" onClick={() => { setCashTendered(totalNum); setShowCashChange(true); }} data-testid="cash-exact">Exact</Button>
                  <Button variant="outline" className="h-12 font-bold" onClick={() => { setCashTendered(Math.ceil(totalNum)); setShowCashChange(true); }} data-testid="cash-round">Round Up</Button>
                  {[5, 10, 20, 50, 100].map(amt => (
                    <Button key={amt} variant="outline" className="h-12 font-bold" disabled={amt < totalNum}
                      onClick={() => { setCashTendered(amt); setShowCashChange(true); }} data-testid={`cash-${amt}`}>
                      ${amt}
                    </Button>
                  ))}
                  <Button variant="outline" className="h-12 font-bold col-span-3" onClick={() => {
                    const custom = prompt('Enter amount tendered:');
                    if (custom && parseFloat(custom) >= totalNum) { setCashTendered(parseFloat(custom)); setShowCashChange(true); }
                    else if (custom) toast({ title: "Error", description: "Amount must be >= total", variant: "destructive" });
                  }} data-testid="cash-custom">Custom Amount</Button>
                </div>
                <Button variant="ghost" className="w-full" onClick={() => setPaymentView('methods')}><ChevronLeft size={16} className="mr-1" /> Back</Button>
              </>
            ) : (
              <div className="space-y-3">
                <div className="text-center p-4 bg-emerald-50 rounded-lg border border-emerald-200">
                  <p className="text-sm text-gray-600">Tendered</p>
                  <p className="text-2xl font-bold text-emerald-700">${cashTendered.toFixed(2)}</p>
                </div>
                <div className="text-center p-4 bg-blue-50 rounded-lg border border-blue-200">
                  <p className="text-sm text-gray-600">Change Due</p>
                  <p className="text-3xl font-bold text-blue-700" data-testid="cash-change">${(cashTendered - totalNum).toFixed(2)}</p>
                </div>
                <Button className="w-full h-14 text-lg font-semibold bg-emerald-600 hover:bg-emerald-700 text-white"
                  onClick={() => { handleCheckout('Cash'); setShowCashChange(false); }} data-testid="cash-complete">
                  Complete Sale
                </Button>
                <Button variant="ghost" className="w-full" onClick={() => setShowCashChange(false)}>Back</Button>
              </div>
            )}
          </div>
        )}
        </div>
        )}
        </>
        )}
      </div>

      {/* ========== Payment Dialogs (QR / UPI / Split) ========== */}
      <QrPaymentDialog
        open={paymentView === 'qr'} onClose={() => setPaymentView('methods')}
        qrData={qrData} total={totalNum} onConfirm={handleConfirmQRPayment} loading={loading}
      />
      <UpiPaymentDialog
        open={paymentView === 'upi'} onClose={() => setPaymentView('methods')}
        qrData={qrData} total={totalNum} onConfirm={handleConfirmQRPayment} loading={loading}
        onCopyUpi={copyToClipboard}
      />
      <SplitPaymentDialog
        open={paymentView === 'split'} onClose={() => setPaymentView('methods')}
        total={totalNum}
        splitParts={splitParts} splitMode={splitMode} splitCount={splitCount}
        seatsAvailable={useSeats && cartWithCourses.some(i => i.seat != null)}
        cartItems={cartWithCourses}
        itemAssignments={itemAssignments}
        onAdjustItemAssignment={adjustItemAssignment}
        customers={customers}
        onSetMode={(m) => {
          if (m === 'seat') {
            if (!initSeatSplitParts()) {
              toast({ title: 'No seats assigned', description: 'Assign seats to cart lines first.', variant: 'destructive' });
              return;
            }
            setSplitMode('seat');
            return;
          }
          if (m === 'items') {
            setItemAssignments({});
            setSplitMode('items');
            recalcItemSplitParts({}, splitCount);
            return;
          }
          setSplitMode(m);
          if (m === 'equal') initSplitParts(splitCount, 'equal');
        }}
        onChangeCount={recalcEqualSplit}
        onUpdatePart={updateSplitPart}
        onPayPart={handlePaySplit}
        splitRemaining={splitRemaining}
        loading={loading} activeSplitIndex={activeSplitIndex}
      />

      <SplitBillLinkDialog
        open={splitLinkOpen} onClose={() => setSplitLinkOpen(false)}
        tableNumber={tableNumber} businessId={user?.businessId}
      />

      {/* QR / UPI scan dialog stacked on top of the split dialog. Nothing is
          marked paid until the cashier taps Confirm — solves the earlier bug
          where selecting UPI/QR on a split silently confirmed the payment. */}
      <QrPaymentDialog
        open={splitQrView === 'qr'}
        onClose={cancelSplitQr}
        qrData={splitQrData || {}}
        total={Number(splitQrData?.amount || 0)}
        onConfirm={confirmSplitQr}
        loading={loading}
      />
      <UpiPaymentDialog
        open={splitQrView === 'upi'}
        onClose={cancelSplitQr}
        qrData={splitQrData || {}}
        total={Number(splitQrData?.amount || 0)}
        onConfirm={confirmSplitQr}
        loading={loading}
        onCopyUpi={copyToClipboard}
      />


      {/* Send-to-Table dialog */}
      <Dialog open={sendToTableOpen} onOpenChange={setSendToTableOpen}>
        <DialogContent className="max-w-2xl" data-testid="send-to-table-dialog">
          <DialogHeader>
            <DialogTitle>Send order to a table</DialogTitle>
          </DialogHeader>
          <p className="text-xs text-gray-500 mb-2">Pick a table — the current cart becomes an open tab on that table so floor staff can settle it later.</p>
          <div className="grid grid-cols-3 md:grid-cols-5 gap-2 max-h-[55vh] overflow-y-auto">
            {floorTables.length === 0 && (
              <div className="col-span-full text-center text-gray-400 py-6 text-sm" data-testid="send-no-tables">
                No floor plan configured. Set one up in Reservations → Floor Plan.
              </div>
            )}
            {floorTables.map(t => (
              <button
                key={t.id}
                disabled={sendingToTable}
                onClick={async () => {
                  setSendingToTable(true);
                  try {
                    const name = selectedCustomer?.name || walkInName || `Table ${t.number}`;
                    await v15API.createTab({
                      name: `Table ${t.number} — ${name}`,
                      cart, selectedCustomer,
                      tableId: t.id,
                      tableNumber: t.number,
                    });
                    toast({ title: `Sent to Table ${t.number}`, description: 'Ready for later payment.' });
                    // Fire kitchen prints so food fires immediately.
                    try {
                      await gamificationAPI.sendToPrinters({
                        items: cart.map(i => ({ productName: i.name, category: i.category, quantity: i.quantity })),
                        orderId: `TABLE-${t.number}`, tableNumber: t.number,
                      });
                    } catch (err) { /* printer optional */ }
                    // Reflect the tab on the floor plan.
                    try { await floorPlansAPI.occupyByNumber(t.number, `TABLE-${t.number}`); } catch {}
                    setSendToTableOpen(false);
                    setTableNumber(String(t.number));
                    clearCart();
                    loadFloorTables();
                  } catch (e) {
                    toast({ title: 'Send failed', description: e?.response?.data?.detail, variant: 'destructive' });
                  } finally { setSendingToTable(false); }
                }}
                className="rounded-lg border-2 p-3 hover:border-current transition-all disabled:opacity-50 disabled:cursor-not-allowed text-left"
                style={{ borderColor: t.status === 'available' ? '#10b981' : '#f59e0b' }}
                data-testid={`send-table-${t.id}`}
              >
                <div className="font-bold text-lg" style={{ color: theme.text }}>#{t.number}</div>
                <div className="text-[10px] text-gray-500 uppercase tracking-wide">{t.section || 'main'}</div>
                <div className="text-[10px] text-gray-400 mt-0.5">seats {t.capacity || t.maxCovers || 2}</div>
                <div className="text-[10px] mt-1 capitalize" style={{ color: t.status === 'available' ? '#10b981' : '#f59e0b' }}>
                  {t.status || 'available'}
                </div>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {/* Open Tabs (Hold / Recall) */}
      <Dialog open={showTabsDialog} onOpenChange={(o) => { setShowTabsDialog(o); if (!o) setTablesDialogMode('view'); }}>
        <DialogContent className="max-w-md" data-testid="tabs-dialog">
          <DialogHeader>
            <DialogTitle>
              {tablesDialogMode === 'move' ? 'Move Table' : tablesDialogMode === 'merge' ? 'Merge Tables' : tablesDialogMode === 'split' ? 'Split Table / Check' : `Open Tabs (${openTabs.length})`}
            </DialogTitle>
          </DialogHeader>
          {tablesDialogMode === 'merge' && (
            <p className="text-xs text-gray-500 -mt-2">Select 2 or more tabs — their items merge into the first one selected, the rest close.</p>
          )}
          <div className="space-y-2 max-h-[60vh] overflow-y-auto">
            {openTabs.map(t => (
              <Card key={t.id} data-testid={`tab-${t.id}`}>
                <CardContent className="p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      {tablesDialogMode === 'merge' && (
                        <input type="checkbox" checked={mergeSelection.includes(t.id)}
                          onChange={e => setMergeSelection(sel => e.target.checked ? [...sel, t.id] : sel.filter(id => id !== t.id))}
                          data-testid={`merge-select-${t.id}`} />
                      )}
                      <div className="min-w-0">
                        <p className="font-semibold text-sm truncate">{t.name}</p>
                        <p className="text-xs text-gray-500">{t.cart?.length || 0} items · table {t.tableNumber || '—'} · {t.createdByName}</p>
                      </div>
                    </div>

                    {tablesDialogMode === 'view' && (
                      <div className="flex gap-1 flex-shrink-0">
                        <Button size="sm" onClick={async () => {
                          clearCart();
                          (t.cart || []).forEach(i => { for (let n = 0; n < i.quantity; n++) addToCart({ ...i }); });
                          if (t.selectedCustomer) setSelectedCustomer(t.selectedCustomer);
                          await v15API.deleteTab(t.id);
                          setHeldCheckoutTabs(prev => prev.filter(h => h.id !== t.id));
                          setShowTabsDialog(false);
                          toast({ title: 'Tab recalled' });
                        }} style={{ backgroundColor: theme.primary }} data-testid={`recall-${t.id}`}>Recall</Button>
                        <Button size="sm" variant="outline" className="text-red-500" onClick={async () => {
                          await v15API.deleteTab(t.id);
                          setOpenTabs(openTabs.filter(o => o.id !== t.id));
                          setHeldCheckoutTabs(prev => prev.filter(h => h.id !== t.id));
                        }}>×</Button>
                      </div>
                    )}
                    {tablesDialogMode === 'move' && movingTab !== t.id && (
                      <Button size="sm" variant="outline" className="flex-shrink-0" onClick={() => { setMovingTab(t.id); setMoveTargetTable(t.tableNumber || ''); }} data-testid={`start-move-${t.id}`}>Move</Button>
                    )}
                    {tablesDialogMode === 'split' && splittingTab !== t.id && (
                      <Button size="sm" variant="outline" className="flex-shrink-0" onClick={() => setSplittingTab(t.id)} data-testid={`start-split-${t.id}`}>Split</Button>
                    )}
                  </div>

                  {tablesDialogMode === 'move' && movingTab === t.id && (
                    <div className="flex gap-2 mt-2">
                      <Input placeholder="New table #" value={moveTargetTable} onChange={e => setMoveTargetTable(e.target.value)} className="h-8 text-sm" data-testid="move-target-table" />
                      <Button size="sm" style={{ backgroundColor: theme.primary }} onClick={() => handleMoveTable(t.id)} data-testid={`confirm-move-${t.id}`}>Go</Button>
                      <Button size="sm" variant="ghost" onClick={() => setMovingTab(null)}>Cancel</Button>
                    </div>
                  )}
                  {tablesDialogMode === 'split' && splittingTab === t.id && (
                    <div className="flex items-center gap-2 mt-2">
                      <select className="border rounded-md text-sm p-1.5" value={splitWays} onChange={e => setSplitWays(parseInt(e.target.value, 10))} data-testid="split-ways">
                        <option value={2}>2 ways</option>
                        <option value={3}>3 ways</option>
                        <option value={4}>4 ways</option>
                      </select>
                      <Button size="sm" style={{ backgroundColor: theme.primary }} onClick={() => handleSplitTable(t.id)} data-testid={`confirm-split-${t.id}`}>Split</Button>
                      <Button size="sm" variant="ghost" onClick={() => setSplittingTab(null)}>Cancel</Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
            {openTabs.length === 0 && <p className="text-center text-gray-400 py-8 text-sm">No tabs on hold</p>}
          </div>
          {tablesDialogMode === 'merge' && openTabs.length > 0 && (
            <Button className="w-full mt-2" style={{ backgroundColor: theme.primary }} disabled={mergeSelection.length < 2} onClick={handleMergeTables} data-testid="confirm-merge-btn">
              Merge {mergeSelection.length > 0 ? `${mergeSelection.length} tabs` : 'selected'}
            </Button>
          )}
        </DialogContent>
      </Dialog>

      {/* Quick Comp/Void — reachable from the staff tab without leaving the till */}
      <Dialog open={showCompVoidQuick} onOpenChange={setShowCompVoidQuick}>
        <DialogContent className="max-w-sm" data-testid="quick-compvoid-dialog">
          <DialogHeader><DialogTitle>Record Comp or Void</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => setCompVoidForm(f => ({ ...f, type: 'comp' }))}
                className={`p-3 rounded-lg border-2 text-sm font-medium transition-all ${compVoidForm.type === 'comp' ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600'}`}
                data-testid="quick-cv-type-comp"><Gift size={16} className="mx-auto mb-1" />Comp</button>
              <button onClick={() => setCompVoidForm(f => ({ ...f, type: 'void' }))}
                className={`p-3 rounded-lg border-2 text-sm font-medium transition-all ${compVoidForm.type === 'void' ? 'border-red-500 bg-red-50 text-red-700' : 'border-gray-200 text-gray-600'}`}
                data-testid="quick-cv-type-void"><Ban size={16} className="mx-auto mb-1" />Void</button>
            </div>
            <Input placeholder="Reason (e.g. Wrong order, Customer complaint)" value={compVoidForm.reason} onChange={e => setCompVoidForm(f => ({ ...f, reason: e.target.value }))} data-testid="quick-cv-reason" />
            <Input type="number" step="0.01" placeholder="Amount ($)" value={compVoidForm.amount} onChange={e => setCompVoidForm(f => ({ ...f, amount: e.target.value }))} data-testid="quick-cv-amount" />
            {lastTxnId && <p className="text-[11px] text-gray-400">Linked to your last transaction: {lastTxnId}</p>}
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={compVoidForm.printVoid} onChange={e => setCompVoidForm(f => ({ ...f, printVoid: e.target.checked }))} /> Print void ticket to kitchen</label>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleQuickCompVoid} disabled={compVoidBusy} data-testid="quick-cv-save-btn">
              {compVoidBusy ? 'Saving…' : `Record ${compVoidForm.type === 'comp' ? 'Comp' : 'Void'}`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

    </div>
  );
};

export default POSTerminal;
