# Nua — Local Development with Docker Compose

Run the entire stack (React + FastAPI + MongoDB) on your laptop with **one command**. Perfect for testing before pushing to production.

> 🎯 You don't need this if you only ever edit code in Emergent. But if you want to develop offline, debug network issues, or test integrations locally — this is the way.

---

## 🧰 Prerequisites

| Need | Where |
|---|---|
| **Docker Desktop** | https://docker.com/products/docker-desktop |
| **Git** | https://git-scm.com |

That's it. No Node, no Python, no Mongo install — Docker handles everything.

---

## 🚀 The 3-step "run it locally" flow

### 1. Clone the repo
```bash
git clone https://github.com/YOUR-NAME/nua.git
cd nua
```

### 2. Create your `.env`
There's no `.env.example` to copy — create `.env` in the repo root directly,
with whichever of `docker-compose.yml`'s backend `environment:` vars you
need (the only one most people want locally is the AI key):
```bash
echo 'OPENAI_API_KEY=sk-...' > .env
```
`OPENAI_API_KEY` is the public OpenAI SDK, see `services/ai_provider.py`;
`EMERGENT_LLM_KEY` is retired and no longer read. Without it, AI-backed
features return a clear "not configured" error rather than a result.

### 3. Launch!
```bash
docker compose up --build
```

First run takes ~5 minutes (downloads images + builds). Subsequent runs take ~15 seconds.

When you see this in the logs, you're live:
```
nua-backend   | INFO:     Uvicorn running on http://0.0.0.0:8001
nua-frontend  | nginx: ready
```

---

## 🌐 Open it

| Service  | URL |
|---|---|
| Frontend (the app) | http://localhost:3000 |
| Backend API | http://localhost:8001/api/social/platforms |
| MongoDB (direct) | `mongodb://localhost:27017` (use Compass to browse) |

Log in as: `owner@nua.com` / `NuaOwner2026!`

---

## 🛠️ Useful commands

| Goal | Command |
|---|---|
| Run in background | `docker compose up -d --build` |
| Stop everything | `docker compose down` |
| Stop AND wipe Mongo data | `docker compose down -v` |
| See logs (live) | `docker compose logs -f backend` |
| Rebuild one service | `docker compose up --build backend` |
| Open a shell in backend | `docker compose exec backend bash` |
| Open a shell in Mongo | `docker compose exec mongo mongosh` |
| Enable Mongo Express UI | `docker compose --profile tools up` → http://localhost:8081 |

---

## 🔁 Hot reload while developing

The provided Dockerfiles **bake the code in** for a production-like setup. For live reload during dev work, use Docker only for Mongo and run the app code natively:

```bash
# Terminal 1 — just Mongo from docker
docker compose up mongo

# Terminal 2 — backend with hot reload
cd backend
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Terminal 3 — frontend with hot reload
cd frontend
yarn install && yarn start
```

This is the same setup the Emergent preview uses internally.

---

## 🩹 Troubleshooting

| Symptom | Fix |
|---|---|
| `Error: Bind for 0.0.0.0:27017 failed: port is already allocated` | Another Mongo is running. Stop it or change the port in `docker-compose.yml`. |
| Frontend loads but APIs return CORS errors | The frontend baked the wrong `REACT_APP_BACKEND_URL` at build time. Rebuild: `docker compose build --no-cache frontend`. |
| `ECONNREFUSED mongo:27017` from backend | Mongo container is still starting up. Compose waits on a healthcheck — give it 30 seconds. |
| `docker: not found` | Install Docker Desktop and make sure the daemon is running. |
| Apple Silicon (M1/M2/M3) slow performance | Docker Desktop → Settings → enable **Rosetta** for x86 emulation. |
| Need to reset everything | `docker compose down -v --remove-orphans && docker compose up --build` |

---

## ✅ Smoke test checklist

After `docker compose up --build` completes:

- [ ] http://localhost:3000 loads the landing page
- [ ] Login with `owner@nua.com` / `NuaOwner2026!` succeeds
- [ ] http://localhost:8001/api/social/platforms returns `{"detail":"Not authenticated"}` (proves Python is alive)
- [ ] Create a product in /products → refresh → it persists (proves Mongo is wired)
- [ ] Visit /social-media → Calendar tab → "Best time to post" chips render

---

## 🎁 Pro tips

1. **Production parity**: The Dockerfiles in this repo are the EXACT ones used by Fly.io and Railway. If it works locally, it works in production.
2. **Volume reset**: Mongo data persists in a docker volume named `nua_mongo-data`. Wipe it with `docker volume rm nua_mongo-data` if you want a clean slate.
3. **Resource caps**: Add `mem_limit: 512m` to a service in `docker-compose.yml` to simulate Fly.io's small-tier RAM limits.
4. **VS Code remote**: Install the "Dev Containers" extension → "Reopen in container" gives you a full IDE inside the running backend container.

You're set. 🎉
