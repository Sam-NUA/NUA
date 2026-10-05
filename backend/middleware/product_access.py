"""Deny legacy staff surfaces to Booking-only accounts, including owner users.

The immutable server-created business ID namespace selects the product boundary.
Neither a tenant header nor the licensing development switch can disable it.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from services.booking_product import is_booking_account

AUTH_PATHS = {
    '/api/auth/login', '/api/auth/logout', '/api/auth/me', '/api/auth/refresh',
    '/api/auth/forgot-password', '/api/auth/reset-password', '/api/auth/2fa/challenge',
}
class ProductAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.scope['path'].rstrip('/')
        if request.method == 'OPTIONS' or not path.startswith('/api/'):
            return await call_next(request)
        token = request.cookies.get('access_token')
        if not token:
            value = request.headers.get('authorization', '')
            token = value[7:] if value.startswith('Bearer ') else request.query_params.get('token')
        if token:
            import os, jwt
            try:
                payload = jwt.decode(token, os.environ['JWT_SECRET'], algorithms=['HS256'])
            except jwt.InvalidTokenError:
                payload = {}
            if is_booking_account(payload.get('businessId')):
                if path not in AUTH_PATHS and not path.startswith('/api/booking-product/'):
                    return JSONResponse({'detail': 'This account has Booking access only.',
                        'errorCode': 'PRODUCT_NOT_ENTITLED'}, status_code=403)
        return await call_next(request)
