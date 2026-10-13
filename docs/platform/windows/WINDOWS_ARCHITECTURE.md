# Windows touchscreen and desktop

One Electron 44 host loads the existing React build from the secure `nua://app` origin. SPA fallback supports direct /login and /pos paths without file URL behavior. No application backend, MongoDB, environment file, signing key or payment secret is included. The standalone manifest and lockfile in `apps/windows` are authoritative for this foundation. The old frontend Electron commands are legacy and must not be used to release it.

Native bridge version 1 exposes only getInfo, setFullscreen, listPrinters and printReceipt. Every command validates the sender window, main frame and origin. Context isolation, sandbox, web security and Node-off renderer are explicit. External navigation/popups/webviews/downloads and permissions are denied. API requests use only the configured HTTPS origin; remote product images outside that origin are currently blocked. External Stripe redirect and camera/voice paths are therefore NOT supported by this phase.

Default desktop uses keyboard/mouse. `npm start -- --touch` enables minimum 44px interactive targets and touch behavior. The host toolbar exposes reversible full screen and a printer test. This is NOT tamper-proof kiosk/Windows Assigned Access, and cashier keyboard shortcuts/virtual keyboard/125–200% scaling still require Windows QA.

Build on Windows, from repo root:

```powershell
$env:REACT_APP_BACKEND_URL = 'https://YOUR-NONPRODUCTION-API-ORIGIN'
$env:NUA_WINDOWS_API_ORIGIN = $env:REACT_APP_BACKEND_URL
$env:PUBLIC_URL = '/'
$env:CI = 'false'
cd frontend
npm ci
npm run build
cd ../apps/windows
npm ci
npm test
npm run prepare:renderer
npm start -- --touch
npm run dist
```

The API must explicitly allow `nua://app` CORS. No live environment change is made here. CI uses reserved `https://windows-api.invalid`; its installer intentionally cannot log into a venue. Rebuild against an approved test API for integrated QA. The renderer build is checked for the same API origin; no runtime arbitrary URL is accepted.

Session storage is in memory: tokens do not persist in Chromium across restart, and reauthentication is required. The encrypted-store + Windows crypto primitives are implemented and tested separately; they are NOT wired to shared AuthContext/queue yet. Do not interpret the separate queue restart test as restart-safe POS operation.
