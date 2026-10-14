// Native bearer tokens live in OS storage and this process only, never localStorage.
let token = null;
export function rememberToken(value) { token = value || null; }
export function getSessionToken() {
  const native = window.Capacitor?.isNativePlatform?.() || window.nuaDesktop;
  return native ? token : localStorage.getItem('nua_token');
}
