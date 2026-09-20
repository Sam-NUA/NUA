import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { ShoppingCart, Plus, Minus, Send, Clock, ChefHat, Check, Utensils, ArrowLeft } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { tableOrderAPI } from '../services/api';
import { toast } from 'sonner';
import { useLanguage } from '../i18n/useLanguage';
import { LanguageSelector } from '../i18n/LanguageSelector';

function itemName(item, lang) { return item?.translations?.[lang]?.name || item.name; }
function itemDescription(item, lang) { return item?.translations?.[lang]?.description || item.description; }

export default function TableOrder() {
  const { tableId } = useParams();
  const [searchParams] = useSearchParams();
  const business = searchParams.get("business") || undefined;
  const { lang, setLang, t, dir, languages } = useLanguage('nua_table_lang');
  const STATUS_MAP = {
    new: { label: t('tableOrder.statusNew'), icon: Clock, color: 'bg-blue-500' },
    preparing: { label: t('tableOrder.statusPreparing'), icon: ChefHat, color: 'bg-amber-500' },
    ready: { label: t('tableOrder.statusReady'), icon: Check, color: 'bg-green-500' },
    served: { label: t('tableOrder.statusServed'), icon: Utensils, color: 'bg-gray-400' },
  };
  const [menu, setMenu] = useState(null);
  const [cart, setCart] = useState([]);
  const [view, setView] = useState('menu'); // menu | cart | status
  const [customerName, setCustomerName] = useState('');
  const [notes, setNotes] = useState('');
  const [activeOrders, setActiveOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState(null);

  useEffect(() => {
    tableOrderAPI.getMenu(tableId, business).then(r => {
      setMenu(r.data);
      if (r.data.categories?.length) setSelectedCategory(r.data.categories[0].name);
    }).catch(() => toast.error(t('tableOrder.menuLoadFailed')));
    pollOrders();
  }, [tableId, business]);

  const pollOrders = useCallback(() => {
    tableOrderAPI.getOrders(tableId, business).then(r => setActiveOrders(r.data)).catch(() => {});
  }, [tableId, business]);

  useEffect(() => {
    const interval = setInterval(pollOrders, 8000);
    return () => clearInterval(interval);
  }, [pollOrders]);

  const addToCart = (item) => {
    setCart(prev => {
      const existing = prev.find(c => c.id === item.id);
      if (existing) return prev.map(c => c.id === item.id ? { ...c, quantity: c.quantity + 1 } : c);
      return [...prev, { ...item, quantity: 1 }];
    });
  };

  const updateQty = (id, delta) => {
    setCart(prev => prev.map(c => c.id === id ? { ...c, quantity: Math.max(0, c.quantity + delta) } : c).filter(c => c.quantity > 0));
  };

  const cartTotal = cart.reduce((sum, c) => sum + c.price * c.quantity, 0);
  const cartCount = cart.reduce((sum, c) => sum + c.quantity, 0);

  const placeOrder = async () => {
    if (!cart.length) return;
    setLoading(true);
    try {
      const res = await tableOrderAPI.placeOrder(tableId, {
        items: cart.map(c => ({ productId: c.id, quantity: c.quantity })),
        customerName: customerName || 'Guest',
        notes,
      }, business);
      toast.success(res.data.message || t('tableOrder.orderPlaced'));
      setCart([]);
      setNotes('');
      setView('status');
      pollOrders();
    } catch {
      toast.error(t('tableOrder.orderFailed'));
    } finally { setLoading(false); }
  };

  if (!menu) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="animate-pulse text-white text-lg">{t('tableOrder.loadingMenu')}</div>
    </div>
  );

  const currentCategory = menu.categories?.find(c => c.name === selectedCategory);

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col" dir={dir} data-testid="table-order-page">
      {/* Header */}
      <header className="sticky top-0 z-30 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-4 py-3">
        <div className="max-w-lg mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold">{menu.restaurantName}</h1>
            <p className="text-xs text-gray-400">
              {t('tableOrder.tableLabel')} {menu.tableInfo?.number || tableId}
              {menu.tableInfo?.section && ` - ${menu.tableInfo.section}`}
            </p>
          </div>
          <div className="flex gap-2 items-center">
            <LanguageSelector lang={lang} setLang={setLang} languages={languages} variant="dark" label={t('common.language')} />
            {activeOrders.length > 0 && (
              <Button size="sm" variant={view === 'status' ? 'default' : 'outline'}
                className="text-xs" onClick={() => setView('status')}
                data-testid="view-orders-btn">
                <Clock size={14} className="mr-1" /> {t('tableOrder.ordersBtn')} ({activeOrders.length})
              </Button>
            )}
            <button onClick={() => setView(view === 'cart' ? 'menu' : 'cart')}
              className="relative bg-white/10 hover:bg-white/20 rounded-full p-2.5 transition-colors"
              data-testid="cart-toggle-btn">
              <ShoppingCart size={20} />
              {cartCount > 0 && (
                <span className="absolute -top-1 -right-1 bg-red-500 text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center">
                  {cartCount}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      <div className="flex-1 max-w-lg mx-auto w-full px-4 pb-24">
        {/* MENU VIEW */}
        {view === 'menu' && (
          <div className="py-4 space-y-4" data-testid="menu-view">
            {/* Category Tabs */}
            <div className="flex gap-2 overflow-x-auto pb-2 -mx-4 px-4 scrollbar-hide">
              {menu.categories?.map(cat => (
                <button key={cat.name} onClick={() => setSelectedCategory(cat.name)}
                  className={`whitespace-nowrap px-4 py-2 rounded-full text-sm font-medium transition-colors ${
                    selectedCategory === cat.name ? 'bg-white text-gray-900' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                  }`} data-testid={`cat-${cat.name}`}>
                  {cat.name}
                </button>
              ))}
            </div>

            {/* Items */}
            <div className="space-y-3">
              {currentCategory?.items.map(item => {
                const inCart = cart.find(c => c.id === item.id);
                return (
                  <Card key={item.id} className="bg-gray-900 border-gray-800 hover:border-gray-700 transition-colors"
                    data-testid={`menu-item-${item.id}`}>
                    <CardContent className="p-4">
                      <div className="flex gap-3">
                        {item.image && (
                          <img src={item.image} alt={item.name} className="w-20 h-20 rounded-lg object-cover flex-shrink-0" />
                        )}
                        <div className="flex-1 min-w-0">
                          <h3 className="font-semibold text-white">{itemName(item, lang)}</h3>
                          {item.description && <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{itemDescription(item, lang)}</p>}
                          <div className="flex items-center justify-between mt-2">
                            <span className="text-lg font-bold text-emerald-400">${item.price.toFixed(2)}</span>
                            {inCart ? (
                              <div className="flex items-center gap-2 bg-white/10 rounded-full px-1">
                                <button onClick={() => updateQty(item.id, -1)} className="p-1.5 hover:bg-white/10 rounded-full"><Minus size={16} /></button>
                                <span className="font-bold text-sm w-6 text-center">{inCart.quantity}</span>
                                <button onClick={() => updateQty(item.id, 1)} className="p-1.5 hover:bg-white/10 rounded-full"><Plus size={16} /></button>
                              </div>
                            ) : (
                              <Button size="sm" onClick={() => addToCart(item)}
                                className="bg-emerald-600 hover:bg-emerald-700 text-white h-8 px-3 text-xs"
                                data-testid={`add-${item.id}`}>
                                <Plus size={14} className="mr-1" /> {t('common.add')}
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        )}

        {/* CART VIEW */}
        {view === 'cart' && (
          <div className="py-4 space-y-4" data-testid="cart-view">
            <button onClick={() => setView('menu')} className="flex items-center gap-1 text-sm text-gray-400 hover:text-white">
              <ArrowLeft size={16} /> {t('tableOrder.backToMenu')}
            </button>
            <h2 className="text-xl font-bold">{t('tableOrder.yourOrder')}</h2>
            {cart.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <ShoppingCart size={48} className="mx-auto mb-3 opacity-30" />
                <p>{t('tableOrder.cartEmpty')}</p>
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  {cart.map(item => (
                    <div key={item.id} className="flex items-center gap-3 bg-gray-900 rounded-lg p-3 border border-gray-800"
                      data-testid={`cart-item-${item.id}`}>
                      <div className="flex-1">
                        <p className="font-medium text-sm">{itemName(item, lang)}</p>
                        <p className="text-xs text-gray-400">${item.price.toFixed(2)} each</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button onClick={() => updateQty(item.id, -1)} className="w-7 h-7 rounded-full bg-gray-800 flex items-center justify-center hover:bg-gray-700"><Minus size={14} /></button>
                        <span className="font-bold text-sm w-6 text-center">{item.quantity}</span>
                        <button onClick={() => updateQty(item.id, 1)} className="w-7 h-7 rounded-full bg-gray-800 flex items-center justify-center hover:bg-gray-700"><Plus size={14} /></button>
                      </div>
                      <span className="font-bold text-emerald-400 w-16 text-right">${(item.price * item.quantity).toFixed(2)}</span>
                    </div>
                  ))}
                </div>
                <div className="space-y-3 pt-2">
                  <Input placeholder={t('tableOrder.namePlaceholder')} value={customerName}
                    onChange={e => setCustomerName(e.target.value)}
                    className="bg-gray-900 border-gray-700 text-white" data-testid="customer-name-input" />
                  <Input placeholder={t('tableOrder.notesPlaceholder')} value={notes}
                    onChange={e => setNotes(e.target.value)}
                    className="bg-gray-900 border-gray-700 text-white" data-testid="order-notes-input" />
                </div>
                <div className="bg-gray-900 rounded-lg p-4 border border-gray-800 space-y-2">
                  <div className="flex justify-between font-bold text-lg">
                    <span>{t('common.total')}</span><span className="text-emerald-400" data-testid="cart-total">${cartTotal.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between text-[11px] text-gray-500 pt-1 border-t border-gray-700"><span>{t('common.gstIncluded')}</span><span>${(cartTotal / 11).toFixed(2)}</span></div>
                  <p className="text-[10px] text-gray-500 text-center">{t('common.pricesIncludeGst')}</p>
                </div>
              </>
            )}
          </div>
        )}

        {/* ORDER STATUS VIEW */}
        {view === 'status' && (
          <div className="py-4 space-y-4" data-testid="status-view">
            <button onClick={() => setView('menu')} className="flex items-center gap-1 text-sm text-gray-400 hover:text-white">
              <ArrowLeft size={16} /> {t('tableOrder.backToMenu')}
            </button>
            <h2 className="text-xl font-bold">{t('tableOrder.yourOrders')}</h2>
            {activeOrders.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <p>{t('tableOrder.noActiveOrders')}</p>
                <Button className="mt-4" onClick={() => setView('menu')}>{t('tableOrder.browseMenu')}</Button>
              </div>
            ) : (
              <div className="space-y-4">
                {activeOrders.map(order => {
                  const statusInfo = STATUS_MAP[order.status] || STATUS_MAP.new;
                  const Icon = statusInfo.icon;
                  return (
                    <Card key={order.id} className="bg-gray-900 border-gray-800" data-testid={`order-${order.id}`}>
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-xs text-gray-400 font-mono">{order.id}</span>
                          <Badge className={`${statusInfo.color} text-white text-xs`}>
                            <Icon size={12} className="mr-1" /> {statusInfo.label}
                          </Badge>
                        </div>
                        <div className="space-y-1.5">
                          {order.items?.map((item, i) => (
                            <div key={i} className="flex justify-between text-sm">
                              <span className="text-gray-300">{item.quantity}x {item.name}</span>
                              <span className="text-gray-400">${(item.price * item.quantity).toFixed(2)}</span>
                            </div>
                          ))}
                        </div>
                        <div className="flex justify-between font-bold mt-3 pt-2 border-t border-gray-700">
                          <span>{t('common.total')}</span><span className="text-emerald-400">${order.total?.toFixed(2)}</span>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Floating Cart Bar */}
      {cartCount > 0 && view === 'menu' && (
        <div className="fixed bottom-0 left-0 right-0 bg-gray-900/95 backdrop-blur border-t border-gray-800 p-4 z-40">
          <div className="max-w-lg mx-auto">
            <Button className="w-full h-12 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-base"
              onClick={() => setView('cart')} data-testid="view-cart-btn">
              <ShoppingCart size={18} className="mr-2" /> {t('tableOrder.viewCart')} ({cartCount}) — ${cartTotal.toFixed(2)}
            </Button>
          </div>
        </div>
      )}

      {/* Place Order Button */}
      {view === 'cart' && cart.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 bg-gray-900/95 backdrop-blur border-t border-gray-800 p-4 z-40">
          <div className="max-w-lg mx-auto">
            <Button className="w-full h-12 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-base"
              onClick={placeOrder} disabled={loading} data-testid="place-order-btn">
              <Send size={18} className="mr-2" /> {loading ? t('tableOrder.placingOrder') : `${t('tableOrder.placeOrder')} — $${cartTotal.toFixed(2)}`}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
