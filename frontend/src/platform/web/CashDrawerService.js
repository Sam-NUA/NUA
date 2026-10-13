/** Directive Phase 7 — cash drawer, modeled independently of any printer
 * (a drawer doesn't necessarily connect to the same machine that prints
 * receipts). No integration exists on any platform today — no printer
 * kick-pulse, USB, serial, or vendor SDK trigger. `open()` rejects rather
 * than fabricating success: a silently-no-op "open" that a cashier
 * believes worked is worse than one that visibly fails. See
 * MOBILE_DESKTOP_BACKLOG.md. */
export function getCapability() {
  return { status: 'unsupported', reason: 'No cash drawer integration exists on this platform.' };
}

export async function open() {
  throw new Error('Cash drawer control is not available on this platform.');
}
