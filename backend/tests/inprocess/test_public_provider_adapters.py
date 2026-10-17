"""Public SDK boundaries, exercised without external calls or credentials."""
import base64
import json
from functools import partial
from types import SimpleNamespace
import httpx
import pytest
from openai import AsyncOpenAI
from conftest import req
from services import ai_provider as ai
from services.stripe_checkout import CheckoutSessionRequest, StripeCheckout, provider_idempotency_key


def _transport(monkeypatch, handler):
    monkeypatch.setattr(ai, '_client', lambda: AsyncOpenAI(api_key='test-only-provider-boundary', max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))


def test_chat_payload_images_history_and_tenant_separation(client, monkeypatch):
    captured = []

    def handler(request):
        assert str(request.url) == 'https://api.openai.com/v1/chat/completions'
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'chatcmpl-test', 'object': 'chat.completion', 'created': 0,
            'model': 'gpt-5.2', 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': '[{"name":"Coffee","price":5.5}]'}}]})

    _transport(monkeypatch, handler)
    monkeypatch.setenv('NUA_AI_MODEL', 'test-configured-model')
    first = ai.LlmChat(system_message='Extract menu')
    image = ai.ImageContent(base64.b64encode(b'\x89PNG\r\n\x1a\nimage').decode())
    assert json.loads(client.portal.call(first.send_message, ai.UserMessage('menu', [image])))[0]['price'] == 5.5
    client.portal.call(first.send_message, ai.UserMessage('followup'))
    client.portal.call(ai.LlmChat(system_message='other business').send_message, ai.UserMessage('new'))
    assert captured[0]['model'] == 'test-configured-model' and captured[0]['store'] is False
    assert captured[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert len(captured[1]['messages']) == 4 and len(captured[2]['messages']) == 2
    assert 'Extract menu' not in json.dumps(captured[2])


def test_missing_key_cannot_fall_back_to_legacy_gateway(client, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('EMERGENT_LLM_KEY', 'test-only-legacy-key')
    with pytest.raises(ai.AIProviderError, match='OPENAI_API_KEY'):
        client.portal.call(ai.LlmChat().send_message, ai.UserMessage('hello'))


def test_provider_error_redacts_response_body(client, monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(429, json={'error': {'message': 'sensitive provider detail'}}))
    with pytest.raises(ai.AIProviderError) as caught:
        client.portal.call(ai.LlmChat().send_message, ai.UserMessage('hello'))
    assert '429' in str(caught.value) and 'sensitive' not in str(caught.value)


@pytest.mark.parametrize('value', ['https://untrusted.example/image.png', '!!!!', base64.b64encode(b'<svg/>').decode()])
def test_images_reject_remote_urls_invalid_base64_and_unsupported_formats(value):
    with pytest.raises(ai.AIProviderError):
        ai.ImageContent(value).part()


def test_transcription_uses_named_file_and_mime(client, monkeypatch):
    def handler(request):
        assert request.url.path == '/v1/audio/transcriptions'
        assert b'filename="recording.webm"' in request.content and b'audio/webm' in request.content
        return httpx.Response(200, json={'text': 'two flat whites'})

    _transport(monkeypatch, handler)
    assert client.portal.call(partial(ai.OpenAIAudio().audio_to_text,
        content=b'audio-sample', mime_type='audio/webm;codecs=opus')) == 'two flat whites'


def test_invalid_audio_never_calls_provider(client):
    with pytest.raises(ai.AIProviderError):
        client.portal.call(partial(ai.OpenAIAudio().audio_to_text, content=b'', mime_type='text/html'))


def test_checkout_uses_minor_units_metadata_and_scoped_provider_idempotency(client, monkeypatch):
    import stripe
    captured = []

    async def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(id='cs_test_boundary', url='https://checkout.stripe.com/test-boundary')

    monkeypatch.setattr(stripe.checkout.Session, 'create_async', create)
    key = provider_idempotency_key('pos', 'business-A:attempt')
    request = CheckoutSessionRequest(19.5, 'aud', 'https://example.com/s', 'https://example.com/c', {'orderId': 'A'}, key)
    result = client.portal.call(StripeCheckout(api_key='test-only-provider-boundary').create_checkout_session, request)
    assert result.session_id == 'cs_test_boundary'
    assert captured[0]['line_items'][0]['price_data']['unit_amount'] == 1950
    assert captured[0]['idempotency_key'] == key != provider_idempotency_key('pos', 'business-B:attempt')
    assert captured[0]['metadata'] == {'orderId': 'A'} and captured[0]['mode'] == 'payment'


@pytest.mark.parametrize('amount', [0, -1, float('nan'), float('inf')])
def test_invalid_checkout_amount_never_calls_provider(client, amount):
    with pytest.raises(ValueError):
        client.portal.call(StripeCheckout(api_key='test-only').create_checkout_session,
            CheckoutSessionRequest(amount, 'aud', 'https://example.com/s', 'https://example.com/c', {}))


def test_checkout_status_preserves_unpaid_sdk_result(client, monkeypatch):
    import stripe
    status = SimpleNamespace(status='open', payment_status='unpaid', amount_total=1950, currency='aud')

    async def retrieve(session_id, **kwargs):
        assert session_id == 'cs_test_status'
        return status

    monkeypatch.setattr(stripe.checkout.Session, 'retrieve_async', retrieve)
    assert client.portal.call(StripeCheckout(api_key='test-only').get_checkout_status, 'cs_test_status') is status


def test_unconfigured_checkout_status_contract(client, monkeypatch):
    monkeypatch.delenv('STRIPE_API_KEY', raising=False)
    response = req(client, 'GET', '/api/stripe/checkout/status/cs_test_unconfigured')
    assert response.status_code == 200 and response.json()['configured'] is False


@pytest.mark.parametrize("url", ["http://example.com/v1", "https://user:pass@example.com/v1", "file:///tmp/provider"])
def test_custom_ai_endpoint_cannot_send_key_over_plaintext_or_embedded_credentials(monkeypatch, url):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-provider-key")
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    with pytest.raises(ai.AIProviderError, match="HTTPS"):
        ai._client()
