#!/usr/bin/env bash
# HISTORICAL: Fly.io is a retired hosting alternative — the requested
# target is Vercel only (see docs/VERCEL_ONLY.md). This script also still
# prompts for EMERGENT_LLM_KEY, which the backend no longer reads (the AI
# adapter is now the public OpenAI SDK, keyed by OPENAI_API_KEY).
#
# Nua → Fly.io one-click deploy.
# Usage:
#   ./deploy.sh           # deploys both backend + frontend
#   ./deploy.sh backend   # deploys backend only
#   ./deploy.sh frontend  # deploys frontend only
#   ./deploy.sh init      # first-time setup: creates the apps and prompts for secrets
#
# Prereqs: flyctl installed + `flyctl auth login` already done.

set -euo pipefail

BACKEND_APP="${BACKEND_APP:-nua-backend}"
FRONTEND_APP="${FRONTEND_APP:-nua-frontend}"
REGION="${FLY_REGION:-syd}"

color()  { printf '\033[1;36m%s\033[0m\n' "$1"; }
ok()     { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
warn()   { printf '\033[1;33m! %s\033[0m\n' "$1"; }
die()    { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed. See /app/Fly.io Setup.md step 0."; }

require flyctl

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

[[ -f "$BACKEND_DIR/fly.toml"  ]] || die "Missing $BACKEND_DIR/fly.toml"
[[ -f "$FRONTEND_DIR/fly.toml" ]] || die "Missing $FRONTEND_DIR/fly.toml"

# ---------- first-time init ----------
init_apps() {
  color "» Creating Fly.io apps (idempotent — skips if they already exist)"
  flyctl apps create "$BACKEND_APP"  --org personal 2>/dev/null || warn "$BACKEND_APP already exists"
  flyctl apps create "$FRONTEND_APP" --org personal 2>/dev/null || warn "$FRONTEND_APP already exists"

  color "» You'll now be asked for the backend secrets. Have these ready:"
  echo "   • MongoDB Atlas connection string (mongodb+srv://...)"
  echo "   • Your EMERGENT_LLM_KEY (from Emergent → Profile → Universal Key)"
  echo ""
  read -r -p "MONGO_URL: " MONGO_URL
  read -r -p "EMERGENT_LLM_KEY: " EMERGENT_LLM_KEY
  read -r -p "DB_NAME [nua_restaurant]: " DB_NAME
  DB_NAME="${DB_NAME:-nua_restaurant}"

  JWT_SECRET="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 64)"
  FRONTEND_URL="https://${FRONTEND_APP}.fly.dev"

  color "» Setting backend secrets…"
  flyctl secrets set \
    MONGO_URL="$MONGO_URL" \
    DB_NAME="$DB_NAME" \
    JWT_SECRET="$JWT_SECRET" \
    EMERGENT_LLM_KEY="$EMERGENT_LLM_KEY" \
    FRONTEND_URL="$FRONTEND_URL" \
    --app "$BACKEND_APP"

  ok "Secrets stored. JWT_SECRET was auto-generated and is only on Fly."
  echo ""
  warn "Make sure $FRONTEND_DIR/fly.toml has:"
  echo "   REACT_APP_BACKEND_URL = \"https://${BACKEND_APP}.fly.dev\""
  echo "   (the deploy script reads it from there)"
}

deploy_backend() {
  color "» Deploying backend ($BACKEND_APP)…"
  (cd "$BACKEND_DIR" && flyctl deploy --app "$BACKEND_APP" --remote-only)
  ok "Backend live: https://${BACKEND_APP}.fly.dev"
}

deploy_frontend() {
  color "» Deploying frontend ($FRONTEND_APP)…"
  (cd "$FRONTEND_DIR" && flyctl deploy --app "$FRONTEND_APP" --remote-only)
  ok "Frontend live: https://${FRONTEND_APP}.fly.dev"
}

smoke() {
  color "» Smoke test…"
  if curl -fsS "https://${BACKEND_APP}.fly.dev/api/social/platforms" >/dev/null 2>&1; then
    ok "Backend reachable (got 200 anonymously — unexpected, but alive)"
  elif curl -fsS -o /dev/null -w "%{http_code}" "https://${BACKEND_APP}.fly.dev/api/social/platforms" | grep -q "401"; then
    ok "Backend reachable (401 = auth required — perfect)"
  else
    warn "Backend not responding yet — give it 30s and try: curl https://${BACKEND_APP}.fly.dev/api/social/platforms"
  fi
  if curl -fsS -o /dev/null "https://${FRONTEND_APP}.fly.dev/"; then
    ok "Frontend reachable"
  else
    warn "Frontend not responding yet — give it 30s"
  fi
}

case "${1:-all}" in
  init)      init_apps ;;
  backend)   deploy_backend && smoke ;;
  frontend)  deploy_frontend && smoke ;;
  all|"")    deploy_backend && deploy_frontend && smoke ;;
  *)         die "Unknown command: $1   (try: init | backend | frontend | all)" ;;
esac

ok "Done. Open https://${FRONTEND_APP}.fly.dev and log in with owner@nuva.com / NuvaOwner2026!"
