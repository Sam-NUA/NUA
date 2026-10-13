/**
 * Directive Phase 13 — "device capability detection," the orchestration
 * layer: platform/index.js's detectPlatform() must pick the right
 * platform from the real global each native shell actually sets, not a
 * generic flag nothing real would set. detectPlatform()/isNative() read
 * window.Capacitor/window.nuaDesktop live on every call (they're plain
 * functions, not module-load-time constants), so this mutates those
 * globals directly between assertions rather than re-requiring the
 * module.
 */
import { detectPlatform, isNative } from '../index';

describe('detectPlatform()', () => {
  afterEach(() => {
    delete window.Capacitor;
    delete window.nuaDesktop;
  });

  it('returns "web" when no native bridge exists', () => {
    expect(detectPlatform()).toBe('web');
    expect(isNative()).toBe(false);
  });

  it('returns Capacitor\'s own platform name ("android"/"ios") when window.Capacitor says native', () => {
    window.Capacitor = { isNativePlatform: () => true, getPlatform: () => 'android' };
    expect(detectPlatform()).toBe('android');
    expect(isNative()).toBe(true);
  });

  it('returns "electron" only for the real apps/windows bridge (window.nuaDesktop), not a generic flag', () => {
    window.nuaDesktop = { getInfo: () => {} };
    expect(detectPlatform()).toBe('electron');
    expect(isNative()).toBe(true);
  });

  it('ignores window.Capacitor when isNativePlatform() reports false (a web tab with the JS SDK loaded but not running natively)', () => {
    window.Capacitor = { isNativePlatform: () => false, getPlatform: () => 'android' };
    expect(detectPlatform()).toBe('web');
  });

  it('Capacitor takes priority over window.nuaDesktop if somehow both are present', () => {
    window.Capacitor = { isNativePlatform: () => true, getPlatform: () => 'ios' };
    window.nuaDesktop = { getInfo: () => {} };
    expect(detectPlatform()).toBe('ios');
  });
});
