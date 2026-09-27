"""Keep Bookings routes separate from the POS frontend on a shared domain."""
from fastapi import FastAPI

from server import app as bookings_app, lifespan

# Vercel Services preserves the original URL path. Mounting gives FastAPI
# the correct root_path for routing and the generated OpenAPI documentation.
# Mounted applications do not receive lifespan events automatically.
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount('/bookings-api', bookings_app)
