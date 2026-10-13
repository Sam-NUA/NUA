"""Minimum-supported-client-version gate (directive Phase 11).

Fail-open on absence, not presence: no existing web/Android/iOS/Windows
build sends X-App-Version today, and this must never start rejecting
every request from every client that predates this header existing. Only
a client that *does* send the header and reports a version below
version.MIN_SUPPORTED_APP_VERSION gets 426 Upgrade Required — a real,
narrow gate for a future native build that opts into reporting its
version, not a blanket enforcement switched on for everyone retroactively.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import version


class VersionGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # scope["path"], not request.url.path — see RequireAuthMiddleware's
        # own comment on why (an unvalidated Host header can rebuild
        # request.url to something other than what actually routed).
        # /api/version itself must never be gated: an out-of-date client
        # needs to be ABLE to call it to find out it's out of date.
        if request.scope["path"] in ("/api/version", "/api/health", "/api/healthz"):
            return await call_next(request)
        client_version = request.headers.get("x-app-version")
        if client_version and not version.is_supported(client_version):
            return JSONResponse(
                status_code=426,
                content={
                    "detail": "This app version is no longer supported. Please update.",
                    "minSupportedVersion": version.MIN_SUPPORTED_APP_VERSION,
                },
            )
        return await call_next(request)
