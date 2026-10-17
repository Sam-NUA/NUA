/** Web implementation — identical behavior to the ~30 inline
 * window.confirm/prompt/alert call sites this replaces as they're migrated
 * (see docs/platform/MOBILE_DESKTOP_BACKLOG.md for the ones not yet
 * swapped). Synchronous browser dialogs wrapped in a resolved Promise so
 * every platform shares one async-first call signature. */
export async function confirm(message) {
  return window.confirm(message);
}

export async function prompt(message, defaultValue = '') {
  return window.prompt(message, defaultValue);
}

export async function alert(message) {
  window.alert(message);
}
