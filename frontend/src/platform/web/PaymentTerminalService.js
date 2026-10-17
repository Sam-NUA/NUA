/** Directive Phase 7 — PaymentTerminalService. "Do NOT implement
 * unsupported providers merely to fill the interface" — no terminal
 * provider (Stripe Terminal, Square, Tyro, Zeller, Worldline) is
 * integrated on any platform, and none is implemented here. This is the
 * interface itself, so a real provider adapter has one contract to
 * implement later rather than inventing its own shape — see
 * docs/platform/PAYMENT_TERMINAL_ARCHITECTURE.md for why nothing beyond
 * this exists yet. Every method rejects rather than fabricating a
 * result — the payment-offline rule applies here just as much as to
 * queued orders: never a fake successful charge, never a connection
 * that silently isn't real.
 */
export function getCapability() {
  return { status: 'unsupported', reason: 'No payment-terminal provider is integrated on this platform.' };
}

export async function connect() {
  throw new Error('No payment terminal is configured for this platform.');
}

export async function chargeAmount() {
  throw new Error('No payment terminal is configured for this platform.');
}

export async function cancelCharge() {
  throw new Error('No payment terminal is configured for this platform.');
}

export async function disconnect() {
  throw new Error('No payment terminal is configured for this platform.');
}
