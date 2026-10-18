# App release strategy

Reviewed 19 October 2026. Use [current build commands](CURRENT_BUILD_GUIDE.md)
and [internal pilot builds](INTERNAL_PILOT_BUILDS.md) for supported procedures.
The old statement that only scaffolding exists is superseded by actual native
CI builds and acceptance runs. Builds, connected pilot packages and signed
store distribution are distinct milestones.

## Current evidence

The [connected pilot run](https://github.com/Sam-NUA/NUA/actions/runs/39139075241)
succeeded on deployed main `40cbe54a5413f0e6457f403c43d29593e5688b6f`.
All three manifests identify `https://app.nuapos.com.au` as the API origin and
`storeRelease: false`. The workflow builds/packages only: it does not launch
these artifacts or send financial acceptance requests to production.

| Platform | Current package | Distribution still required |
| --- | --- | --- |
| Android | Debug-key-signed internal APK | Publisher account, controlled release signing, Play listing/data-safety material and physical-device acceptance before Play testing/release. |
| Windows | Unsigned x64 NSIS installer from `apps/windows` | Signing identity, distribution/update policy and physical venue acceptance before merchant distribution. The retired `frontend/electron` scaffold is not the release host. |
| iOS/iPadOS | Unsigned Simulator app ZIP, built on macOS CI | Apple team/enrollment, certificate, provisioning, physical-device build/acceptance and App Store assets before TestFlight/App Store. The Simulator ZIP cannot install on an iPhone/iPad. |

Artifacts are retained for 30 days and include manifests with source SHA,
API origin, signing state, file size and SHA-256. Verify the manifest and hash
before installation; download links and instructions are in the pilot guide.

## Native acceptance

`.github/workflows/android.yml` builds a real APK, boots an AVD and exercises
cash checkout, outage, process restart and exactly-once replay against an
isolated backend. `ios.yml` uses `macos-latest`, Xcode and a booted Simulator;
its Appium critical acceptance covers PIN/device binding, refresh fault
injection and restart/replay. `windows-foundation.yml` launches the packaged
Electron app on Windows CI and tests restart/account-switch/exactly-once replay
against an isolated loopback backend. Native checks on the reviewed frontend
commit `f6d62d0eb64bf344b49c289b16f4997f7ba52587` passed before integration.

These are automated emulator/simulator/Windows CI results, not physical venue
hardware acceptance. The native workflows run on matching pull requests or
manual dispatch; they do not run on every push. Foundation artifacts use test
origins and must not be mistaken for connected pilot installers.

`frontend/ios/App/App/PrivacyInfo.xcprivacy` already exists. Its presence does
not itself establish App Store privacy compliance; review declared API usage,
privacy policy, support URL and real screenshots before submission.

## Versioning already implemented

`frontend/src/version.js` and `backend/version.py` supply the version.
Native API requests send `X-App-Version`. `VersionGateMiddleware` returns 426
for an unsupported supplied version; requests without that header remain
compatible, and version/health endpoints are exempt. The frontend handles 426
with `VersionGateLockScreen`; Settings terminal management shows app/platform/
device information. Do not describe the gate or readout as unimplemented.

An automatic native binary updater is not implemented. Version rejection does
not install an update, and raising the minimum must wait for a usable approved
distribution channel. Keep frontend/backend version changes coordinated.

## Release sequence

1. Keep source/CI evidence tied to the exact commit and package manifest.
2. Use a dedicated test venue for supervised pilot acceptance. Confirm owner
   email/PIN/MFA, real provider delivery/import and independent retained-backup
   restore without overwriting production.
3. Validate selected printer/scanner/drawer/terminal equipment and network
   topology. Partial EFTPOS adapters are not merchant-ready; see
   [payment terminal limits](PAYMENT_TERMINAL_ARCHITECTURE.md).
4. Complete publisher/signing custody and controlled distribution before store
   release. Never commit signing keys or embed provider/account credentials.

Current release evidence and unresolved operator gates are tracked in
[the launch report](https://github.com/Sam-NUA/NUA/pull/34). No signed store
release, physical-hardware acceptance or live provider payment is claimed here.
