"""Small async Checkout adapter over the public, pinned Stripe SDK.

The routes retain their authorization, resource ownership and durable claim logic.
Provider idempotency also covers a response lost after Stripe created the session.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import stripe


@dataclass
class CheckoutSessionRequest:
    amount: float
    currency: str
    success_url: str
    cancel_url: str
    metadata: dict
    idempotency_key: str | None = None


@dataclass
class CheckoutSession:
    session_id: str
    url: str


class StripeCheckout:
    def __init__(self, *, api_key, webhook_url=None):
        if not api_key:
            raise ValueError("Stripe not configured")
        self.api_key = api_key

    async def create_checkout_session(self, request):
        try:
            amount = Decimal(str(request.amount))
            if not amount.is_finite() or amount <= 0:
                raise ValueError("Invalid checkout amount")
            cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, OverflowError):
            raise ValueError("Invalid checkout amount") from None
        if not 1 <= cents <= 99_999_999 or request.currency.lower() != "aud":
            raise ValueError("Unsupported checkout amount or currency")
        options = {"api_key": self.api_key}
        if request.idempotency_key:
            options["idempotency_key"] = request.idempotency_key
        session = await stripe.checkout.Session.create_async(
            mode="payment", success_url=request.success_url, cancel_url=request.cancel_url,
            metadata=request.metadata,
            line_items=[{"quantity": 1, "price_data": {"currency": "aud", "unit_amount": cents,
                         "product_data": {"name": "NUA checkout"}}}], **options)
        if not session.id or not session.url:
            raise ValueError("Stripe did not return a checkout session")
        return CheckoutSession(session_id=session.id, url=session.url)

    async def get_checkout_status(self, session_id):
        return await stripe.checkout.Session.retrieve_async(session_id, api_key=self.api_key)


def provider_idempotency_key(namespace, key):
    return hashlib.sha256(f"nua:{namespace}:{key}".encode()).hexdigest()
