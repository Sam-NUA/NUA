"""Remediation of the final readiness audit's Medium finding: POST
/api/pos/voice-order (routes/v15_features.py's voice_order) wrote decoded
guest audio to a NamedTemporaryFile(delete=False) and never cleaned it up —
on any code path, success or failure — leaving raw audio on local disk
indefinitely. Fixed with a guaranteed finally block; verified here on both
the success path and an exception raised mid-transcription.
"""
import base64
import glob
import os
import tempfile

from tests.inprocess.conftest import req


class _FakeTranscript:
    text = "one flat white"


class _FakeTranscriptions:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    def create(self, model, file):
        if self.should_fail:
            raise RuntimeError("simulated transcription provider failure")
        return _FakeTranscript()


class _FakeAudio:
    def __init__(self, should_fail=False):
        self.transcriptions = _FakeTranscriptions(should_fail=should_fail)


class _FakeOpenAI:
    def __init__(self, should_fail=False, **kwargs):
        self.audio = _FakeAudio(should_fail=should_fail)


def _tmp_count():
    return len(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*")))


def test_temp_audio_file_is_deleted_after_a_successful_transcription(client, owner_headers, monkeypatch):
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _FakeOpenAI(should_fail=False))

    audio_b64 = base64.b64encode(b"fake audio bytes for cleanup test").decode()
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*")))
    r = req(client, "POST", "/api/pos/voice-order", headers=owner_headers,
            json={"audioBase64": audio_b64, "mime": "audio/webm"})
    assert r.status_code == 200, r.text[:200]
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*")))
    leaked = [p for p in (after - before) if os.path.exists(p)]
    assert not leaked, f"the temp audio file must be deleted after a successful transcription — leaked: {leaked}"


def test_temp_audio_file_is_deleted_even_when_transcription_raises(client, owner_headers, monkeypatch):
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _FakeOpenAI(should_fail=True))

    audio_b64 = base64.b64encode(b"fake audio bytes for failure cleanup test").decode()
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*")))
    r = req(client, "POST", "/api/pos/voice-order", headers=owner_headers,
            json={"audioBase64": audio_b64, "mime": "audio/webm"})
    assert r.status_code == 500  # the simulated provider failure surfaces as an error
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*")))
    leaked = [p for p in (after - before) if os.path.exists(p)]
    assert not leaked, (
        f"the temp audio file must be deleted even when transcription fails — leaked: {leaked}"
    )
