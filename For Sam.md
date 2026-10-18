> Historical. Written for the CRA + Supervisor preview-env era, before the Vercel-only pivot (`docs/VERCEL_ONLY.md`) and the Vite/native-platform work in `docs/platform/`. Use `docs/platform/CURRENT_BUILD_GUIDE.md` and `docs/platform/INTERNAL_PILOT_BUILDS.md` for current build/deploy steps; `EMERGENT_LLM_KEY` below is retired — the AI adapter is now the public OpenAI SDK, keyed by `OPENAI_API_KEY` (see `services/ai_provider.py`).

# For Sam — Nua Restaurant OS Deployment Guide

This document is your single source of truth for getting **Nua – Restaurant OS** in front of real users on **Windows desktops, Android tablets/phones, and the open Web**. Every section ends with a smoke-test checklist so you can sign off cleanly.

> **Stack snapshot**
> • Frontend: React 18 + CRA + Tailwind + Shadcn UI · `/app/frontend`
> • Backend: FastAPI + Motor (async Mongo) · `/app/backend`
> • Database: MongoDB 7+
> • Hot reload via Supervisor (`supervisorctl`) in the preview env
> • Auth: JWT + bcrypt (managed in `routes/auth.py`); owner seed at startup

---

## 0 · One-time prerequisites (all platforms)

| Need              | Why                                | Where                                          |
| ----------------- | ---------------------------------- | ---------------------------------------------- |
| Node 18 LTS+      | Build the SPA bundle               | https://nodejs.org                              |
| Python 3.11+      | Run the FastAPI server             | https://python.org                              |
| Yarn 1.x          | Frontend dependency manager        | `npm i -g yarn`                                 |
| MongoDB 7         | Persistent store                   | Local install OR Atlas free tier                |
| Domain + HTTPS    | Required for Meta/TikTok OAuth     | Cloudflare / Namecheap / any registrar          |

### Environment variables (do **not** commit `.env`)

`backend/.env`:
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=nua_restaurant
JWT_SECRET=<generate-with `openssl rand -hex 32`>
EMERGENT_LLM_KEY=<your universal LLM key — required for AI calendar & inbox>
FRONTEND_URL=https://your-deployed-domain.com

# Optional integrations (leave blank until ready)
SENDGRID_API_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
META_APP_ID=
META_APP_SECRET=
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
X_API_KEY=
X_API_SECRET=
```

`frontend/.env`:
```
REACT_APP_BACKEND_URL=https://api.your-domain.com
```
> Never hardcode URLs — every `fetch` in the SPA uses `process.env.REACT_APP_BACKEND_URL` and every `/api/*` route is namespaced for Kubernetes ingress.

### Universal seed credentials

A bootstrap **owner** is auto-created on first backend startup:

```
email:    owner@nua.com
password: NuaOwner2026!
```

Change it immediately via **Settings → Staff → Roles** in production.

---

## 1 · Web deployment (production-grade)

This is the canonical deployment — Windows desktops and Android devices all reach the same hosted URL.

### 1.1 — Build the SPA
```bash
cd /app/frontend
yarn install
yarn build          # outputs to /app/frontend/build
```

### 1.2 — Containerise (Dockerfile)

We recommend two containers behind a single Nginx ingress.

`infra/Dockerfile.backend`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
```

`infra/Dockerfile.frontend`:
```dockerfile
FROM nginx:alpine
COPY frontend/build /usr/share/nginx/html
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

`infra/nginx.conf` (proxy `/api` → backend, serve SPA for everything else):
```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    location /api/ { proxy_pass http://backend:8001; proxy_set_header Host $host; }
    location /     { try_files $uri /index.html; }
}
```

`docker-compose.yml`:
```yaml
version: "3.9"
services:
  mongo:
    image: mongo:7
    volumes: [mongo-data:/data/db]
  backend:
    build: { context: ., dockerfile: infra/Dockerfile.backend }
    env_file: backend/.env
    depends_on: [mongo]
  frontend:
    build: { context: ., dockerfile: infra/Dockerfile.frontend }
    ports: ["80:80"]
    depends_on: [backend]
volumes: { mongo-data: {} }
```

### 1.3 — Hosting choices (pick one)

| Host                    | Effort  | Notes                                                              |
| ----------------------- | ------- | ------------------------------------------------------------------ |
| **Fly.io / Render**     | ★      | Push the compose file, get HTTPS for free                          |
| **AWS ECS Fargate**     | ★★     | Scales to thousands of seats; pairs with DocumentDB or Atlas       |
| **Self-hosted VPS**     | ★★★    | DigitalOcean / Hetzner: Docker + Caddy for auto-HTTPS              |
| **Vercel + Railway**    | ★      | SPA on Vercel, FastAPI + Mongo on Railway                          |

### 1.4 — Smoke test (Web)
1. Browse to `https://your-deployed-domain.com` — landing should render.
2. Log in with `owner@nua.com` / `NuaOwner2026!`.
3. Open **POS** → punch in a $1 test item → finish order. Expect ✅ on the kitchen ticket.
4. Open **Social Media → Calendar** → confirm the "best time to post" chips render.
5. Hit `/api/health` (or `/api/social/platforms`) — expect HTTP 200 JSON.

---

## 2 · Windows desktop (kiosk / counter machine)

You have **two** good options. Pick based on whether the venue has reliable internet.

### Option A — PWA shortcut (always-online, lowest friction)
1. Open Edge → navigate to the deployed URL → log in.
2. `…` menu → **Apps → Install this site as an app**.
3. The OS gets a shortcut + standalone window (no chrome).
4. Pin to taskbar; double-click acts identically to the iPad app.

### Option B — Electron wrapper (offline-tolerant kiosk)

Build a thin Electron shell that loads the deployed URL and falls back to a cached offline page when the network drops.

```bash
mkdir nua-desktop && cd nua-desktop
npm init -y
npm i electron electron-builder --save-dev
```

`main.js`:
```js
const { app, BrowserWindow } = require('electron');
function createWindow () {
  const win = new BrowserWindow({
    width: 1440, height: 900,
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true },
  });
  win.loadURL(process.env.NUA_URL || 'https://your-deployed-domain.com');
  win.setMenuBarVisibility(false);
  win.setFullScreen(true);   // counter kiosk mode
}
app.whenReady().then(createWindow);
```

`package.json` (add):
```json
"main": "main.js",
"build": {
  "appId": "com.nua.restaurant",
  "productName": "Nua Restaurant OS",
  "win": { "target": "nsis", "icon": "build/icon.ico" }
},
"scripts": { "start": "electron .", "dist:win": "electron-builder --win" }
```

`yarn dist:win` produces a signed `.exe` installer in `dist/`. Sign with an EV code-signing cert before distributing.

### Smoke test (Windows)
1. Run the installer on a clean Windows 11 machine.
2. Launch from the Start menu — the app should open full-screen.
3. Plug in a receipt printer (Epson TM-m30) and a USB barcode scanner; both should resolve through the SPA without driver clicks (browser-side `WebUSB` / device input).
4. Force-disconnect WiFi — the kiosk should show the cached offline screen, then auto-reload on reconnect.

---

## 3 · Android (Phone & Tablet)

Three rollout paths — pick by audience.

### Option A — PWA install (recommended for owners + staff)
1. Visit the deployed URL in **Chrome on Android** → log in.
2. Tap the address bar **⋮ → Add to Home screen**.
3. The app installs as a standalone icon; **launches without browser chrome** because we ship the right Web App Manifest (see `/app/frontend/public/manifest.json`).
4. iOS Safari users can use the same flow via **Share → Add to Home Screen** (yes it works on iPad too).

**Why this is the default**: zero store-review wait, instant updates, no APK signing. Tested on tablets >= 10".

### Option B — TWA (Trusted Web Activity) APK for the Play Store

Wrap the PWA in a TWA so it shows up on Google Play.

```bash
npx -p @bubblewrap/cli bubblewrap init --manifest=https://your-deployed-domain.com/manifest.json
npx -p @bubblewrap/cli bubblewrap build       # produces app-release-signed.aab
```
Upload the `.aab` to the Play Console. Verify **Digital Asset Links** via the `/.well-known/assetlinks.json` file (Bubblewrap prints the JSON to add to your hosting).

### Option C — React Native shell (only when you need native bluetooth/printer SDKs)
Skip unless you have an actual native dependency that the SPA can't solve.

### Smoke test (Android)
1. Install via PWA on a 10" tablet (e.g. Lenovo Tab M10 / Galaxy Tab S9).
2. Confirm the calendar drag-drop works with finger drag (touch events are wired in `SocialCalendar.jsx`).
3. Open **POS** → split a $20 bill across two payment methods → expect both to settle.
4. Force the device into airplane mode mid-order → the SPA should buffer and re-sync once the network returns (service worker handles this).
5. Rotate device → header & tables reflow without overlap.

---

## 4 · Day-2 operations

### 4.1 Auth + secrets
- Rotate `JWT_SECRET` every 90 days. Existing sessions invalidate automatically; staff re-login.
- `EMERGENT_LLM_KEY` — top up via Profile → Universal Key → Add Balance.
- For Meta/TikTok/X publishing, request **Business Verification** with each platform and fill the `*_APP_ID / SECRET` env vars. Until then the social-publish endpoint stays in mocked-OAuth mode (banner visible in `/social-media`).

### 4.2 Backups
- Run `mongodump --uri="$MONGO_URL" --out=/backups/$(date +%F)` on a nightly cron.
- Retain 30 days locally + ship monthly snapshot to S3 / GCS.

### 4.3 Logs & monitoring
- Backend logs: `journalctl -u nua-backend -f` (systemd) or `docker logs backend -f` (compose).
- Frontend errors: hook Sentry via `REACT_APP_SENTRY_DSN` — already wired through `axios` interceptor in `services/api.js`.
- Mongo metrics: enable free-tier Atlas alerting (slow queries > 100 ms, connections > 80% pool).

### 4.4 Updating production
```bash
git pull && docker compose build && docker compose up -d
```
Zero-downtime upgrade: scale the backend to 2 replicas behind the ingress before swapping.

---

## 5 · Troubleshooting cheat-sheet

| Symptom                                       | Likely cause                              | Fix                                                                       |
| --------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------- |
| SPA loads but every API call 401s             | `JWT_SECRET` mismatch between containers  | Bake the same `.env` into both backend replicas                           |
| Calendar best-time chips show "Default" only  | No POS transactions in last 7 days        | Run 5 test orders → chips will switch to "POS" within a minute            |
| AI Weekly Plan stuck on "queued"              | `EMERGENT_LLM_KEY` empty / out of credit  | Top up in Profile → Universal Key                                         |
| Social publish silently fails                 | Mock OAuth mode (expected, no creds)      | Add Meta/TikTok/X credentials, then bounce the backend container         |
| Android PWA opens browser tab instead of app  | Service worker not registered (HTTP host) | Production must be **HTTPS**; PWAs refuse to install on plain HTTP        |
| Windows EXE shows blank window                | Antivirus quarantined the build           | Sign the executable with an EV cert and add to the AV allowlist           |
| `x-ai-parsed-fallback: true` on inbox ingest  | LLM unavailable, returning templates      | Check `EMERGENT_LLM_KEY` and Anthropic/Gemini provider status            |

---

## 6 · Five-year posture (what to enable as you grow)

1. **Multi-tenant**: schema is already namespaced via `tenantId`. Flip the `/api/multi-tenant` routes on to host multiple venues from one deployment.
2. **Offline-first**: enable the workbox service worker (already in CRA's PWA template) to cache product catalog + recent orders.
3. **Edge cache**: park the SPA on a CDN (Cloudflare Pages / Vercel Edge) — the FastAPI box only handles `/api/*` calls.
4. **Reservations OAuth**: switch the booking inbox from manual-ingest to webhook subscriptions (Instagram Graph API, Twilio inbound SMS, Mailgun routes).
5. **Hardware health**: the `Hardware Health` route is wired into `routes/automation.py`. Connect Zebra / Epson printers' SNMP and surface temp/jam alerts via the dock.

---

You're set. Ping the engineering channel if anything in the smoke tests doesn't tick — we'll triage in under 30 minutes.

— Nua engineering
