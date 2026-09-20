import { useState, useEffect, useCallback } from 'react';
import { guestSessionAPI } from '../services/api';

// One verified phone session shared across every guest-facing surface
// (booking, waitlist, online ordering) — verify once, and returning guests
// on the same device don't have to re-type their name/phone/email on the
// next page that asks. Not a login: the token is short-lived (60 min,
// server-enforced) and carries no role, just "this phone was verified."


export function useGuestSession(business) {
  const storageKey = `nua_guest_session:${business || "single-venue"}`;
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  const clearSession = useCallback(() => {
    localStorage.removeItem(storageKey);
    setProfile(null);
  }, [storageKey]);

  useEffect(() => {
    const token = localStorage.getItem(storageKey);
    if (!token) { setLoading(false); return; }
    guestSessionAPI.me(token)
      .then(r => setProfile({ ...r.data, token }))
      .catch(() => clearSession())
      .finally(() => setLoading(false));
  }, [clearSession, storageKey]);

  const requestCode = useCallback((phone) => guestSessionAPI.requestCode(phone), []);

  const verify = useCallback(async (phone, code) => {
    const r = await guestSessionAPI.verify(phone, code, business);
    localStorage.setItem(storageKey, r.data.token);
    setProfile(r.data);
    return r.data;
  }, [business, storageKey]);

  return { profile, loading, requestCode, verify, clearSession };
}
