# Current shared/native build commands

Updated 17 October 2026 for the Vite migration. Use this guide instead of old
root-level Electron/CRA packaging instructions. These commands build artifacts;
they do not deploy or authorize production API calls. Use an explicitly authorized
staging API origin for interactive acceptance tests.

## Shared frontend

Node 22.12+ is required; use the committed npm lockfile.

```bash
cd frontend
npm ci
npm run lint
npm test -- --runInBand --watchAll=false
PUBLIC_URL=/ REACT_APP_BACKEND_URL=https://your-staging-origin.example npm run build
```

Output: `frontend/build`. The example origin is a placeholder, not a usable service.
Vercel's existing same-origin service configuration uses `PUBLIC_URL=/` and an
empty `REACT_APP_BACKEND_URL`; API rewrites route `/api` and `/bookings-api`.
The Vite config exposes only explicitly allowlisted public settings. Never put
server/provider secrets in `REACT_APP_*` variables.

## Android

After the shared build above, from `frontend/`:

```bash
npx cap sync android
cd android
./gradlew assembleDebug
```

Use JDK 21 and the Android SDK versions in the committed Gradle project. On Windows
use `gradlew.bat`. Output: `frontend/android/app/build/outputs/apk/debug/app-debug.apk`.
The debug APK is not a signed store release. `frontend/build-android.sh` also
requires an explicit `REACT_APP_BACKEND_URL` rather than baking a fake default.
See `android.yml` for isolated emulator acceptance; don't aim its financial tests
at a real venue.

## iOS/iPadOS

On macOS with Xcode, after the shared build, from `frontend/`:

```bash
npx cap sync ios
npx cap open ios
```

Build/run the App scheme on an available simulator. The repository uses Swift
Package Manager; see `.github/workflows/ios.yml` for dependency resolution and
unsigned simulator build commands. Physical distribution needs the correct Apple
team, certificate and provisioning profile. Do not remove Keychain entitlements
or the custom session plugin to resolve a signing problem.

## Windows

Use the supported host in `apps/windows`. The former `frontend/electron` scaffold
and its `build-windows.bat`/`electron-package.json` are retired.

PowerShell on a Windows machine with Node 22.12+ (CI uses Node 24):

```powershell
$env:PUBLIC_URL = '/'
$env:REACT_APP_BACKEND_URL = 'https://your-staging-origin.example'
$env:NUA_WINDOWS_API_ORIGIN = $env:REACT_APP_BACKEND_URL
cd frontend
npm ci
npm run build
cd ../apps/windows
npm ci
npm test
npm run prepare:renderer
node scripts/smoke.cjs
npm run dist
```

The API origin must match the compiled frontend and satisfy the host's HTTPS
policy. No implicit production endpoint is supplied. The unsigned NSIS installer
is produced under `apps/windows/dist`. Distribution signing remains a separate
release gate. `windows-foundation.yml` runs a real Windows restart/account-switch/
exactly-once replay acceptance test against an isolated loopback backend; it is
stronger evidence than building an installer alone.

See [software closure](LAUNCH_SOFTWARE_CLOSURE_2026-10-17.md) for exact tested
commits, counts, remaining provider/hardware/signing gates and review dependencies.
