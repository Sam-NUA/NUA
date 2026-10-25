# NUA POS device icons and native installer branding
All app platforms must display **NUA POS**, not the retired Windows "Foundation" name.

Run `python3 scripts/generate_app_icons.py` (from the repository root) before
Android/iOS/Windows native builds. This uses the Python standard library only,
with NUA Burgundy / Warm Ivory / Intelligence Violet. It overwrites launcher
assets in `frontend/android/app/src/main/res/mipmap-*`, the required **1024x1024**
iOS AppIcon asset, `apps/windows/build/icon.ico` and `icon.png`, and PWA
icon variants in `frontend/public`.

Official workflow builds invoke the generator on each CI runner. Native icons
are rebuilt from source rather than copying a 512-pixel web favicon into a
different size or shipping the stock Capacitor/Electron logo.

The SVG preview under `frontend/public/nua-icon.svg` is a scalable reference.
The raster generator deliberately uses a portable no-font wordmark because
system-installed fonts differ across release environments. Review rendered icon
appearance on the target OS and store; icon generation alone is **not** store
artwork approval.

Windows Electron uses `apps/windows/build/icon.ico` for its running window
and NSIS installer, while preserving the existing Electron `appId` to avoid
orphaning the test installation. Clear the OS icon cache if a previously
installed app continues to display its old icon.

No Apple distribution signing, Microsoft publisher certificate or Android
production keystore is created by this procedure.
