/** Single source of truth for this build's version string — directive
 * Phase 11. Must track backend/version.py's APP_VERSION; bump both
 * together when cutting a release, never one without the other. Only
 * native builds (Android/iOS/Electron) report this via X-App-Version
 * (see services/api.js) — a web deploy is live instantly for everyone,
 * so "is this client out of date" isn't a meaningful question for it the
 * way it is for an already-installed native app.
 */
export const APP_VERSION = '1.0.0';
