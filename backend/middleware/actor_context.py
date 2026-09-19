"""
Actor / device / IP / tenant context — carried through the request lifecycle
via a `contextvars.ContextVar`, populated by a Starlette middleware and read
by `stamped_insert` / `stamped_update` when a route doesn't have the user
object directly in scope.

Design notes
────────────
• Missing business context never authorizes tenant-owned data access.
• Never overwrites an explicit `createdBy` passed by the caller.
• Public requests get device/IP context; a venue is resolved by their endpoint.
"""
from __future__ import annotations
from contextvars import ContextVar
from typing import Optional, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)

_actor_ctx: ContextVar[Optional[Dict[str, Any]]] = ContextVar("nua_actor_ctx", default=None)


def get_actor_context() -> Dict[str, Any]:
    """Read the actor context. Returns an empty dict when unset."""
    return _actor_ctx.get() or {}


def set_actor_context(ctx: Dict[str, Any]) -> None:
    _actor_ctx.set(ctx)


def tenant_scope_filter(business_id: Optional[str] = None) -> Dict[str, Any]:
    """Only verified tenant records are visible; unowned/quarantined rows are not.

    Background tasks must pass their tenant explicitly. Missing context produces
    an impossible predicate, never an unrestricted query.
    """
    biz = business_id if business_id is not None else get_actor_context().get("businessId")
    if not isinstance(biz, str) or not biz.strip():
        return {"$expr": {"$eq": [1, 0]}}
    return {"businessId": biz, "_ownershipQuarantined": {"$ne": True}}


def tenant_owns(doc_business_id: Optional[str], business_id: Optional[str] = None) -> bool:
    """Compatibility alias with the same fail-closed ownership contract."""
    return tenant_owns_strict(doc_business_id, business_id)


def tenant_owns_strict(doc_business_id: Optional[str], business_id: Optional[str] = None) -> bool:
    """Require a nonempty tenant and exact ownership, for reads and writes."""
    biz = business_id if business_id is not None else get_actor_context().get("businessId")
    return bool(isinstance(biz, str) and biz.strip() and doc_business_id == biz)


class ActorContextMiddleware(BaseHTTPMiddleware):
    """Populates the contextvar from request headers + JWT.

    Order matters: this runs BEFORE endpoint dependencies, so route handlers
    that call `stamped_insert(...)` without passing `user=` explicitly will
    still get the correct createdBy from the JWT.
    """

    async def dispatch(self, request, call_next):
        # Extract device + IP + tenant from headers
        device = request.headers.get("user-agent") or None
        client = request.client.host if request.client else None
        # Uvicorn applies configured proxy trust; never re-trust raw forwarding headers.
        ip = client
        location_id = request.headers.get("x-location-id")

        # Attempt to decode JWT quickly without triggering auth failures.
        # This is best-effort — protected routes still enforce auth normally.
        email = None
        role = None
        jwt_business_id = None
        auth = request.headers.get("authorization") or ""
        if request.cookies.get("access_token"):
            auth = "Bearer " + request.cookies["access_token"]
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
            try:
                import jwt
                import os
                secret = os.environ["JWT_SECRET"]
                data = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": True})
                if data.get("type") == "access":
                    from database import db
                    user = await db.auth_users.find_one({"id": data.get("sub"), "status": "active"})
                    if user:
                        email = user.get("email")
                        role = user.get("role")
                        jwt_business_id = user.get("businessId")
            except Exception:
                pass  # Auth will handle its own error on the route

        # Public callers cannot assert tenant membership through headers.
        # Guest routes resolve a venue explicitly; protected dependencies refresh
        # this context from the current user record before database operations.
        business_id = jwt_business_id

        ctx = {
            "email": email,
            "role": role,
            "device": (device[:200] if device else None),
            "ip": ip,
            "businessId": business_id,
            "locationId": location_id,
        }
        token = _actor_ctx.set(ctx)
        try:
            return await call_next(request)
        finally:
            _actor_ctx.reset(token)
