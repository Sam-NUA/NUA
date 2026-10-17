/** The Windows host denies every camera permission check/request outright
 * (`setPermissionCheckHandler(() => false)` in apps/windows/src/main.cjs)
 * — BarcodeDetector support is irrelevant here since the OS-level grant
 * can never succeed, unlike web/Capacitor where it's a real, usable path.
 * See docs/platform/HARDWARE_COMPATIBILITY_MATRIX.md. */
export function isCameraScanAvailable() {
  return false;
}

export function getCapability() {
  return { status: 'unsupported', reason: "This host's session denies every camera permission request outright." };
}
