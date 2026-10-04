import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const AuthContext = createContext(null);
const API = process.env.REACT_APP_BACKEND_URL || "";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);     // null = checking, false = not auth'd
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    const token = localStorage.getItem('nua_token');
    if (!token) { setUser(false); setLoading(false); return; }
    try {
      const res = await axios.get(`${API}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setUser(res.data);
    } catch {
      localStorage.removeItem('nua_token');
      setUser(false);
    }
    setLoading(false);
  }, []);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  // A correct password is not the same as being signed in. When the account
  // carries a second factor the backend answers with a challenge instead of a
  // token, and the caller has to come back through completeTwoFactor. The
  // shape below makes that explicit so no caller can mistake a challenge for
  // a successful login.
  const login = async (email, password) => {
    const res = await axios.post(
      `${API}/api/auth/login`,
      { email, password, deviceToken: localStorage.getItem('nua_device_token') || undefined },
      { withCredentials: true },
    );
    if (res.data.twoFactorRequired) return { twoFactor: res.data };
    localStorage.setItem('nua_token', res.data.token);
    setUser(res.data.user);
    return { user: res.data.user };
  };

  const completeTwoFactor = async (challengeToken, code, trustDevice) => {
    const res = await axios.post(
      `${API}/api/auth/2fa/challenge`,
      { challengeToken, code, trustDevice: !!trustDevice },
      { withCredentials: true },
    );
    localStorage.setItem('nua_token', res.data.token);
    // Kept alongside the cookie: a tablet running the POS as a home-screen app
    // doesn't always get third-party cookies back, and being asked for a code
    // every shift is what drives staff to write the seed on the wall.
    if (res.data.deviceToken) localStorage.setItem('nua_device_token', res.data.deviceToken);
    setUser(res.data.user);
    return res.data;
  };

  const logout = async () => {
    try { await axios.post(`${API}/api/auth/logout`, {}, { withCredentials: true }); } catch {}
    localStorage.removeItem('nua_token');
    setUser(false);
  };

  const hasPermission = (page) => {
    if (!user) return false;
    if (user.role === 'owner') return true;
    const perms = user.permissions || [];
    return perms.includes('*') || perms.includes(page);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, completeTwoFactor, logout, hasPermission, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
