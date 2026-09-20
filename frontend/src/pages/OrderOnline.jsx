import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ShoppingBag, MapPin, Store, Bike, Plus, Minus, Clock, ArrowRight, Trash2 } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { CategoryIcon } from './Categories';
import { onlineAPI } from '../services/api';
import { useToast } from '../hooks/use-toast';
import { useLanguage } from '../i18n/useLanguage';
import { LanguageSelector } from '../i18n/LanguageSelector';

function productName(p, lang) { return p?.translations?.[lang]?.name || p.name; }

export default function OrderOnline() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // ?business=<slug-or-id> — a deployment with multiple businesses hands
  // each one its own online-ordering link. Absent on a single-business
  // deployment, where it's a no-op (backend treats it the same as unset).
  const businessParam = searchParams.get('business') || undefined;
  const businessQuery = businessParam ? `?business=${encodeURIComponent(businessParam)}` : '';
  const { toast } = useToast();
  const { lang, setLang, t, dir, languages } = useLanguage('nua_online_lang');
  const CHANNELS = [
    { key: 'pickup', label: t('orderOnline.channelPickup'), icon: Store, hint: t('orderOnline.channelPickupHint') },
    { key: 'delivery', label: t('orderOnline.channelDelivery'), icon: Bike, hint: t('orderOnline.channelDeliveryHint') },
    { key: 'dine-in', label: t('orderOnline.channelDineIn'), icon: ShoppingBag, hint: t('orderOnline.channelDineInHint') },
  ];
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [selectedCat, setSelectedCat] = useState('All');
  const [cart, setCart] = useState([]);
  const [channel, setChannel] = useState('pickup');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [address, setAddress] = useState('');
  const [notes, setNotes] = useState('');
  const [placing, setPlacing] = useState(false);
  const [voucherCode, setVoucherCode] = useState('');
  const [voucherApplied, setVoucherApplied] = useState(null); // { code, discount, label }
  const [voucherChecking, setVoucherChecking] = useState(false);
  const [voucherError, setVoucherError] = useState('');
  // null = no ?business= param (normal, unscoped menu) or still checking;
  // true/false once a param is present and its resolution is known. Without
  // this, a stale or mistyped ?business= slug silently fell back to showing
  // every business's menu combined instead of telling the guest their link
  // is broken.
  const [businessFound, setBusinessFound] = useState(null);
  const [menuLoading, setMenuLoading] = useState(true);
  const [menuError, setMenuError] = useState(false);

  useEffect(() => {
    if (!businessParam) { setBusinessFound(null); return; }
    onlineAPI.businessInfo(businessParam)
      .then(r => setBusinessFound(!!r.data?.found))
      .catch(() => setBusinessFound(null));
  }, [businessParam]);

  const loadMenu = React.useCallback(() => {
    setMenuLoading(true);
    setMenuError(false);
    Promise.all([onlineAPI.publicProducts(businessParam), onlineAPI.publicCategories(businessParam)])
      .then(([p, c]) => { setProducts(p.data || []); setCategories(c.data || []); })
      // A guest hitting a slow/broken backend used to just see an empty
      // product grid with zero explanation — no loading state, no error,
      // no way to tell "nothing on the menu" from "couldn't load the menu."
      .catch(() => setMenuError(true))
      .finally(() => setMenuLoading(false));
  }, [businessParam]);

  useEffect(() => {
    if (businessParam && businessFound === false) return;
    loadMenu();
  }, [businessParam, businessFound, loadMenu]);

  // Filter categories by selected channel
  const cats = useMemo(() => categories.filter(c => true), [categories]);

  const filteredProducts = selectedCat === 'All'
    ? products
    : products.filter(p => p.category === selectedCat);

  // Menu prices already include GST — it's disclosed below, not added on top.
  const subtotal = cart.reduce((s, i) => s + i.price * i.quantity, 0);
  const voucherDiscount = voucherApplied ? Math.min(voucherApplied.discount, subtotal) : 0;
  const total = Math.max(0, subtotal - voucherDiscount);
  const gst = total / 11;

  // Discount is re-checked against the live cart whenever it changes so a
  // stale "applied" voucher can't silently overstate its discount.
  useEffect(() => {
    setVoucherApplied(prev => {
      if (!prev) return prev;
      setVoucherError(t('orderOnline.voucherRecheckPrompt'));
      return null;
    });
    // eslint-disable-next-line
  }, [cart]);

  const applyVoucher = async () => {
    if (!voucherCode.trim()) return;
    setVoucherChecking(true);
    setVoucherError('');
    try {
      const r = await onlineAPI.checkVoucher(voucherCode.trim(), cart.map(i => ({ price: i.price, quantity: i.quantity, category: i.category, id: i.id })), businessParam);
      if (r.data?.valid) {
        setVoucherApplied({ code: voucherCode.trim(), discount: r.data.discount, label: r.data.label });
      } else {
        setVoucherApplied(null);
        setVoucherError(r.data?.reason || t('orderOnline.voucherInvalid'));
      }
    } catch (e) {
      setVoucherApplied(null);
      setVoucherError(e?.response?.data?.detail || t('orderOnline.voucherInvalid'));
    } finally { setVoucherChecking(false); }
  };

  const maxPrepMin = useMemo(() => {
    if (cart.length === 0) return 0;
    return Math.max(...cart.map(i => {
      const c = cats.find(cc => cc.name === i.category);
      return c?.prepTime || 8;
    }));
  }, [cart, cats]);

  const addItem = (p) => setCart(prev => {
    const ex = prev.find(x => x.id === p.id);
    if (ex) return prev.map(x => x.id === p.id ? { ...x, quantity: x.quantity + 1 } : x);
    return [...prev, { id: p.id, name: p.name, price: p.price, quantity: 1, category: p.category, image: p.image, translations: p.translations }];
  });
  const updQty = (id, d) => setCart(prev =>
    prev.map(x => x.id === id ? { ...x, quantity: Math.max(0, x.quantity + d) } : x).filter(x => x.quantity > 0)
  );
  const removeItem = (id) => setCart(prev => prev.filter(x => x.id !== id));

  const place = async () => {
    if (!name) { toast({ title: t('orderOnline.toastNameRequired'), variant: 'destructive' }); return; }
    if (cart.length === 0) { toast({ title: t('orderOnline.toastCartEmpty'), variant: 'destructive' }); return; }
    if (channel === 'delivery' && !address) { toast({ title: t('orderOnline.toastAddressRequired'), variant: 'destructive' }); return; }
    setPlacing(true);
    try {
      const r = await onlineAPI.placeOrder({
        items: cart.map(i => ({ id: i.id, productId: i.id, name: i.name, price: i.price, quantity: i.quantity, category: i.category })),
        channel,
        customerName: name, customerPhone: phone, customerEmail: email,
        address: channel === 'delivery' ? address : '', notes,
        voucherCode: voucherApplied?.code || undefined,
        business: businessParam,
      });
      toast({ title: t('orderOnline.toastOrderPlaced'), description: t('orderOnline.toastTrackingCode', { code: r.data.id }) });
      // If Stripe is configured, send the guest to pay now instead of the
      // old "pay at pickup" default — falls back to the tracking page (same
      // as before this existed) if payments aren't set up for this venue.
      try {
        const pay = await onlineAPI.checkout(r.data.id, window.location.origin, businessParam);
        if (pay.data?.configured && pay.data?.url) { window.location.href = pay.data.url; return; }
      } catch { /* fall through to tracking page */ }
      navigate(`/track/${r.data.id}${businessQuery}`);
    } catch (e) {
      toast({ title: t('orderOnline.toastFailed'), description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setPlacing(false); }
  };

  if (businessParam && businessFound === false) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6" data-testid="order-online-not-found">
        <Card className="max-w-md w-full">
          <CardContent className="p-8 text-center space-y-2">
            <Store className="mx-auto text-gray-300" size={40} />
            <h1 className="text-xl font-bold">Ordering link not found</h1>
            <p className="text-sm text-gray-500">
              This link doesn't match a business we know about. Double-check the link, or ask the venue for their current online-ordering link.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50" dir={dir} data-testid="order-online-page">
      <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-5">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">{t('orderOnline.brandTitle')}</h1>
            <p className="text-sm text-gray-500">{t('orderOnline.subtitle')}</p>
          </div>
          <div className="flex items-center gap-3">
            <LanguageSelector lang={lang} setLang={setLang} languages={languages} variant="light" label={t('common.language')} />
            <Button variant="ghost" onClick={() => navigate(`/rewards${businessQuery}`)} className="text-sm">{t('orderOnline.myRewards')}</Button>
            <Button variant="ghost" onClick={() => navigate(`/track${businessQuery}`)} className="text-sm">{t('orderOnline.trackOrder')}</Button>
          </div>
        </header>

        {/* Channel picker */}
        <div className="grid grid-cols-3 gap-2" data-testid="channel-picker">
          {CHANNELS.map(c => {
            const Active = c.icon;
            const on = channel === c.key;
            return (
              <button key={c.key} onClick={() => setChannel(c.key)}
                className={`p-4 rounded-xl border-2 transition flex items-center gap-3 ${on ? 'border-gray-900 bg-white shadow-sm' : 'border-transparent bg-white hover:border-gray-300'}`}
                data-testid={`channel-${c.key}`}>
                <Active size={20} className={on ? 'text-gray-900' : 'text-gray-400'} />
                <div className="text-left">
                  <p className={`font-bold text-sm ${on ? '' : 'text-gray-600'}`}>{c.label}</p>
                  <p className="text-[10px] text-gray-400">{c.hint}</p>
                </div>
              </button>
            );
          })}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Catalog */}
          <div className="lg:col-span-2 space-y-3">
            <div className="flex gap-2 overflow-x-auto pb-1">
              <button onClick={() => setSelectedCat('All')}
                className={`px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap ${selectedCat === 'All' ? 'bg-gray-900 text-white' : 'bg-white border'}`}
                data-testid="online-cat-All">{t('orderOnline.allCategory')}</button>
              {cats.map(c => (
                <button key={c.id} onClick={() => setSelectedCat(c.name)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap ${selectedCat === c.name ? 'text-white' : 'bg-white border'}`}
                  style={selectedCat === c.name ? { background: c.color } : {}}
                  data-testid={`online-cat-${c.name}`}>
                  <CategoryIcon name={c.icon} size={12} /> {c.name}
                  <span className="text-[10px] opacity-70">⏱{c.prepTime}m</span>
                </button>
              ))}
            </div>
            {menuError && (
              <div className="text-center py-10 border border-dashed rounded-lg" data-testid="online-menu-error">
                <p className="text-sm text-gray-500 mb-2">Couldn't load the menu — please check your connection.</p>
                <Button size="sm" variant="outline" onClick={loadMenu} data-testid="online-menu-retry">Try again</Button>
              </div>
            )}
            {menuLoading && !menuError && (
              <div className="text-center py-10 text-sm text-gray-400" data-testid="online-menu-loading">Loading menu…</div>
            )}
            {!menuLoading && !menuError && filteredProducts.length === 0 && (
              <div className="text-center py-10 text-sm text-gray-400" data-testid="online-menu-empty">Nothing available in this category right now.</div>
            )}
            <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(170px,1fr))]">
              {!menuLoading && !menuError && filteredProducts.map(p => (
                <Card key={p.id} className="overflow-hidden cursor-pointer hover:shadow-md transition" onClick={() => addItem(p)} data-testid={`online-product-${p.id}`}>
                  <img src={p.image || 'https://placehold.co/300x180/e5e7eb/9ca3af?text=NUA'} alt={productName(p, lang)} className="w-full h-28 object-cover" />
                  <CardContent className="p-2.5">
                    <p className="font-medium text-sm truncate">{productName(p, lang)}</p>
                    <p className="text-[10px] text-gray-400 uppercase">{p.category}</p>
                    <div className="flex justify-between items-center mt-1">
                      <span className="font-bold text-sm">${p.price.toFixed(2)}</span>
                      <Button size="sm" className="h-7 px-2 text-xs"><Plus size={11} /></Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>

          {/* Cart */}
          <Card className="lg:sticky lg:top-4 self-start">
            <CardContent className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-bold">{t('orderOnline.yourCart')} ({cart.length})</h2>
                {cart.length > 0 && <span className="flex items-center gap-1 text-xs text-purple-700"><Clock size={12} /> ~{maxPrepMin}m {t('orderOnline.prepTime')}</span>}
              </div>

              {cart.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">{t('orderOnline.emptyCartPrompt')}</p>
              ) : (
                <div className="space-y-2" data-testid="online-cart">
                  {cart.map(i => (
                    <div key={i.id} className="flex items-center gap-2">
                      <div className="flex-1">
                        <p className="text-sm font-medium">{productName(i, lang)}</p>
                        <p className="text-xs text-gray-400">${i.price.toFixed(2)} ea</p>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button size="sm" variant="outline" className="h-7 w-7 p-0" onClick={() => updQty(i.id, -1)} data-testid={`online-minus-${i.id}`}><Minus size={11} /></Button>
                        <span className="w-5 text-center text-sm">{i.quantity}</span>
                        <Button size="sm" variant="outline" className="h-7 w-7 p-0" onClick={() => updQty(i.id, 1)} data-testid={`online-plus-${i.id}`}><Plus size={11} /></Button>
                        <button onClick={() => removeItem(i.id)} className="text-gray-300 hover:text-red-600 ml-1"><Trash2 size={12} /></button>
                      </div>
                    </div>
                  ))}

                  <div className="pt-2 border-t space-y-1.5">
                    {voucherApplied ? (
                      <div className="flex items-center justify-between text-xs bg-green-50 border border-green-200 rounded-md px-2 py-1.5" data-testid="online-voucher-applied">
                        <span className="text-green-700 font-medium">{t('orderOnline.voucherAppliedLabel', { label: voucherApplied.label || voucherApplied.code })} · -${voucherDiscount.toFixed(2)}</span>
                        <button onClick={() => { setVoucherApplied(null); setVoucherCode(''); }} className="text-green-700 underline">{t('orderOnline.voucherRemove')}</button>
                      </div>
                    ) : (
                      <div className="flex gap-1.5">
                        <Input placeholder={t('orderOnline.voucherPlaceholder')} value={voucherCode}
                          onChange={e => { setVoucherCode(e.target.value); setVoucherError(''); }}
                          className="h-8 text-xs" data-testid="online-voucher-code" />
                        <Button size="sm" variant="outline" className="h-8 text-xs shrink-0" disabled={voucherChecking || !voucherCode.trim()} onClick={applyVoucher} data-testid="online-voucher-apply">
                          {voucherChecking ? t('orderOnline.voucherApplying') : t('orderOnline.voucherApplyBtn')}
                        </Button>
                      </div>
                    )}
                    {voucherError && <p className="text-[11px] text-red-600">{voucherError}</p>}
                  </div>

                  <div className="pt-2 border-t text-sm space-y-1">
                    {voucherDiscount > 0 && (
                      <div className="flex justify-between text-[11px] text-green-700"><span>Subtotal</span><span>${subtotal.toFixed(2)} - ${voucherDiscount.toFixed(2)}</span></div>
                    )}
                    <div className="flex justify-between font-bold"><span>{t('common.total')}</span><span>${total.toFixed(2)}</span></div>
                    <div className="flex justify-between text-[11px] text-gray-400"><span>{t('common.gstIncluded')}</span><span>${gst.toFixed(2)}</span></div>
                    <p className="text-[10px] text-gray-400 text-center">{t('common.pricesIncludeGst')}</p>
                  </div>

                  <div className="pt-2 border-t space-y-2">
                    <Input placeholder={t('orderOnline.namePlaceholder')} value={name} onChange={e => setName(e.target.value)} data-testid="online-name" />
                    <Input placeholder={t('orderOnline.phonePlaceholder')} value={phone} onChange={e => setPhone(e.target.value)} data-testid="online-phone" />
                    <Input placeholder={t('orderOnline.emailPlaceholder')} value={email} onChange={e => setEmail(e.target.value)} />
                    {channel === 'delivery' && (
                      <Textarea rows={2} placeholder={t('orderOnline.addressPlaceholder')} value={address} onChange={e => setAddress(e.target.value)} data-testid="online-address" />
                    )}
                    <Textarea rows={2} placeholder={t('orderOnline.notesPlaceholder')} value={notes} onChange={e => setNotes(e.target.value)} />
                  </div>

                  <Button onClick={place} disabled={placing} className="w-full bg-gray-900 hover:bg-black text-white" data-testid="place-order-btn">
                    {placing ? t('orderOnline.placing') : (<><ArrowRight size={14} className="mr-1" /> {t('orderOnline.placeOrderBtn')} · ${total.toFixed(2)}</>)}
                  </Button>
                  <p className="text-[10px] text-gray-400 text-center">
                    {t('orderOnline.paymentCollectedAt', { location: channel === 'delivery' ? t('orderOnline.deliveryWord') : t('orderOnline.pickupWord') })}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
