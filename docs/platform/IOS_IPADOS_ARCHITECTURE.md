# iOS / iPadOS architecture

The master directive's own Phase 10 guidance said no Apple-specific work
was required until the Android architecture validated — this pass's user
instruction explicitly overrode that default ("Start with 5) iPadOS & 6)
iPhone / iOS... skip nothing as a requirement"), so this document covers
the full Phase 10 list the directive names, with the same honesty rules
as `ANDROID_ARCHITECTURE.md`: nothing claimed verified that wasn't
actually run.

## What exists

- Native project: `frontend/ios/` — generated via `npx cap add ios`
  against the same `frontend/capacitor.config.json` (`appId: com.nua.pos`)
  used for Android. Real Xcode project
  (`ios/App/App.xcodeproj/project.pbxproj`, `PRODUCT_BUNDLE_IDENTIFIER =
  com.nua.pos`), real `AppDelegate.swift`/`SceneDelegate.swift`, a Swift
  Package Manager manifest (`ios/App/CapApp-SPM/Package.swift`) listing
  all 8 plugins.
- **Unexpected positive finding**: `npx cap add ios` succeeds fully on
  this Linux sandbox with no Xcode, no CocoaPods, and no Swift toolchain
  installed (confirmed: `which swift swiftc xcodebuild pod` all empty).
  Capacitor's iOS plugin resolution is Swift-Package-Manager-based, which
  only needs the `Package.swift` manifests to exist — unlike Android's
  Gradle-based resolution, which needs live network access to
  `dl.google.com` and is blocked by this sandbox's network policy. iOS
  scaffolding is therefore *less* blocked than Android's was in this
  sandbox, even though iOS compilation is *more* blocked (see "Hard
  blocker" below) — these are two independent limits, not one.
- The same 8 Capacitor plugins used for Android (`@capacitor/app`,
  `clipboard`, `device`, `dialog`, `filesystem`, `network`, `preferences`,
  `share`) are cross-platform and already wired into
  `frontend/src/platform/capacitor/*` — no iOS-specific service code was
  needed. `platform/index.js`'s `detectPlatform()` already routes `'ios'`
  to the exact same `capacitor/*` adapters as `'android'`; this was
  verified by reading the dispatch logic, not assumed — it was built
  correctly during the Android pass by using a platform family check
  (`isCapacitor = platform === 'android' || platform === 'ios'`) rather
  than an Android-only check.

## Hard blocker: iOS compilation needs macOS, categorically, not just a network policy

Android's blocker (`./gradlew assembleDebug` failing on a `dl.google.com`
403) is a sandbox *network policy* restriction — it would resolve with a
different network configuration. iOS's blocker is different in kind:
Xcode only runs on macOS. No amount of network access in this Linux
sandbox makes `xcodebuild` exist. This was confirmed directly
(`which xcodebuild pod swift swiftc` → all empty; `uname -s` → `Linux`),
not inferred from general knowledge. Nothing short of a macOS build
runner (a real Mac, a macOS CI runner such as GitHub Actions'
`macos-latest`, or a cloud Mac-build service) can compile or run this iOS
project. This is named explicitly because it changes what "ready to
attempt" can mean for iOS versus Android: Android is blocked by sandbox
policy and could be unblocked in-place; iOS needs a different kind of
machine entirely.

## Build configuration

Same `REACT_APP_BACKEND_URL` requirement as Android — no "same origin"
exists inside a Capacitor WKWebView either:

```bash
PUBLIC_URL=/ REACT_APP_BACKEND_URL=https://app.nuapos.com.au npx craco build
npx cap sync ios
```

`ios/App/App/public` (the synced web assets) is gitignored by Capacitor's
own generated `.gitignore`, same as Android's `assets/public` — regenerate
via the two commands above before any future iOS build, never hand-edit.

## iPad landscape POS

The directive calls this out by name as its own Phase 10 item. Capacitor's
default `Info.plist` (unmodified by this pass — it already shipped this
way) declares:

```xml
<key>UISupportedInterfaceOrientations~ipad</key>
<array>
  <string>UIInterfaceOrientationPortrait</string>
  <string>UIInterfaceOrientationPortraitUpsideDown</string>
  <string>UIInterfaceOrientationLandscapeLeft</string>
  <string>UIInterfaceOrientationLandscapeRight</string>
</array>
```

All four orientations, landscape included, are already permitted for
iPad out of the box — no change was needed for the primary "iPad as a POS
terminal in landscape" use case. This is a necessary-not-sufficient
finding: the app's own CSS/layout was never run on an actual iPad screen
(no device/simulator available — see the hard blocker above), so whether
the existing Tailwind responsive layout looks right in that orientation is
**not tested**, only *not blocked at the manifest level*.

## iPhone management experience

The directive's broader plan mentions a separate "NUA Business"
owner/manager app as a future, phone-oriented companion surface. No such
app exists yet in this repo — today's web app is the only frontend, and
nothing in this pass built a phone-specific layout or a second app target.
`UISupportedInterfaceOrientations` (the iPhone, non-`~ipad` key) in the
generated `Info.plist` defaults to portrait + both landscape orientations,
same as iPad's set minus upside-down — unmodified, inherited from
Capacitor's template. Running the existing POS UI on an iPhone-sized
screen was not attempted or reasoned about in depth this pass, since the
directive frames the phone experience as a distinct, later surface, not a
shrunk POS terminal; `MOBILE_DESKTOP_BACKLOG.md` should track "design an
actual phone-sized layout" as separate from this iPad POS work rather than
assuming the existing responsive CSS is sufficient.

## Secure storage / Keychain

Covered in full, with the corrected claim, in `SECURITY_MODEL.md` and
`frontend/src/platform/capacitor/SecureStorageService.js`. Summary: the
same `@capacitor/preferences` plugin used for Android is used for iOS.
Verified directly against the plugin's own native source
(`node_modules/@capacitor/preferences/ios/Sources/PreferencesPlugin/Preferences.swift`):
`private var defaults: UserDefaults { return UserDefaults.standard }` —
plain `UserDefaults`, not Keychain. This is **not** hardened storage on
iOS any more than it is on Android; a real Keychain-backed secure-storage
plugin (e.g. one using `kSecClassGenericPassword` with
`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`) is the still-correct
target and is tracked as genuinely not done in `MOBILE_DESKTOP_BACKLOG.md`
item 9, not as "iOS-specific hardening owed later" — the gap is identical
on both platforms.

## Camera and local-network permissions

iOS's WKWebView enforces `getUserMedia` and local-network access behind
OS-level permission prompts that only fire if the corresponding
"usage description" key exists in `Info.plist` — unlike a browser, which
can prompt without any app-level declaration. Reasoning through the
app's actual existing code (not a generic iOS checklist) found three real
call sites that would silently fail on iOS without these keys:
`components/pos/ScanVoucherButton.jsx` (camera, for QR-code vouchers/loyalty),
`VoiceCommandButton.jsx` / `VoiceOrderButton.jsx` / `pages/VoiceRecipe.jsx`
(microphone, for voice input), and — most consequential —
`services/printer.js`'s `printToNetwork()`, which does a plain
`fetch(\`http://${printerConfig.ipAddress}:${printerConfig.port}\`, ...)`
to a LAN thermal printer. That last one isn't a `getUserMedia` call, but
iOS's App Transport Security (ATS) blocks all plain-HTTP network requests
by default app-wide, which would silently break the **primary** printing
path (not a fallback) the moment the app ran on a real device. Added to
`frontend/ios/App/App/Info.plist`:

```xml
<key>NSCameraUsageDescription</key>
<string>NUA POS uses the camera to scan QR codes for vouchers and loyalty rewards.</string>
<key>NSMicrophoneUsageDescription</key>
<string>NUA POS uses the microphone for voice commands and voice-to-recipe features.</string>
<key>NSLocalNetworkUsageDescription</key>
<string>NUA POS connects to receipt and kitchen printers on your local network.</string>
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsLocalNetworking</key>
  <true/>
</dict>
```

`NSAllowsLocalNetworking` scopes the ATS exception to local/private-IP
hosts only (unlike Android's `usesCleartextTraffic`, which has no
equivalent local-only granularity and had to be applied app-wide — see
`ANDROID_ARCHITECTURE.md` and the comment in
`frontend/android/app/src/main/AndroidManifest.xml`). The real API traffic
to `https://app.nuapos.com.au` is already HTTPS and unaffected either way.
`npx cap sync` was re-run after these edits and the keys were confirmed
present in the synced `Info.plist` (`grep -c` found 3 matches) — but
**the actual OS permission prompts have never fired on a real device or
simulator**, since none is available in this sandbox. The keys existing
is necessary for the prompts to work at all; it is not proof they do.

## Bluetooth

No Bluetooth code exists anywhere in this app (confirmed in the Phase 0
browser-API audit) — same as Android. iOS additionally requires its own
`NSBluetoothAlwaysUsageDescription` key the moment any Bluetooth API is
touched (e.g. a future Bluetooth receipt printer), which is not yet
needed and not added. Status: **BLOCKED** (no plugin, no code), identical
to Android's rating in `HARDWARE_COMPATIBILITY_MATRIX.md`, not a
different or harder iOS-specific blocker.

## Payment SDK restrictions

No payment-terminal SDK is integrated on any platform today (Android,
iOS, or web) — `services/eftpos_service.py` exists but its own
terminal-SDK integration was never independently verified in this or the
prior session's work. Apple's iOS-specific restriction that would matter
*if and when* that changes: in-person card payment on iOS is either
through a certified third-party reader SDK (Tyro, Square, Zeller, etc.,
each with their own iOS SDK and MFi/Bluetooth certification) or Apple's
own Tap to Pay on iPhone — Apple does not allow a generic/unlisted
software-only card-reading implementation. This is a real constraint to
design around later, not a decision this pass needed to make, since no
payment SDK choice has been made for any platform yet.

## Background execution limitations

Not yet relevant in practice, but worth stating precisely for later:
iOS suspends a backgrounded app's JavaScript execution (including a
WKWebView's) far more aggressively than Android's background services
model — there is no equivalent to an Android foreground service keeping
JS running indefinitely while the app is backgrounded. The existing
offline-sync design (`lib/offlineQueue.js` flushing on mount, the
`online` event, and a 30-second poll — see `OFFLINE_SYNC_ARCHITECTURE.md`)
already assumes sync happens while the app is open/foregrounded, which
matches iOS's constraint reasonably well as designed — but no background
sync (e.g. a silent push-triggered sync while the app is closed) exists on
any platform, and iOS would need `BGTaskScheduler`/background push
entitlements specifically if that were ever added. Not a gap introduced
by this pass; named because the directive's Phase 10 list asks for it
explicitly.

## App Store requirements and privacy manifest

Not started, and genuinely cannot be finished without resources this
sandbox doesn't have:

- **Apple Developer Program enrollment** (paid, requires a real
  organization/individual account) — not something this pass can create
  or verify; needed before any signing, TestFlight, or App Store
  submission step.
- **Signing and provisioning** — needs a Developer Program membership,
  a distribution certificate, and a provisioning profile matching
  `com.nua.pos`. None exist. `project.pbxproj` currently has no team ID
  configured. This cannot be done from this sandbox regardless of
  network access, since it requires Apple's own account/portal and,
  practically, Xcode itself.
- **App Review requirements** specific to a business/POS app: a privacy
  policy URL, a support URL, and screenshots sized for the iPad and
  iPhone families actually being submitted for — none of these assets
  exist yet in this repo.
- **Privacy manifest (`PrivacyInfo.xcprivacy`)** — Apple requires this
  file, declaring "required reason" API usage, for apps using certain
  APIs as of its 2024+ App Store rules. `UserDefaults` (used indirectly
  via `@capacitor/preferences`, confirmed above) is on Apple's required-reason
  list. **This file does not exist in `frontend/ios/App/App/` and was not
  created this pass** — named here as a real, concrete gap rather than
  silently omitted, since it would block App Store submission (not local
  development or TestFlight-only use) if left unaddressed.

## Critical acceptance milestone — honest status

> iOS/iPad → take order → lose internet → continue operating → restart
> app → order survives → internet returns → synchronise → exactly one
> order appears in NUA → correct businessId → no duplicated
> payment/order/KDS event.

Identical reasoning to Android's section in `ANDROID_ARCHITECTURE.md`:

- The **code path** (`lib/offlineQueue.js`, `hooks/useOfflineQueue.js`,
  `clientOpId` dedup) is unchanged by this pass and platform-agnostic —
  IndexedDB is a standard WebKit/WKWebView API, not something Capacitor
  swaps out per platform.
- The **backend half** (tenant-scoped `clientOpId` dedup, atomic
  transaction handling) was already audited and fixed in this session's
  earlier launch-audit work and is unaffected by anything in this phase.
- **What this pass did NOT do**: run this flow on an iOS device or
  simulator — impossible from this sandbox regardless of effort, per the
  hard blocker above. The milestone is **not** claimed complete for iOS;
  it is claimed **ready to attempt the moment a macOS build environment
  is available** (a real Mac, a macOS CI runner, or a cloud Mac-build
  service) — a stronger caveat than Android's "ready to attempt," since
  Android's own blocker could in principle be lifted inside this same
  sandbox by a network-policy change, and iOS's cannot.

## Classification

**FOUNDATION**, with a lower ceiling than Android's FOUNDATION rating in
this same sandbox. The native project scaffolds correctly, the shared app
is unmodified in structure, the platform abstraction layer required no
iOS-specific changes at all (confirmed, not assumed), the device-identity
backend contract already accepted `"ios"` and is now explicitly tested
(see `backend/tests/inprocess/test_device_identity.py`), and the two
concrete platform gaps this pass found (camera/mic/local-network
permission declarations, ATS exception for LAN printer traffic) are
fixed. Not ALPHA: no build, no simulator run, no device run — and unlike
Android, none of those is reachable from this sandbox at all, only from a
macOS environment this pass had no access to.
