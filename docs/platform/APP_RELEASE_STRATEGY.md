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
Internal installer (the existing electron-builder NSIS/portable output) →
Signed staging build →
Production installer
```

Prerequisites not yet in place: a code-signing certificate (unsigned
Windows installers trigger SmartScreen warnings that erode trust fast for
a POS system businesses are trusting with payments), a distribution
mechanism (direct download per the existing `WINDOWS_BUILD_GUIDE.md`
family of docs, or a proper installer-hosting/update-check service — none
of the existing auto-update scaffolding in `electron-package.json`
actually implements update checking yet).

### iOS

```text
Development → TestFlight → App Store
```

The native iOS project (`frontend/ios/`, `@capacitor/ios`) now exists —
generated this pass via `npx cap add ios`, which succeeds without Xcode
since Capacitor's iOS plugin resolution is Swift-Package-Manager-based.
Prerequisites still not in place, per `IOS_IPADOS_ARCHITECTURE.md`: an
Apple Developer Program enrollment, signing certificate and provisioning
profile, a `PrivacyInfo.xcprivacy` privacy manifest (not yet created —
required for App Store submission since the app uses `UserDefaults`, one
of Apple's "required reason" APIs, via `@capacitor/preferences`), App
Store assets (privacy policy URL, support URL, per-device screenshots),
and — the hardest one — **a macOS build environment**. This sandbox is
Linux; Xcode categorically does not run on it. Nothing past scaffolding
(no build, no TestFlight upload, no simulator run) can happen until a
real Mac, a macOS CI runner, or a cloud Mac-build service is available.

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
only. No signing keys, no store listings, no CI release pipeline changes.
