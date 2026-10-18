# App release strategy

Nothing in this document has been executed — per the directive, "Do not
publish anything during this assignment." This records the intended
channels so a future pass (or a human) has a plan to follow, not a
decision log of things already done.

## Channels (per the master directive)

```text
development → internal → staging → production
```

### Android

```text
Internal APK (sideload, for the team) →
Google Play Internal Testing →
Closed Testing →
Production
```

Prerequisites not yet in place: a Google Play Developer account, an app
signing keystore (NOT to be committed to git — `frontend/android/.gitignore`
already excludes `local.properties` and keystore-adjacent files by
Capacitor's default template; verify a real keystore stays out of version
control when one is generated), a Play Console listing (icon, screenshots,
privacy policy, data-safety declaration — this app handles payment and
customer PII, so the data-safety form needs real care, not a placeholder).

### Windows

```text
Internal installer (apps/windows's electron-builder NSIS output, CI-built, unsigned) →
Signed staging build →
Production installer
```

The real Windows foundation (`apps/windows/`, built on `feat/windows-
foundation` and taken over into this branch — see `WINDOWS_ARCHITECTURE.md`)
supersedes the older, stalled `frontend/electron/` scaffold referenced by
any earlier `WINDOWS_BUILD_GUIDE.md`-family doc — that scaffold is not
used to release this and never loaded its own preload script correctly
(see `CURRENT_ARCHITECTURE_AUDIT.md`'s W01). CI
(`.github/workflows/windows-foundation.yml`) already builds and uploads
an unsigned NSIS artifact on every push, as a review/CI artifact only —
not a release channel yet.

Prerequisites not yet in place: a code-signing certificate (unsigned
Windows installers trigger SmartScreen warnings that erode trust fast for
a POS system businesses are trusting with payments), a real distribution
mechanism and update-check service (nothing in `apps/windows` implements
auto-update), a device-pairing credential beyond the identity registry
itself (see `CURRENT_ARCHITECTURE_AUDIT.md`'s W09), and the still-open
decision of whether `packages/platform-core`'s cash queue gets wired into
the live app before release (see `OFFLINE_SYNC_ARCHITECTURE.md`).

### iOS

```text
Development → TestFlight → App Store
```

The native iOS project (`frontend/ios/`, `@capacitor/ios`) now exists —
generated this pass via `npx cap add ios`, which succeeds without Xcode
since Capacitor's iOS plugin resolution is Swift-Package-Manager-based.
`frontend/ios/App/App/PrivacyInfo.xcprivacy` **has since been created**
— that prerequisite is done, not open.

**Correction — a macOS build environment already exists in CI**: an
earlier version of this paragraph said nothing past scaffolding could
happen without a real Mac, a macOS CI runner, or a cloud Mac-build
service, and called that "the hardest one." That's no longer true.
`.github/workflows/ios.yml` runs on a real `macos-latest` GitHub Actions
runner, builds the actual native project for Simulator, and launches it
on a real booted iOS Simulator — its `critical-acceptance-milestone` job
goes further, driving a full Appium-based PIN-login, device-binding, and
cold-restart fault-injection acceptance run against that same real
Simulator. `internal-pilot.yml` reuses the same runner to produce an
unsigned Simulator-app ZIP as a review artifact. None of that is a
TestFlight upload or an App Store submission — those still need Apple
Developer Program enrollment, a real signing certificate and provisioning
profile (CI only builds for Simulator, which needs no signing), and the
App Store assets below — but "can't build or run past scaffolding
without a Mac" is false; this sandbox itself still can't run Xcode (it's
Linux), but the deployment as a whole already can, in CI, on every push.
Remaining prerequisites, per `IOS_IPADOS_ARCHITECTURE.md`: an Apple
Developer Program enrollment, a real (non-Simulator) signing certificate
and provisioning profile, and App Store assets (privacy policy URL,
support URL, per-device screenshots).

## Versioning (directive Phase 11 — not yet implemented)

No version-identification UI or minimum-supported-version gate exists
anywhere in the app yet (checked: no "App: x.y.z / Build: n / API: v1 /
Platform: ... / Device: ..." surface found in the frontend). This is
real, named work for a later pass — a `GET /api/version` endpoint plus a
small always-visible (or Settings-tucked) version readout, and a
`minSupportedVersion` check the backend could enforce the same way
`LicenseEnforcementMiddleware` already gates other things.

## What this pass actually shipped toward this

Nothing publish-facing — git commits on `feat/multiplatform-foundation`
only. No signing keys, no store listings, no production deploy or
Railway/Vercel change. One real exception, narrowly scoped: Windows now
has a CI pipeline (`windows-foundation.yml`) that builds an **unsigned**
NSIS installer and uploads it as a 7-day GitHub Actions artifact on every
push — a review/QA artifact, not a release channel. It has no signing
identity, isn't linked to any distribution mechanism, and nothing in this
pass treated it as one.
