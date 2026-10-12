import { Dialog } from '@capacitor/dialog';

/** Native Capacitor dialogs. @capacitor/dialog has no prompt() — there's
 * no OS-level text-input dialog primitive on Android/iOS the way there is
 * for alert/confirm, so a text prompt on native falls back to the web
 * (in-WebView) window.prompt, which Capacitor's WebView still supports;
 * replacing it with a real React modal is tracked in
 * docs/platform/MOBILE_DESKTOP_BACKLOG.md rather than faked here. */
export async function confirm(message) {
  const { value } = await Dialog.confirm({ title: 'NUA POS', message });
  return value;
}

export async function prompt(message, defaultValue = '') {
  // eslint-disable-next-line no-restricted-globals
  return window.prompt(message, defaultValue);
}

export async function alert(message) {
  await Dialog.alert({ title: 'NUA POS', message });
}
