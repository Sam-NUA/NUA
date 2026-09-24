"""NUA Bookings — standalone partner API service.

Its own database, its own versioned public API. NUA Counter consumes this the
same way any external POS does: over HTTP with a partner key ("nua-native").
The allocation logic in allocation.py is the platform's licensed IP and only
ever executes here — hosted API access only, no self-hosted distribution.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import routes_admin
import routes_public
import routes_v1
import webhooks

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app):
    await webhooks.start_worker()
    try:
        yield
    finally:
        await webhooks.stop_worker()


app = FastAPI(
    lifespan=lifespan,
    title="NUA Bookings API",
    version="1.0",
    description="Multi-tenant bookings platform. All /v1 routes require a partner API key.",
    # Partners get the API contract, not the implementation.
    docs_url="/docs", redoc_url=None,
)

app.include_router(routes_v1.router)
app.include_router(routes_admin.router)
app.include_router(routes_public.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nua-bookings"}
