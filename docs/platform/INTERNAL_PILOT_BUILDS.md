# Internal pilot native packages

The foundation CI packages deliberately use reserved `.invalid` API origins.
They prove isolated builds/acceptance; they are not connected venue installers.

`Internal native pilot packages` builds separate Android, Windows and iOS
Simulator artifacts with the explicit API origin **https://app.nuapos.com.au**.
CI only builds/packages them. It never launches them or sends acceptance sales
to the live service. Existing native financial tests keep their isolated servers.

The target API must explicitly configure `NATIVE_APP_CORS_ORIGINS` as
`https://localhost,capacitor://localhost,nua://app`. These are the three renderer
origins configured in the native projects. Keep `FRONTEND_URL` as the canonical
HTTPS web origin for recovery links. Unrecognized origins/wildcards are rejected;
this setting does not bypass login, device binding or tenant authorization.

## Obtain the packages

Open GitHub Actions → **Internal native pilot packages** → the successful reviewed
run. Download the platform artifact. Every artifact includes a README and
`build-manifest.json` with the actual checked-out source commit, API origin,
signing/channel, file size and SHA-256. Verify the hash before installing.
The build fails if the native renderer does not contain the approved API origin
or the expected output was not produced. Artifacts are retained for 30 days.

After this workflow is merged, an authorized repository maintainer can choose
**Run workflow** on a reviewed commit. It also runs on PRs that change the
workflow or its manifest helper, allowing its actual three-platform build to be
reviewed before merge. No deployment, release upload, signing secret, account
credential, payment call or production test transaction is part of the workflow.

| Package | Use and limits |
| --- | --- |
| Android APK | Debug-key-signed internal sideload; not a Google Play release. |
| Windows EXE | Unsigned x64 NSIS installer; not a signed merchant distribution. |
| iOS Simulator ZIP | App.app for a Mac/Xcode Simulator; cannot install on a physical iPhone/iPad and is not TestFlight. |

## Supervised pilot

These packages connect to the real NUA service. Use the intended business account.
Provision a dedicated test venue before controlled pilot sales or bookings;
do not run automated financial acceptance against production.
Test real printers/drawers/scanners/EFTPOS with the selected venue equipment.
A connected build does not prove hardware behavior.

Physical iOS distribution still requires the Apple team, certificate and profile.
Google Play distribution needs the publisher account/signing custody. Signed
Windows distribution needs the signing identity and delivery channel.
Never commit signing keys or use credentials embedded in the frontend.
See [current build commands](CURRENT_BUILD_GUIDE.md) and the release report in PR #33.
