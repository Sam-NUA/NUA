import React, { useSyncExternalStore } from 'react';
import { subscribeVersionGate, getVersionGateSnapshot } from '../lib/versionGate';
import { detectPlatform } from '../platform';
import { AlertTriangle } from 'lucide-react';

/**
 * Directive Phase 11 — the "update required" UX for VersionGateMiddleware's
 * 426. Named in MOBILE_DESKTOP_BACKLOG.md as a real gap: the backend gate
 * existed and was tested, but no native build has ever sent a version low
 * enough to trip it, so this screen had never been exercised against a
 * real 426 — only this component's own existence closes that gap, not the
 * (already-tested) backend logic.
 *
 * Mirrors LicenseLockScreen's full-page-overlay pattern (pages/
 * LicensePage.jsx) rather than inventing a new one. Unlike the license
 * lock screen, there's no "keep using the app at /billing" escape hatch —
 * an unsupported app version is unsupported everywhere, including this
 * screen's own origin, so it blocks unconditionally once tripped.
 */
export default function VersionGateLockScreen() {
  const detail = useSyncExternalStore(subscribeVersionGate, getVersionGateSnapshot);
  if (!detail) return null;

  const platform = detectPlatform();
  // Reloading a web build re-fetches whatever's currently deployed (an
  // atomic replace, not a stale cache) — a real recovery action there.
  // For native, there's nothing to reload into; the only real fix is a
  // fresh build from the platform's store, so the action and copy differ.
  const isNativePlatform = platform === 'android' || platform === 'ios' || platform === 'windows';

  return (
    <div
      className="fixed inset-0 z-[9999] bg-gradient-to-br from-slate-900 to-slate-800 text-white flex items-center justify-center p-6"
      data-testid="version-gate-lockscreen"
    >
      <div className="max-w-md w-full text-center space-y-5">
        <div className="flex justify-center">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/20 flex items-center justify-center">
            <AlertTriangle size={28} className="text-amber-400" />
          </div>
        </div>
        <h1 className="text-xl font-semibold">Update required</h1>
        <p className="text-slate-300 text-sm">
          {detail.detail || 'This app version is no longer supported.'}
        </p>
        {detail.minSupportedVersion && (
          <p className="text-slate-500 text-xs">
            Minimum supported version: {detail.minSupportedVersion}
          </p>
        )}
        {isNativePlatform ? (
          <p className="text-slate-400 text-xs">
            Update the app from your device's app store, then reopen it.
          </p>
        ) : (
          <button
            className="rounded-lg bg-white/10 hover:bg-white/20 px-5 py-2.5 text-sm font-medium transition"
            onClick={() => window.location.reload()}
            data-testid="version-gate-reload"
          >
            Reload
          </button>
        )}
      </div>
    </div>
  );
}
