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

import * as electronDialog from './electron/DialogService';
import * as electronPrint from './electron/PrintService';
import * as electronFile from './electron/FileService';
import * as electronClipboard from './electron/ClipboardService';
import * as electronNetwork from './electron/NetworkService';
import * as electronSecureStorage from './electron/SecureStorageService';
import * as electronDeviceIdentity from './electron/DeviceIdentityService';

/** 'web' | 'android' | 'ios' | 'electron' */
export function detectPlatform() {
  if (typeof window === 'undefined') return 'web';
  const cap = window.Capacitor;
  if (cap?.isNativePlatform?.()) {
    // 'android' | 'ios' — Capacitor's own platform name, not a guess.
    return cap.getPlatform();
  }
  // window.nuaDesktop is the real bridge apps/windows/src/preload.cjs
  // exposes (see docs/platform/WINDOWS_ARCHITECTURE.md) — not a generic
  // "isElectron" flag, so this can't be set by anything other than that
  // specific, sender-validated preload script.
  if (window.nuaDesktop) return 'electron';
  return 'web';
}

/** True for a dedicated terminal/device, not a browser tab — a tablet,
 * phone or Windows PC running the native/desktop shell. Device identity
 * registration (useDeviceRegistration) and the native-backed storage/
 * print/file adapters below all key off this, not off `isCapacitor`
 * alone, since Electron is native in the same sense Capacitor is. */
export function isNative() {
  const p = detectPlatform();
  return p === 'android' || p === 'ios' || p === 'electron';
}

const platform = detectPlatform();
const isCapacitor = platform === 'android' || platform === 'ios';
const isElectron = platform === 'electron';

function pick(web, capacitor, electron) {
  if (isCapacitor) return capacitor;
  if (isElectron) return electron;
  return web;
}

export const DialogService = pick(webDialog, capacitorDialog, electronDialog);
export const PrintService = pick(webPrint, capacitorPrint, electronPrint);
export const FileService = pick(webFile, capacitorFile, electronFile);
export const ClipboardService = pick(webClipboard, capacitorClipboard, electronClipboard);
export const NetworkService = pick(webNetwork, capacitorNetwork, electronNetwork);
export const SecureStorageService = pick(webSecureStorage, capacitorSecureStorage, electronSecureStorage);
export const DeviceIdentityService = pick(webDeviceIdentity, capacitorDeviceIdentity, electronDeviceIdentity);
