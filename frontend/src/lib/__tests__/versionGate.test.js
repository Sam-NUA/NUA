/**
 * Directive Phase 11 — the "update required" UX gap this closes: the
 * backend's 426 (VersionGateMiddleware) was already tested, but nothing
 * on the frontend had ever reacted to one. This tests the tiny store
 * api.js's response interceptor and VersionGateLockScreen share, since
 * that's the actual new logic — not a rendered-component test, matching
 * this repo's existing style (capabilityDetection.test.js tests plain
 * functions too, not rendered output).
 */
import { tripVersionGate, subscribeVersionGate, getVersionGateSnapshot } from '../versionGate';

describe('versionGate store', () => {
  it('starts untripped', () => {
    expect(getVersionGateSnapshot()).toBe(null);
  });

  it('records the 426 response body once tripped', () => {
    tripVersionGate({ detail: 'This app version is no longer supported. Please update.', minSupportedVersion: '1.2.0' });
    expect(getVersionGateSnapshot()).toEqual({
      detail: 'This app version is no longer supported. Please update.',
      minSupportedVersion: '1.2.0',
    });
  });

  it('falls back to a generic message if tripped with no detail', () => {
    tripVersionGate(undefined);
    expect(getVersionGateSnapshot()).toEqual({ detail: 'This app version is no longer supported. Please update.' });
  });

  it('notifies every subscriber on trip', () => {
    const calls = [];
    const unsubA = subscribeVersionGate(() => calls.push('a'));
    const unsubB = subscribeVersionGate(() => calls.push('b'));
    tripVersionGate({ detail: 'x' });
    expect(calls).toEqual(['a', 'b']);
    unsubA();
    unsubB();
  });

  it('stops notifying a subscriber after it unsubscribes', () => {
    const calls = [];
    const unsub = subscribeVersionGate(() => calls.push('x'));
    unsub();
    tripVersionGate({ detail: 'y' });
    expect(calls).toEqual([]);
  });
});
