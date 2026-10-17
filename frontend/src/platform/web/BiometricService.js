/** Directive Phase 5 — "evaluate biometric reauthentication for managers,
 * refunds, voids, sensitive settings." No biometric plugin/API is wired
 * up on any platform — WebAuthn's platform-authenticator flow could
 * theoretically do this on web, but it needs a registered credential per
 * user and a verification ceremony this pass has no reason to build
 * speculatively ("do not implement unsupported providers merely to fill
 * the interface" — the same discipline PaymentTerminalService follows
 * applies here too). `isAvailable()` is honestly false everywhere today;
 * callers (see hooks/useSensitiveActionReauth.js) fall back to the real,
 * server-verified PIN re-entry (POST /api/auth/verify-sensitive-action)
 * this interface exists to be swapped out from under later. */
export function isAvailable() {
  return false;
}

export function getCapability() {
  return { status: 'unsupported', reason: 'No biometric authenticator is wired up on this platform.' };
}

export async function verify() {
  throw new Error('Biometric verification is not available on this platform.');
}
