/**
 * Directive Phase 12 — structured client telemetry: app launch, sync
 * failures, hardware/printer failures, device registration. Separate
 * from lib/errorReporting.js (crashes) — this is for known, named events
 * the app chooses to report, not uncaught exceptions.
 *
 * Deliberately never sends: passwords, tokens, PINs, card data — the
 * backend (services/observability.py's _redact) also strips these
 * defensively, but this module itself never reads anything from
 * SecureStorageService/AuthContext to begin with, so there's nothing
 * sensitive in `data` to redact in the common case.
 */
import { opsAPI } from '../services/api';
import { detectPlatform } from '../platform';
import { APP_VERSION } from '../version';

const KNOWN_TYPES = new Set([
  'app_launch', 'sync_failure', 'printer_failure', 'hardware_error', 'device_registered',
]);

// Same reasoning as errorReporting.js's cap — a feedback loop that fires
// telemetry on every render of a broken screen must not itself become a
// flood.
const MAX_EVENTS_PER_SESSION = 50;
let eventCount = 0;

export function trackEvent(type, data = {}) {
  if (!KNOWN_TYPES.has(type)) return;
  if (eventCount >= MAX_EVENTS_PER_SESSION) return;
  eventCount++;
  opsAPI.reportClientEvent({
    type,
    data,
    platform: detectPlatform(),
    appVersion: APP_VERSION,
    osVersion: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 300) : '',
  }).catch(() => { /* best-effort — losing a telemetry event is fine */ });
}
