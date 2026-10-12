# iOS / iPadOS architecture

No iOS-specific work was done or attempted this pass, per the master
directive's own Phase 10 guidance: "No Apple-specific implementation is
required until the architecture has been validated unless useful for
early compile testing." Android validation isn't complete yet (no
on-device run — see `ANDROID_ARCHITECTURE.md`), so this wasn't attempted.

What's already true without any iOS-specific work, by construction:

- Every native integration added this pass sits behind the
  `platform/index.js` abstraction — `detectPlatform()` already returns
  `'ios'` correctly whenever Capacitor's own `getPlatform()` does (no
  separate iOS detection logic needed).
- All 8 Capacitor plugins installed this pass (`app`, `clipboard`,
  `device`, `dialog`, `filesystem`, `network`, `preferences`, `share`)
  are cross-platform Capacitor core/first-party plugins — every one
  already supports iOS, not just Android. No `@capacitor/ios` dependency
  or native Xcode project exists yet; adding one is `npx cap add ios`,
  the same mechanical step as the Android one this pass did, once
  justified.

What would need separate attention when iOS work actually starts (not
done, just named, per the directive's own list): Keychain-backed secure
storage instead of (or alongside) `@capacitor/preferences`, WKWebView's
stricter Bluetooth/local-network permission prompts, Apple's background
execution limits (relevant to any future push-notification or
background-sync work), App Store privacy manifest requirements, and
signing/provisioning — none of which block the Android-first work this
pass actually did.

No Xcode/macOS runner exists in this sandbox either way, so even an iOS
compile-check wasn't possible this pass regardless of priority.
