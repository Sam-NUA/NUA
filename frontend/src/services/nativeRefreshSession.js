import { Capacitor, registerPlugin } from '@capacitor/core';

let bridge;
const session = () => bridge || (bridge = registerPlugin('NuaRefreshSession'));
export const usesDurableNativeRefresh = () => Capacitor.getPlatform?.() === 'ios';

export async function commitNativeRefresh(apiUrl, token) {
  if (!usesDurableNativeRefresh()) return;
  const claims = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  if (!claims.sessionId) throw new Error('Verified terminal session required');
  const result = await session().commit({ url: apiUrl, sessionId: claims.sessionId });
  if (!result.committed) throw new Error('Native refresh was not committed');
}

export async function refreshNativeSession(apiUrl) {
  const result = await session().refresh({ url: apiUrl });
  if (!Number.isInteger(result.status) || result.status < 200 || result.status >= 300) {
    const error = new Error(result.data?.detail || 'Native refresh rejected');
    error.response = result;
    throw error;
  }
  return result;
}

export async function clearDurableNativeRefresh(apiUrl) {
  const result = await session().clear({ url: apiUrl });
  if (!result.cleared) throw new Error('Native refresh was not cleared');
}
