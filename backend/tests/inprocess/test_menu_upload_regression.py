"""Exercise menu uploads through HTTP and the real public SDK serializer."""
import base64
import io
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pypdf import PdfWriter

from conftest import req
from services import ai_provider as ai


def _provider(monkeypatch, *, content=None, finish_reason="stop", status=200):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "private provider detail"}})
        return httpx.Response(200, json={"id": "chatcmpl-menu", "object": "chat.completion",
            "created": 0, "model": "gpt-5.2", "choices": [{"index": 0,
            "finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}]})

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-menu-key")
    monkeypatch.delenv("NUA_AI_MODEL", raising=False)
    monkeypatch.setattr(ai, "_client", lambda: AsyncOpenAI(api_key="test-only-menu-key", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    return captured


def _upload(client, headers, data, kind="image"):
    return req(client, "POST", "/api/menu/ai-preview", headers=headers,
               json={"fileData": data, "fileType": kind})


def test_pdf_without_text_layer_reaches_vision_and_review_can_commit(client, owner_headers, monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    encoded = base64.b64encode(buf.getvalue()).decode()
    captured = _provider(monkeypatch, content=json.dumps([
        {"name": "Menu regression coffee", "category": "Coffee", "price": 5.5}]))
    from database import db
    before = client.portal.call(db.products.count_documents, {})
    response = _upload(client, owner_headers, encoded, "pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert client.portal.call(db.products.count_documents, {}) == before
    part = captured[0]["messages"][-1]["content"][1]
    assert part == {"type": "file", "file": {"filename": "menu.pdf",
        "file_data": f"data:application/pdf;base64,{encoded}"}}
    item = body["items"][0]
    response = req(client, "POST", "/api/menu/ai-commit", headers=owner_headers,
                   json={"items": [{**item, "skipIfDuplicate": False}]})
    assert response.status_code == 200, response.text
    saved = response.json()["items"][0]
    assert saved["name"] == item["name"] and saved["price"] == 5.5
    assert saved["businessId"] == "default"
    client.portal.call(db.products.delete_one, {"id": saved["id"]})


def test_photo_uses_larger_output_budget_and_low_reasoning(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content='[{"name":"Toast","price":8}]')
    image = base64.b64encode(b"\x89PNG\r\n\x1a\nimage").decode()
    response = _upload(client, owner_headers, f"data:image/png;base64,{image}")
    assert response.status_code == 200 and response.json()["count"] == 1
    assert captured[0]["max_completion_tokens"] == 16384
    assert captured[0]["reasoning_effort"] == "low"
    assert captured[0]["store"] is False
    assert captured[0]["messages"][-1]["content"][1]["type"] == "image_url"


@pytest.mark.parametrize("content", [None, '[{"name":"unfinished'])
def test_token_exhaustion_is_reported_instead_of_no_items(client, owner_headers, monkeypatch, content):
    _provider(monkeypatch, content=content, finish_reason="length")
    response = _upload(client, owner_headers, base64.b64encode(b"GIF89aimage").decode())
    assert response.status_code == 422
    assert "fewer menu pages" in response.json()["detail"]


def test_missing_configuration_is_actionable(client, owner_headers, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = _upload(client, owner_headers, "anything")
    assert response.status_code == 503 and "OPENAI_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize("data", ["!!!!", base64.b64encode(b"not a pdf").decode(), "A" * 4_000_004],
                         ids=["invalid-base64", "not-a-pdf", "oversized-pdf"])
def test_invalid_pdf_is_rejected_before_provider_call(client, owner_headers, monkeypatch, data):
    captured = _provider(monkeypatch, content="[]")
    response = _upload(client, owner_headers, data, "pdf")
    assert response.status_code == 422 and not captured


def test_provider_failure_is_redacted(client, owner_headers, monkeypatch):
    _provider(monkeypatch, status=429)
    response = _upload(client, owner_headers, base64.b64encode(b"GIF89aimage").decode())
    assert response.status_code == 422 and "429" in response.json()["detail"]
    assert "private provider detail" not in response.text


def test_malformed_response_is_distinct_from_empty_menu(client, owner_headers, monkeypatch):
    _provider(monkeypatch, content="broken JSON")
    response = _upload(client, owner_headers, base64.b64encode(b"GIF89aimage").decode())
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


def test_model_override_without_reasoning_support(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content="[]")
    monkeypatch.setenv("NUA_AI_MODEL", "gpt-4.1")
    response = _upload(client, owner_headers, base64.b64encode(b"GIF89aimage").decode())
    assert response.status_code == 200
    assert captured[0]["model"] == "gpt-4.1"
    assert "reasoning_effort" not in captured[0]


def test_pasted_text_menu_reaches_the_provider_as_plain_text_and_review_can_commit(client, owner_headers, monkeypatch):
    menu_text = "Flat White - $5.50\nLong Black - $4.80\nCroissant - $6.00"
    captured = _provider(monkeypatch, content=json.dumps([
        {"name": "Flat White", "category": "Coffee", "price": 5.5},
        {"name": "Long Black", "category": "Coffee", "price": 4.8},
        {"name": "Croissant", "category": "Bakery", "price": 6.0}]))
    from database import db
    before = client.portal.call(db.products.count_documents, {})
    response = _upload(client, owner_headers, menu_text, "text")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 3
    assert client.portal.call(db.products.count_documents, {}) == before
    # A text upload has no file part at all — just the pasted text inline.
    part = captured[0]["messages"][-1]["content"]
    assert len(part) == 1 and part[0]["type"] == "text" and menu_text in part[0]["text"]
    item = body["items"][0]
    response = req(client, "POST", "/api/menu/ai-commit", headers=owner_headers,
                   json={"items": [{**item, "skipIfDuplicate": False}]})
    assert response.status_code == 200, response.text
    saved = response.json()["items"][0]
    assert saved["name"] == "Flat White" and saved["price"] == 5.5
    client.portal.call(db.products.delete_one, {"id": saved["id"]})


def test_empty_pasted_text_is_a_clean_no_items_response_not_a_provider_call(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content="[]")
    response = _upload(client, owner_headers, "   ", "text")
    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert not captured, "blank pasted text must never reach the provider"


def test_oversized_pasted_text_is_rejected_before_the_provider_call(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content="[]")
    response = _upload(client, owner_headers, "A" * 100_001, "text")
    assert response.status_code == 413
    assert "too long" in response.json()["detail"]
    assert not captured


# ============ DETERMINISTIC, NO-API-KEY PATHS (PDF text / XLSX / XLS) ============
# A spreadsheet, or a PDF with real embedded text, never needs the AI
# provider at all — only a scanned/photographed PDF or an actual photo
# does, since reading a picture has no deterministic alternative.

def _text_pdf_base64():
    """A real PDF with embedded, selectable text (unlike the blank-page
    PDF above, which has none) — built the same way a menu exported from
    Word/Canva/a POS system would be."""
    import io as _io
    from reportlab.pdfgen import canvas
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 400))
    c.drawString(20, 380, "COFFEE")
    c.drawString(20, 360, "Flat White .......... $5.50")
    c.drawString(20, 340, "Long Black .......... $4.80")
    c.drawString(20, 320, "BAKERY")
    c.drawString(20, 300, "Croissant 6.00")
    c.save()
    return base64.b64encode(buf.getvalue()).decode()


def test_text_pdf_is_parsed_deterministically_without_any_api_key(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content="[]")
    # _provider() sets OPENAI_API_KEY as a side effect of configuring the
    # mock transport — undo that so this test genuinely has no key.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = _upload(client, owner_headers, _text_pdf_base64(), "pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 3
    names = {item["name"] for item in body["items"]}
    assert names == {"Flat White", "Long Black", "Croissant"}
    flat_white = next(i for i in body["items"] if i["name"] == "Flat White")
    # categoryMatched/category reflect the usual fuzzy-match-to-existing-
    # category step, same as any other extraction path — proposedCategory
    # is what the deterministic parser itself actually read off the PDF.
    assert flat_white["price"] == 5.5 and flat_white["proposedCategory"] == "COFFEE"
    assert not captured, "a text-based PDF must never reach the AI provider"


def test_scanned_pdf_with_no_embedded_text_still_requires_the_api_key(client, owner_headers, monkeypatch):
    # The existing blank-page PDF test above proves the *success* path
    # with a key configured; this proves the no-key failure path gives an
    # accurate, specific message rather than the generic one.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import io as _io
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buf = _io.BytesIO()
    writer.write(buf)
    response = _upload(client, owner_headers, base64.b64encode(buf.getvalue()).decode(), "pdf")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "scanned or photographed" in detail and "OPENAI_API_KEY" in detail


def test_text_pdf_with_no_priced_lines_degrades_gracefully_without_a_key(client, owner_headers, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import io as _io
    from reportlab.pdfgen import canvas
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 400))
    c.drawString(20, 380, "Welcome to our restaurant, please see staff for today's specials")
    c.save()
    encoded = base64.b64encode(buf.getvalue()).decode()
    response = _upload(client, owner_headers, encoded, "pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 0
    assert "couldn't automatically detect priced items" in body["message"]


def test_text_pdf_with_no_priced_lines_tries_ai_when_a_key_is_configured(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content=json.dumps([{"name": "Chef's Special", "price": 22.0}]))
    import io as _io
    from reportlab.pdfgen import canvas
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 400))
    c.drawString(20, 380, "Welcome to our restaurant, please see staff for today's specials")
    c.save()
    encoded = base64.b64encode(buf.getvalue()).decode()
    response = _upload(client, owner_headers, encoded, "pdf")
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1
    assert captured, "a text PDF with no parseable items may opportunistically use AI when a key IS configured"


def _xlsx_base64(rows, headers=("Name", "Category", "Price", "Cost", "Description")):
    import io as _io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    buf = _io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def test_xlsx_is_parsed_deterministically_without_any_api_key(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content="[]")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    encoded = _xlsx_base64([
        ("Flat White", "Coffee", 5.5, 2.0, "Milky espresso"),
        ("Croissant", "Bakery", 6.0, 2.1, ""),
    ])
    response = _upload(client, owner_headers, encoded, "xlsx")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    flat_white = next(i for i in body["items"] if i["name"] == "Flat White")
    assert flat_white["price"] == 5.5 and flat_white["cost"] == 2.0 and flat_white["proposedCategory"] == "Coffee"
    assert not captured, "an xlsx upload must never reach the AI provider"


def test_xls_legacy_binary_is_parsed_deterministically_without_any_api_key(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content="[]")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import io as _io
    import xlwt
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Menu")
    for col, header in enumerate(["Item", "Category", "Price", "Cost"]):
        ws.write(0, col, header)
    ws.write(1, 0, "Long Black")
    ws.write(1, 1, "Coffee")
    ws.write(1, 2, 4.8)
    ws.write(1, 3, 1.5)
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = base64.b64encode(buf.getvalue()).decode()
    response = _upload(client, owner_headers, encoded, "xls")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["name"] == "Long Black" and body["items"][0]["price"] == 4.8
    assert not captured, "an xls upload must never reach the AI provider"


def test_xlsx_without_a_recognizable_header_is_a_clean_no_items_response(client, owner_headers, monkeypatch):
    captured = _provider(monkeypatch, content="[]")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    encoded = _xlsx_base64([("some", "random", "data")], headers=("Foo", "Bar", "Baz"))
    response = _upload(client, owner_headers, encoded, "xlsx")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 0
    assert "No recognizable item rows" in body["message"]
    assert not captured
