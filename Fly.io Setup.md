> Historical alternative. The requested hosting target is Vercel only — see `docs/VERCEL_ONLY.md`. Fly.io is not required and this guide's `EMERGENT_LLM_KEY` references predate the OpenAI SDK migration (now `OPENAI_API_KEY`, see `docs/platform/CURRENT_ARCHITECTURE_AUDIT.md`).

# Nua on Fly.io — The 5-Year-Old Deployment Guide

Fly.io is like renting two tiny robots:
1. 🧠 **Backend robot** — runs Python + FastAPI (the brain)
2. 🎨 **Frontend robot** — serves the React website (the pretty face)
3. 📦 **Toy box** — we'll use **MongoDB Atlas** for free instead of running our own Mongo robot (much easier, won't break)

Total cost: **$0–10/month** to start. Free tier handles small restaurants.

---

## 🧰 Step 0 — Get the tools (one time only)

### Make accounts (all free)
| Where | What for |
|---|---|
| https://fly.io/app/sign-up | Where we host the app |
| https://cloud.mongodb.com | Where we store data (free 512 MB cluster) |
| https://github.com | To save your code (use Emergent's "Save to GitHub" button) |

### Install the Fly tool on your computer
**Mac:**
```bash
brew install flyctl
```

**Windows (PowerShell):**
```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

**Linux:**
```bash
curl -L https://fly.io/install.sh | sh
```

Then log in:
```bash
flyctl auth login
```
Browser opens → click "OK" → done.

---

## 📦 Step 1 — Make the MongoDB toy box (5 minutes, free)

1. Go to https://cloud.mongodb.com and click **Build a Database**.
2. Pick the **FREE M0 cluster** (512 MB, more than enough to start).
3. Choose the region closest to your customers (e.g. **Sydney** for Australia).
4. Create a database user:
   - Username: `nua-admin`
   - Password: click "Autogenerate" and **COPY IT SOMEWHERE SAFE**
5. **Network Access** → "Allow access from anywhere" → confirm with `0.0.0.0/0`
   *(Don't worry, the password protects you.)*
6. Click **Connect → Drivers** → copy the connection string. Looks like:
   ```
   mongodb+srv://nua-admin:YOUR-PASSWORD@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority
   ```

Keep that string handy. We'll need it in Step 3.

---

## 🧠 Step 2 — Deploy the Backend brain

### 2a. Make a Dockerfile (one file, paste exactly)

Create `/app/backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
COPY . .
EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
```

### 2b. Make a fly.toml for the backend

Create `/app/backend/fly.toml`:

```toml
app = "nua-backend"           # change to your unique name
primary_region = "syd"         # syd=Sydney, lax=LA, lhr=London, fra=Frankfurt

[build]
  dockerfile = "Dockerfile"

[http_service]
  internal_port = 8001
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 1

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
```

### 2c. Launch it
```bash
cd /app/backend
flyctl launch --no-deploy   # answer No to "Would you like to deploy now"
```
*(If it asks to overwrite fly.toml, say NO.)*

### 2d. Save your secrets (the real magic step)
Run **each line** in your terminal — replace the placeholders with real values:

```bash
flyctl secrets set MONGO_URL="mongodb+srv://nua-admin:YOUR-PASSWORD@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority"
flyctl secrets set DB_NAME="nua_restaurant"
flyctl secrets set JWT_SECRET="$(openssl rand -hex 32)"
flyctl secrets set EMERGENT_LLM_KEY="your-emergent-key-here"
flyctl secrets set FRONTEND_URL="https://nua-frontend.fly.dev"
```

### 2e. Deploy!
```bash
flyctl deploy
```
Wait ~3 minutes ☕. When done it prints something like:
```
Visit https://nua-backend.fly.dev/
```
Test it:
```bash
curl https://nua-backend.fly.dev/api/social/platforms
```
You'll get `{"detail":"Not authenticated"}` — that's **PERFECT** (it means the API is alive and asking for a login).

---

## 🎨 Step 3 — Deploy the Frontend face

### 3a. Make a Dockerfile for the frontend

Create `/app/frontend/Dockerfile`:

```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile
COPY . .
ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
RUN yarn build

# Serve stage
FROM nginx:alpine
COPY --from=builder /app/build /usr/share/nginx/html
RUN echo 'server { \
  listen 8080; \
  root /usr/share/nginx/html; \
  location / { try_files $uri /index.html; } \
}' > /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
```

### 3b. Make a fly.toml for the frontend

Create `/app/frontend/fly.toml`:

```toml
app = "nua-frontend"          # change to your unique name
primary_region = "syd"

[build]
  dockerfile = "Dockerfile"
  [build.args]
    REACT_APP_BACKEND_URL = "https://nua-backend.fly.dev"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 1

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 256
```

> 🔑 **The most important line** is `REACT_APP_BACKEND_URL` — it must point at the URL Fly gave you in Step 2e.

### 3c. Launch & deploy
```bash
cd /app/frontend
flyctl launch --no-deploy
flyctl deploy
```

Wait ~5 minutes. When done:
```
Visit https://nua-frontend.fly.dev/
```

🎉 **OPEN THAT URL!** Log in with `owner@nua.com` / `NuaOwner2026!` — Nua is live on the internet.

---

## 🌐 Step 4 — Point your own domain at it (optional but pro)

If you bought `nua-eatery.com` (from GoDaddy, Namecheap, anywhere):

```bash
flyctl certs create nua-eatery.com --app nua-frontend
flyctl certs create www.nua-eatery.com --app nua-frontend
```

Fly prints two values. Go to your domain's DNS settings and add:
- **A record**: `@` → the IPv4 Fly shows you
- **AAAA record**: `@` → the IPv6 Fly shows you
- **CNAME**: `www` → `nua-frontend.fly.dev`

Wait 5–60 minutes for DNS to update. Fly auto-issues a free HTTPS certificate 🔒.

Then **update the backend's `FRONTEND_URL` secret** to your real domain:
```bash
cd /app/backend
flyctl secrets set FRONTEND_URL="https://nua-eatery.com"
```

And **rebuild the frontend** with the new backend URL if you also gave the backend a custom domain.

---

## 🧪 Step 5 — Smoke test

| Check | Command / where |
|---|---|
| Backend alive? | `curl https://nua-backend.fly.dev/api/social/platforms` → returns JSON |
| Frontend alive? | Browser → `https://nua-frontend.fly.dev` → landing page renders |
| Login works? | `owner@nua.com` / `NuaOwner2026!` → dashboard appears |
| Mongo wired? | Add a product → refresh → it's still there |
| AI calendar? | `/social-media` → Calendar tab → chips render with times |

If ANY check fails, see the troubleshooting table at the bottom.

---

## 💸 What it actually costs

| Component | Free tier? | Real cost if you grow |
|---|---|---|
| Fly.io (2 small machines) | Yes, first 3 shared-cpu-1x | ~$5–8/month |
| MongoDB Atlas M0 | Yes, 512 MB | $9/mo for M2 (2 GB) |
| Domain | No | ~$12/year |
| **Total to start** | **$0** | **~$15/month for a busy restaurant** |

---

## 🔁 Day-2: How to update the app later

Every time you change code in Emergent:
1. Hit "Save to GitHub" in the Emergent chat.
2. On your computer: `git pull`
3. Backend changes:  `cd backend && flyctl deploy`
4. Frontend changes: `cd frontend && flyctl deploy`

That's it. Each deploy takes 2–5 minutes, zero downtime.

---

## 🩹 Troubleshooting

| Symptom | Fix |
|---|---|
| `flyctl: command not found` | Re-run the install one-liner from Step 0, then restart your terminal |
| Backend deploys but `/api/...` returns 500 | `flyctl logs --app nua-backend` — usually a missing secret. Re-run `flyctl secrets set`. |
| Frontend loads but every button = network error | `REACT_APP_BACKEND_URL` was wrong at build time. Edit `fly.toml`, redeploy. |
| Mongo connection refused | In Atlas, Network Access must allow `0.0.0.0/0`. Re-check. |
| "App name already taken" | Pick a unique name like `nua-yourrestaurant-backend` |
| Custom domain stuck "pending" | DNS hasn't propagated yet — wait 30 min, then `flyctl certs check yourdomain.com` |
| Backend keeps sleeping (slow first response) | Set `min_machines_running = 1` in fly.toml (already set above) and redeploy |

---

## 🎁 Pro tips for the future

1. **Auto-deploy on git push**: Add `flyctl deploy --remote-only` to a GitHub Action — every commit redeploys automatically.
2. **Scale to multiple regions**: `flyctl regions add lax fra` — Fly mirrors your app to LA + Frankfurt for global speed.
3. **Persistent volume** (if you ditch Atlas later): `flyctl volumes create nua_data --size 10 --region syd` and add `[mounts]` to fly.toml.
4. **Logs**: `flyctl logs --app nua-backend` (live tail) — your best friend when debugging.
5. **Console**: `flyctl ssh console --app nua-backend` — opens a terminal inside the running container.

---

## ✅ The "I just did it" checklist

- [ ] Fly + Mongo Atlas accounts created
- [ ] `flyctl` installed and logged in
- [ ] Mongo connection string copied
- [ ] Backend `Dockerfile` + `fly.toml` created
- [ ] Backend secrets set (`MONGO_URL`, `JWT_SECRET`, `EMERGENT_LLM_KEY`)
- [ ] Backend deployed → `https://nua-backend.fly.dev/api/social/platforms` returns JSON
- [ ] Frontend `Dockerfile` + `fly.toml` created
- [ ] Frontend deployed → loads in browser
- [ ] Logged in successfully as `owner@nua.com`
- [ ] (Optional) Custom domain + HTTPS certificate
- [ ] (Optional) Updated `FRONTEND_URL` secret + redeployed

You're done. 🎉
