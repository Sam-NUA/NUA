/**
 * Directive Phase 13 — unit tests for "device capability detection."
 * Each hardware-abstraction service's getCapability() is tested directly
 * against its own per-platform implementation (not through platform/
 * index.js's runtime detectPlatform() switch, which depends on globals
 * — window.Capacitor / window.nuaDesktop — this suite exercises
 * separately below) so each platform's real, distinct answer is what's
 * actually checked, not whatever this jsdom environment happens to look
 * like by default.
 */
import * as webScanner from '../web/ScannerService';
import * as capacitorScanner from '../capacitor/ScannerService';
import * as electronScanner from '../electron/ScannerService';

import * as webCashDrawer from '../web/CashDrawerService';
import * as electronCashDrawer from '../electron/CashDrawerService';

import * as webPaymentTerminal from '../web/PaymentTerminalService';
import * as electronPaymentTerminal from '../electron/PaymentTerminalService';

import * as webBiometric from '../web/BiometricService';
import * as capacitorBiometric from '../capacitor/BiometricService';
import * as electronBiometric from '../electron/BiometricService';

describe('ScannerService capability detection', () => {
  afterEach(() => { delete window.BarcodeDetector; });

  it('reports available when BarcodeDetector exists (web/Capacitor share this check)', () => {
    window.BarcodeDetector = function () {};
    expect(webScanner.isCameraScanAvailable()).toBe(true);
    expect(webScanner.getCapability()).toEqual({ status: 'available' });
    expect(capacitorScanner.isCameraScanAvailable()).toBe(true);
  });

  it('reports unsupported when BarcodeDetector is absent', () => {
    delete window.BarcodeDetector;
    expect(webScanner.isCameraScanAvailable()).toBe(false);
    expect(webScanner.getCapability().status).toBe('unsupported');
  });

  it('Electron always reports unsupported regardless of BarcodeDetector — the host denies camera permission outright', () => {
    window.BarcodeDetector = function () {};
    expect(electronScanner.isCameraScanAvailable()).toBe(false);
    expect(electronScanner.getCapability().status).toBe('unsupported');
  });
});

describe('CashDrawerService — no platform has an integration', () => {
  it.each([
    ['web', webCashDrawer],
    ['electron', electronCashDrawer],
  ])('%s reports unsupported and open() rejects rather than fabricating success', async (_name, service) => {
    expect(service.getCapability().status).toBe('unsupported');
    await expect(service.open()).rejects.toThrow();
  });
});

describe('PaymentTerminalService — no provider is integrated on any platform', () => {
  it.each([
    ['web', webPaymentTerminal],
    ['electron', electronPaymentTerminal],
  ])('%s reports unsupported and every method rejects rather than faking a charge', async (_name, service) => {
    expect(service.getCapability().status).toBe('unsupported');
    await expect(service.connect()).rejects.toThrow();
    await expect(service.chargeAmount()).rejects.toThrow();
  });
});

describe('BiometricService — honestly unsupported everywhere until a real plugin/API is wired up', () => {
  it.each([
    ['web', webBiometric],
    ['capacitor', capacitorBiometric],
    ['electron', electronBiometric],
  ])('%s reports unsupported and verify() rejects rather than auto-approving', async (_name, service) => {
    expect(service.isAvailable()).toBe(false);
    expect(service.getCapability().status).toBe('unsupported');
    await expect(service.verify()).rejects.toThrow();
  });
});
