import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { SecureStorageService, DeviceIdentityService, isNative, NetworkService } from '../platform';
import * as offlineQueue from '../lib/offlineQueue';

const AuthContext = createContext(null);
const API = process.env.REACT_APP_BACKEND_URL;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);     // null = checking, false = not auth'd
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);

  const checkAuth = useCallback(async () => {
    setLoading(true);
    setAuthError(false);
    offlineQueue.lock();
    try {
      const token = await SecureStorageService.getToken();
      if (!token) { offlineQueue.lock(); setUser(false); setLoading(false); return; }
      const res = await axios.get(`${API}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      offlineQueue.activate(res.data.businessId);
      setUser(res.data);
    } catch (error) {
      if ([401, 403].includes(error.response?.status)) {
        // The backend actually rejected this token (expired, revoked by a
        // password change or a device revocation, invalid) — it really is
        // a signed-out session.
        offlineQueue.lock();
        setUser(false);
        try { await SecureStorageService.clearToken(); } catch { setAuthError(true); }
      } else {
        // A busy or unreachable server does not invalidate a session.
        // Keep the credential, but gate protected screens until verified —
        // see App.js's ProtectedRoutes, which renders a "try again" screen
        // on authError rather than treating this the same as a real 401.
        setAuthError(true);
      }
    }
    setLoading(false);
  }, []);

  useEffect(() => { checkAuth(); }, [checkAuth]);
  useEffect(() => {
    if (!authError) return;
    const retry = () => { checkAuth(); };
    const unsubscribe = NetworkService.addStatusListener(({ connected }) => { if (connected) retry(); });
    const timer = setInterval(retry, 30000);
    return () => { unsubscribe(); clearInterval(timer); };
  }, [authError, checkAuth]);

  // MOBILE_DESKTOP_BACKLOG.md — local offline storage must be partitioned
  // per authorised business, not shared by every business that's ever
  // logged in on this device. offlineQueue is a plain module (no React
  // access of its own), so this is the one place that tells it whose data
  // it's allowed to touch right now, same pattern as BusinessContext's own
  // user-keyed effect below.
  useEffect(() => {
    if (user && user.businessId) offlineQueue.activate(user.businessId);
    else offlineQueue.lock();
  }, [user]);

  // A correct password is not the same as being signed in. When the account
  // carries a second factor the backend answers with a challenge instead of a
  // token, and the caller has to come back through completeTwoFactor. The
  // shape below makes that explicit so no caller can mistake a challenge for
  // a successful login.
  const login = async (email, password) => {
    offlineQueue.lock();
    // A device that previously registered (see platform/*/DeviceIdentityService)
    // identifies itself on login so a revoked terminal is rejected outright —
    // see backend/routes/auth.py's _resolve_device_id and
    // docs/platform/DEVICE_IDENTITY_MODEL.md. Most sessions (web without an
    // explicit registration, any device before its first registration call)
    // have none, and log in exactly as before this existed.
    const deviceId = await DeviceIdentityService.getStoredDeviceId();
    const res = await axios.post(
      `${API}/api/auth/login`,
      { email, password, deviceToken: isNative() ? undefined : localStorage.getItem('nua_device_token') || undefined },
      { withCredentials: true, headers: deviceId ? { 'X-Device-Id': deviceId } : {} },
    );
    if (res.data.twoFactorRequired) return { twoFactor: res.data };
    await SecureStorageService.setToken(res.data.token);
    offlineQueue.activate(res.data.user.businessId);
    setUser(res.data.user);
    return { user: res.data.user };
  };

  const completeTwoFactor = async (challengeToken, code, trustDevice) => {
    const deviceId = await DeviceIdentityService.getStoredDeviceId();
    const res = await axios.post(
      `${API}/api/auth/2fa/challenge`,
      { challengeToken, code, trustDevice: !isNative() && !!trustDevice },
      { withCredentials: true, headers: deviceId ? { 'X-Device-Id': deviceId } : {} },
    );
    await SecureStorageService.setToken(res.data.token);
    // Kept alongside the cookie: a tablet running the POS as a home-screen app
    // doesn't always get third-party cookies back, and being asked for a code
    // every shift is what drives staff to write the seed on the wall.
    if (!isNative() && res.data.deviceToken) localStorage.setItem('nua_device_token', res.data.deviceToken);
    offlineQueue.activate(res.data.user.businessId);
    setUser(res.data.user);
    return res.data;
  };

  const logout = async () => {
    offlineQueue.lock();
    setUser(false);
    // Local sign-out must complete even when an offline server never answers.
    // Clear the OS/web credential before attempting cookie/session cleanup.
    let storageError;
    try { await SecureStorageService.clearToken(); }
    catch (error) { storageError = error; setAuthError(true); }
    try { await axios.post(`${API}/api/auth/logout`, {}, { withCredentials: true, timeout: 5000 }); } catch {}
    if (storageError) throw storageError;
  };

  const hasPermission = (page) => {
    if (!user) return false;
    if (user.role === 'owner') return true;
    const perms = user.permissions || [];
    return perms.includes('*') || perms.includes(page);
  };

  return (
    <AuthContext.Provider value={{ user, loading, authError, login, completeTwoFactor, logout, hasPermission, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
