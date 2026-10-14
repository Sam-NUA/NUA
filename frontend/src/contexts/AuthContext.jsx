import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { SecureStorageService, DeviceIdentityService, isNative, NetworkService } from '../platform';
import { bindTerminalSession } from '../services/terminalSession';
import * as offlineQueue from '../lib/offlineQueue';

const AuthContext = createContext(null);
const API = process.env.REACT_APP_BACKEND_URL;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);     // null = checking, false = not auth'd
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);
  const authGeneration = useRef(0);
  const assertCurrent = (generation) => {
    if (authGeneration.current !== generation) throw new Error('Sign-in session changed');
  };

  const checkAuth = useCallback(async () => {
    const generation = ++authGeneration.current;
    setLoading(true);
    setAuthError(false);
    offlineQueue.lock();
    try {
      const token = await SecureStorageService.getToken();
      if (!token) { offlineQueue.lock(); setUser(false); setLoading(false); return; }
      const res = await axios.get(`${API}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      assertCurrent(generation);
      const bound = await bindTerminalSession(res.data, token);
      assertCurrent(generation);
      await offlineQueue.activate(res.data.businessId, bound);
      assertCurrent(generation);
      setUser(res.data);
    } catch (error) {
      if (authGeneration.current !== generation) return;
      if ([401, 403, 409].includes(error.response?.status)) {
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
    if (authGeneration.current === generation) setLoading(false);
  }, []);

  useEffect(() => { checkAuth(); }, [checkAuth]);
  useEffect(() => {
    if (!authError) return;
    const retry = () => { checkAuth(); };
    const unsubscribe = NetworkService.addStatusListener(({ connected }) => { if (connected) retry(); });
    const timer = setInterval(retry, 30000);
    return () => { unsubscribe(); clearInterval(timer); };
  }, [authError, checkAuth]);

  // A correct password is not the same as being signed in. When the account
  // carries a second factor the backend answers with a challenge instead of a
  // token, and the caller has to come back through completeTwoFactor. The
  // shape below makes that explicit so no caller can mistake a challenge for
  // a successful login.
  const login = async (email, password) => {
    const generation = ++authGeneration.current;
    offlineQueue.lock();
    // A device that previously registered (see platform/*/DeviceIdentityService)
    // identifies itself on login so a revoked terminal is rejected outright —
    // see backend/routes/auth.py's _resolve_device_id and
    // docs/platform/DEVICE_IDENTITY_MODEL.md. Most sessions (web without an
    // explicit registration, any device before its first registration call)
    // have none, and log in exactly as before this existed.
    const deviceHeaders = await DeviceIdentityService.getLoginHeaders();
    const res = await axios.post(
      `${API}/api/auth/login`,
      { email, password, deviceToken: isNative() ? undefined : localStorage.getItem('nua_device_token') || undefined },
      { withCredentials: true, headers: deviceHeaders },
    );
    assertCurrent(generation);
    if (res.data.twoFactorRequired) return { twoFactor: res.data };
    assertCurrent(generation);
    await SecureStorageService.setToken(res.data.token);
    assertCurrent(generation);
    const bound = await bindTerminalSession(res.data.user, res.data.token);
    assertCurrent(generation);
    await offlineQueue.activate(res.data.user.businessId, bound);
    assertCurrent(generation);
    setUser(res.data.user);
    return { user: res.data.user };
  };

  const completeTwoFactor = async (challengeToken, code, trustDevice) => {
    const generation = ++authGeneration.current;
    const deviceHeaders = await DeviceIdentityService.getLoginHeaders();
    const res = await axios.post(
      `${API}/api/auth/2fa/challenge`,
      { challengeToken, code, trustDevice: !isNative() && !!trustDevice },
      { withCredentials: true, headers: deviceHeaders },
    );
    assertCurrent(generation);
    await SecureStorageService.setToken(res.data.token);
    // Kept alongside the cookie: a tablet running the POS as a home-screen app
    // doesn't always get third-party cookies back, and being asked for a code
    // every shift is what drives staff to write the seed on the wall.
    if (!isNative() && res.data.deviceToken) localStorage.setItem('nua_device_token', res.data.deviceToken);
    assertCurrent(generation);
    const bound = await bindTerminalSession(res.data.user, res.data.token);
    assertCurrent(generation);
    await offlineQueue.activate(res.data.user.businessId, bound);
    assertCurrent(generation);
    setUser(res.data.user);
    return res.data;
  };

  const logout = async () => {
    authGeneration.current += 1;
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
