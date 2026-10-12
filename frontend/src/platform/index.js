/**
 * Platform abstraction layer (ADR-001). Business logic/components depend on
 * these exports, never on `window`/`navigator`/`document` directly, and
 * never on which OS they're running on — see docs/platform/ADR-001-
 * multiplatform-architecture.md for the full rationale.
 *
 * Each service below is a plain object with the same method signatures
 * across every platform implementation; this file is the only place that
 * picks which one a given method call actually runs.
 */
import * as webDialog from './web/DialogService';
import * as webPrint from './web/PrintService';
import * as webFile from './web/FileService';
import * as webClipboard from './web/ClipboardService';
import * as webNetwork from './web/NetworkService';
import * as webSecureStorage from './web/SecureStorageService';
import * as webDeviceIdentity from './web/DeviceIdentityService';

import * as capacitorDialog from './capacitor/DialogService';
import * as capacitorPrint from './capacitor/PrintService';
import * as capacitorFile from './capacitor/FileService';
import * as capacitorClipboard from './capacitor/ClipboardService';
import * as capacitorNetwork from './capacitor/NetworkService';
import * as capacitorSecureStorage from './capacitor/SecureStorageService';
import * as capacitorDeviceIdentity from './capacitor/DeviceIdentityService';

/** 'web' | 'android' | 'ios' | 'electron' */
export function detectPlatform() {
  if (typeof window === 'undefined') return 'web';
  const cap = window.Capacitor;
  if (cap?.isNativePlatform?.()) {
    // 'android' | 'ios' — Capacitor's own platform name, not a guess.
    return cap.getPlatform();
  }
  if (window.electronAPI?.isElectron) return 'electron';
  return 'web';
}

export function isNative() {
  const p = detectPlatform();
  return p === 'android' || p === 'ios';
}

const platform = detectPlatform();
const isCapacitor = platform === 'android' || platform === 'ios';

// Electron support for these services is ChatGPT's lane (see
// docs/platform/COLLABORATION.md) — falls back to the web implementation
// for now, which is exactly correct for an Electron renderer (it's a real
// Chromium browser context, same APIs as web) until/unless Electron-
// specific IPC implementations land.
export const DialogService = isCapacitor ? capacitorDialog : webDialog;
export const PrintService = isCapacitor ? capacitorPrint : webPrint;
export const FileService = isCapacitor ? capacitorFile : webFile;
export const ClipboardService = isCapacitor ? capacitorClipboard : webClipboard;
export const NetworkService = isCapacitor ? capacitorNetwork : webNetwork;
export const SecureStorageService = isCapacitor ? capacitorSecureStorage : webSecureStorage;
export const DeviceIdentityService = isCapacitor ? capacitorDeviceIdentity : webDeviceIdentity;
