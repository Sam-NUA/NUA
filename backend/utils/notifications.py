"""Notification abstraction.

Tries SendGrid (email) + Twilio (SMS) when API keys are present in env. Falls
back to persisting the notification on the order document. Wiring real channels
is a config change, not a code change.

ENV (optional):
  SENDGRID_API_KEY, SENDGRID_FROM_EMAIL
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_PHONE
"""
from __future__ import annotations
import os
import asyncio
import logging
from typing import Optional

log = logging.getLogger("notifications")


async def send_email(to: str, subject: str, body: str) -> dict:
    """Email via SendGrid. No-op (logs only) when keys absent."""
    if not (to or "").strip():
        return {"channel": "email", "delivered": False, "reason": "no_recipient"}
    api_key = os.environ.get("SENDGRID_API_KEY")
    sender = os.environ.get("SENDGRID_FROM_EMAIL")
    if not api_key or not sender:
        log.info("email-skipped to=%s subject=%s (SendGrid not configured)", to, subject)
        return {"channel": "email", "delivered": False, "reason": "not_configured"}
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        msg = Mail(from_email=sender, to_emails=to, subject=subject, html_content=body)
        response = await asyncio.to_thread(SendGridAPIClient(api_key).send, msg)
        if not 200 <= response.status_code < 300:
            return {"channel": "email", "delivered": False, "reason": "provider_rejected"}
        return {"channel": "email", "delivered": True, "to": to}
    except Exception as e:
        log.exception("email-failed: %s", e)
        return {"channel": "email", "delivered": False, "reason": str(e)[:120]}


async def send_sms(to: str, body: str) -> dict:
    """SMS via Twilio. No-op when keys absent."""
    if not (to or "").strip():
        return {"channel": "sms", "delivered": False, "reason": "no_recipient"}
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    sender = os.environ.get("TWILIO_FROM_PHONE")
    if not all([sid, token, sender]):
        log.info("sms-skipped to=%s (Twilio not configured)", to)
        return {"channel": "sms", "delivered": False, "reason": "not_configured"}
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(body=body[:320], from_=sender, to=to)
        return {"channel": "sms", "delivered": True, "to": to}
    except Exception as e:
        log.exception("sms-failed: %s", e)
        return {"channel": "sms", "delivered": False, "reason": str(e)[:120]}


async def notify_order(order: dict, message: str, subject: Optional[str] = None) -> list[dict]:
    """Best-effort multi-channel send. Returns delivery receipts."""
    cust = order.get("customer") or {}
    receipts = []
    if cust.get("email"):
        receipts.append(await send_email(
            cust["email"],
            subject or f"Update on order {order.get('id', '')}",
            f"<p>{message}</p><p style='color:#999;font-size:12px'>Order: {order.get('id','')}</p>",
        ))
    if cust.get("phone"):
        receipts.append(await send_sms(cust["phone"], f"{message} (#{order.get('id','')})"))
    return receipts
