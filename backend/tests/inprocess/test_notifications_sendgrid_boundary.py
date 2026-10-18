"""utils/notifications.py's send_email() is the literal code that would run
in production for every owner password-reset email, PO-supplier email, and
customer order update — but every existing test (test_password_reset.py,
test_po_supplier_email.py, ...) replaces send_email() itself with a fake,
so none of them ever exercise the real SendGrid SDK call it makes: the
`Mail(...)` object construction, the `SendGridAPIClient(api_key).send(msg)`
call, or its success/rejection/exception handling. This mocks the SDK
boundary instead (`SendGridAPIClient.send`, following the same
monkeypatch-the-provider-not-our-own-wrapper pattern test_durable_backups.py
already uses for `vercel.blob`), so a real SendGrid key dropped into
SENDGRID_API_KEY/SENDGRID_FROM_EMAIL is the only thing standing between this
and an actually-delivered email — not an untested code path.
"""
import asyncio
from types import SimpleNamespace

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def sendgrid_config(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "test-only-key")
    monkeypatch.setenv("SENDGRID_FROM_EMAIL", "help@example.com")


def test_a_successful_send_builds_the_real_sendgrid_message_and_reports_delivered(monkeypatch):
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    import utils.notifications as notifications

    captured = {}

    def fake_send(self, message):
        captured["message"] = message
        captured["api_key"] = self.api_key
        return SimpleNamespace(status_code=202)

    monkeypatch.setattr(SendGridAPIClient, "send", fake_send)

    result = _run(notifications.send_email("owner@nua.com", "Reset your password", "<p>link</p>"))

    assert result == {"channel": "email", "delivered": True, "to": "owner@nua.com"}
    assert captured["api_key"] == "test-only-key"
    sent = captured["message"]
    assert isinstance(sent, Mail)
    # The Mail object's own getters, not our input strings — proves the SDK
    # actually received the sender/recipient/subject/body we passed it.
    rendered = sent.get()
    assert rendered["from"]["email"] == "help@example.com"
    assert rendered["personalizations"][0]["to"][0]["email"] == "owner@nua.com"
    assert rendered["subject"] == "Reset your password"
    assert rendered["content"][0]["value"] == "<p>link</p>"


def test_a_provider_rejection_status_is_reported_as_not_delivered(monkeypatch):
    from sendgrid import SendGridAPIClient

    monkeypatch.setattr(SendGridAPIClient, "send", lambda self, message: SimpleNamespace(status_code=400))
    import utils.notifications as notifications

    result = _run(notifications.send_email("owner@nua.com", "subject", "body"))
    assert result == {"channel": "email", "delivered": False, "reason": "provider_rejected"}


def test_an_sdk_exception_is_caught_and_reported_not_raised(monkeypatch):
    from sendgrid import SendGridAPIClient

    def raises(self, message):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(SendGridAPIClient, "send", raises)
    import utils.notifications as notifications

    result = _run(notifications.send_email("owner@nua.com", "subject", "body"))
    assert result["channel"] == "email"
    assert result["delivered"] is False
    assert "connection refused" in result["reason"]


def test_missing_config_never_reaches_the_sdk_at_all(monkeypatch):
    from sendgrid import SendGridAPIClient

    called = []
    monkeypatch.setattr(SendGridAPIClient, "send", lambda self, message: called.append(1))
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    import utils.notifications as notifications

    result = _run(notifications.send_email("owner@nua.com", "subject", "body"))
    assert result == {"channel": "email", "delivered": False, "reason": "not_configured"}
    assert called == [], "must not import/construct the SDK at all when unconfigured"
