/** Web implementation — plain localStorage, exactly today's behavior.
 * `nua_token` is kept as the literal key so this swap is behavior-neutral
 * for the existing web deployment (same storage, same key, same value). */
const TOKEN_KEY = 'nua_token';

export async function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export async function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export async function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}
