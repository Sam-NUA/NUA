/** Electron implementation — the web `window.open` + `document.write` +
 * `print()` pattern is unconditionally denied inside the Windows host
 * (main.cjs's `restrict()` calls `setWindowOpenHandler(() => ({ action:
 * 'deny' }))` for every window, not just cross-origin ones), so it would
 * silently fail to even open a print preview. Routes raw HTML (e.g. the
 * kitchen docket, which has no fixed schema — allergens, seats, course
 * banners) through `nua:print-html`, which prints it in a disposable,
 * `javascript:false` preview window — the control that keeps a malformed
 * or hostile document from executing anything, since this path isn't
 * run through receipt.cjs's field-level escaping.
 *
 * `printReceipt` is a second, additional method — not on the shared
 * web/capacitor contract — that printer.js's printBrowser() calls
 * instead of printHtml() when it's available (feature-detected, so web/
 * capacitor behavior is completely unchanged). It routes to
 * `nua:print-receipt`, which builds and escapes the HTML natively from
 * structured fields via receipt.cjs, closing the same unescaped-
 * interpolated-receipt-HTML gap the Windows audit flagged (W07) for the
 * one call site that has fully structured data to give it. */
export async function printHtml(html) {
  const result = await window.nuaDesktop.printHtml(html);
  return result.status === 'submitted';
}

export async function printReceipt(receipt) {
  const result = await window.nuaDesktop.printReceipt(receipt);
  return result.status === 'submitted';
}
