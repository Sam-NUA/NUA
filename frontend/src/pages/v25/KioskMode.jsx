import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { v25API, productsAPI } from '../../services/api';
import { useTheme } from '../../contexts/ThemeContext';
import { useToast } from '../../hooks/use-toast';
import { Smartphone } from 'lucide-react';
import { useLanguage } from '../../i18n/useLanguage';
import { LanguageSelector } from '../../i18n/LanguageSelector';
import { coursingAPI } from '../../services/api';
import { courseForCategory, courseLabel, courseKeys } from '../../lib/coursing';

function productName(p, lang) {
  return p?.translations?.[lang]?.name || p.name;
}

export default function KioskMode() {
  const business = new URLSearchParams(window.location.search).get("business") || undefined;
  const { theme } = useTheme(); const { toast } = useToast();
  const { lang, setLang, t, dir, languages } = useLanguage('nua_kiosk_lang');
  const [products, setProducts] = useState([]);
  const [session, setSession] = useState(null);
  const [cart, setCart] = useState([]);
  // Coursing config, so a dine-in kiosk can show and change the course a dish
  // lands on. A takeaway kiosk never sees any of this — the venue's own
  // straight-fire rules already say a counter order goes out together.
  const [coursing, setCoursing] = useState(null);
  // productId -> { loading, original, substitutes } while a guest is looking
  // at alternatives for an 86'd item they tapped.
  const [substituteFor, setSubstituteFor] = useState(null);
  useEffect(() => {
    // Unauthenticated (the kiosk calls this with no token, same as any
    // guest-facing menu), so /api/products already strips cost/stock/sku
    // for us. 86'd items stay in the list (unlike an earlier version of
    // this fix, which hid them outright) so a guest who taps one gets an
    // AI-suggested alternative instead of the item just not existing —
    // still can't add it to the cart directly, same protection as before.
    productsAPI.getAll({ business })
      .then(r => setProducts(Array.isArray(r.data) ? r.data : []))
      .catch(() => toast({ title: "Could not load this venue’s menu", variant: "destructive" }));
  }, []);
  useEffect(() => { coursingAPI.getConfig().then(r => setCoursing(r.data)).catch(() => setCoursing(null)); }, []);

  // Only dine-in kiosks course. `tableId` on the session is what makes it
  // dine-in; without one this is a counter order.
  const dineIn = !!session?.tableId;
  const showCourses = !!coursing?.enabled && dineIn;

  const start = async () => { const r = await v25API.kioskStart({ guests: 2, business }); setSession(r.data); setCart([]); };

  const add = (p) => {
    if (p.eightySixed) { showSubstitutes(p); return; }
    const line = {
      ...p,
      lineId: `${p.id}-${Date.now()}`,
      course: showCourses ? courseForCategory(p.category, coursing) : undefined,
    };
    setCart(prev => [...prev, line]);
    v25API.kioskAdd(session.id, {
      productId: p.id, name: p.name, category: p.category,
      price: p.price, quantity: 1, lineId: line.lineId,
      ...(line.course ? { course: line.course } : {}),
    });
  };

  const showSubstitutes = async (p) => {
    setSubstituteFor({ loading: true, original: p, substitutes: [] });
    try {
      const r = await v25API.substitute(p.id);
      setSubstituteFor({ loading: false, original: r.data.original, substitutes: r.data.substitutes || [] });
    } catch {
      setSubstituteFor(null);
      toast({ title: t('kiosk.substituteFailed') || "Couldn't load alternatives", variant: 'destructive' });
    }
  };

  const addSubstitute = (p) => {
    setSubstituteFor(null);
    add(p);
  };

  // Moving a dish to another course has to reach the session, not just the
  // screen — the ticket is built from the stored cart, not from this state.
  const moveCourse = async (lineId, course) => {
    setCart(prev => prev.map(l => (l.lineId === lineId ? { ...l, course } : l)));
    try {
      await v25API.kioskSetCourse(session.id, { lineId, course });
    } catch { /* the guest sees their choice; the send-side default still applies */ }
  };

  const checkout = async () => { await v25API.kioskCheckout(session.id); toast({ title: t('kiosk.orderSent') }); setSession(null); setCart([]); };
  return (
    <div className="space-y-6" dir={dir} data-testid="kiosk-page">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}><Smartphone className="text-blue-600" /> {t('kiosk.title')}</h1>
        <div className="flex items-center gap-3">
          <LanguageSelector lang={lang} setLang={setLang} languages={languages} variant="light" label={t('common.language')} />
          {!session ? <Button onClick={start} style={{ background: theme.primary }} data-testid="kiosk-start">{t('kiosk.startOrder')}</Button> :
            <Button onClick={checkout} style={{ background: theme.primary }} data-testid="kiosk-checkout">{t('kiosk.checkout')} ({cart.length})</Button>}
        </div>
      </div>
      {session && showCourses && cart.length > 0 && (
        <Card><CardContent className="p-3 space-y-1" data-testid="kiosk-courses">
          <p className="text-xs font-semibold">{t('kiosk.yourOrder') || 'Your order'}</p>
          {cart.map(l => (
            <div key={l.lineId} className="flex items-center gap-2 text-sm" data-testid={`kiosk-line-${l.lineId}`}>
              <span className="flex-1 truncate">{productName(l, lang)}</span>
              <select
                className="text-xs border rounded px-1 py-0.5 bg-white"
                value={l.course ?? ''}
                onChange={e => moveCourse(l.lineId, parseInt(e.target.value, 10))}
                data-testid={`kiosk-course-${l.lineId}`}
              >
                {courseKeys(coursing).map(k => (
                  <option key={k} value={k}>{courseLabel(k, coursing)}</option>
                ))}
              </select>
            </div>
          ))}
          <p className="text-[10px] text-gray-500 pt-1">
            Courses come out one at a time — move a dish if you'd like it earlier or later.
          </p>
        </CardContent></Card>
      )}

      {session && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {products.slice(0, 12).map(p => (
            <button key={p.id} onClick={() => add(p)}
              className={`border rounded-xl p-4 transition-all text-left relative ${
                p.eightySixed ? 'opacity-60' : 'hover:shadow-md hover:-translate-y-0.5'
              }`}
              data-testid={`kiosk-prod-${p.id}`}>
              <p className="font-bold">{productName(p, lang)}</p>
              {p.eightySixed ? (
                <p className="text-xs font-medium text-amber-600 mt-1">{t('kiosk.unavailableTapForAlternatives') || 'Unavailable — tap for alternatives'}</p>
              ) : (
                <p className="text-lg" style={{ color: theme.primary }}>${p.price}</p>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Substitute suggestions for an 86'd item the guest tapped */}
      {substituteFor && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setSubstituteFor(null)}>
          <Card className="max-w-md w-full" onClick={e => e.stopPropagation()} data-testid="kiosk-substitutes">
            <CardContent className="p-5 space-y-3">
              <p className="font-bold">
                {t('kiosk.notAvailable', { name: productName(substituteFor.original, lang) })
                  || `${productName(substituteFor.original, lang)} isn't available right now`}
              </p>
              {substituteFor.loading ? (
                <p className="text-sm text-gray-400">{t('kiosk.loadingAlternatives') || 'Finding alternatives…'}</p>
              ) : substituteFor.substitutes.length === 0 ? (
                <p className="text-sm text-gray-400">{t('kiosk.noAlternatives') || 'No similar items available right now.'}</p>
              ) : (
                <div className="space-y-2">
                  {substituteFor.substitutes.map(s => (
                    <button key={s.id} onClick={() => addSubstitute(s)}
                      className="w-full flex items-center justify-between border rounded-lg p-3 hover:shadow-sm text-left"
                      data-testid={`kiosk-substitute-${s.id}`}>
                      <span>
                        <span className="font-semibold block">{productName(s, lang)}</span>
                        <span className="text-xs text-gray-500">{s.substitutionReason}</span>
                      </span>
                      <span className="font-bold" style={{ color: theme.primary }}>${s.price}</span>
                    </button>
                  ))}
                </div>
              )}
              <Button variant="outline" className="w-full" onClick={() => setSubstituteFor(null)}>
                {t('common.cancel') || 'Cancel'}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
