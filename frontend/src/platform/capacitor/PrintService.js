import { Share } from '@capacitor/share';

/** There is no OS-level "print to a popup" concept on Android/iOS, and no
 * silent-print API this app can call without a dedicated print plugin
 * (none installed — see docs/platform/HARDWARE_ABSTRACTION.md and
 * MOBILE_DESKTOP_BACKLOG.md). The network ESC/POS path
 * (services/printer.js's printToNetwork) is the PRIMARY path on every
 * platform including this one and is unaffected by any of this — this
 * function only runs as that path's fallback, or for on-screen documents
 * (gift card detail, 2FA recovery codes) that have no ESC/POS equivalent.
 * Rather than silently no-op or throw, this hands the HTML to the native
 * Share sheet so staff can still save/print it via any app that accepts
 * shared text (a real, if less direct, way to get a hard copy without a
 * network printer). */
export async function printHtml(html) {
  try {
    await Share.share({
      title: 'NUA POS',
      text: stripToPlainText(html),
      dialogTitle: 'Save or print',
    });
    return true;
  } catch {
    return false;
  }
}

function stripToPlainText(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return (div.textContent || div.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
}
