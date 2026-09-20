# Nua Backend — FastAPI + Motor (MongoDB driver)
# Used by Fly.io, Railway, Render, Docker Compose — anywhere that speaks Docker.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Native deps for cryptography, bcrypt, etc.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional AI extras, served from a private index. Every import site in the
# codebase try/excepts this package and degrades to a non-LLM path, so an
# index outage must never take the build down with it — hence `|| true`
# and a separate layer rather than `&&` onto the line above.
RUN pip install --no-cache-dir emergentintegrations \
      --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ \
 || echo "emergentintegrations unavailable — continuing without AI extras"

# Copy the app
COPY . .

ENV PORT=8001
EXPOSE 8001

# Use uvicorn directly (single worker; the platform handles horizontal scaling).
# --proxy-headers respects the X-Forwarded-* set by the edge proxy, but only
# from a peer whose real TCP source IP is in --forwarded-allow-ips — '*'
# (the old unconditional default) told uvicorn to trust that header from
# ANY caller, meaning any internet client could set X-Forwarded-For to
# whatever it wanted and have request.client.host become that spoofed
# value, bypassing every IP-keyed rate limit and the login/2FA brute-force
# lockout (see TRUST_RELEASE_FINAL_REPORT.md §11.4/§11.9). Now reads
# FORWARDED_ALLOW_IPS from the environment, defaulting to '127.0.0.1' —
# i.e. trust nothing by default (request.client.host reflects the real
# TCP peer, safe on an internet-facing deployment with no proxy in
# front of it) — rather than trusting everything by default. Whoever
# operates the real deployment must explicitly set FORWARDED_ALLOW_IPS to
# their actual edge proxy's IP address(es)/CIDR (comma-separated, or the
# literal '*' — never do this unless a header-stripping proxy is
# confirmed to sit in front of every path to this container) once that
# topology is confirmed; see FORWARDED_ALLOW_IPS_SETUP.md.
# $PORT is honoured because Railway assigns it dynamically; Fly and Compose
# fall back to the 8001 default above.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8001} --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
