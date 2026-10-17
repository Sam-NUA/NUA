"""NUA's bounded OpenAI adapter. No proprietary gateway or shared conversation state."""
import base64
import binascii
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from openai import AsyncOpenAI, APIError


class AIProviderError(RuntimeError):
    pass


def _client():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise AIProviderError("AI not configured: OPENAI_API_KEY is required")
    # Custom compatible endpoints require an explicit, encrypted server setting.
    base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    origin = urlsplit(base_url)
    if origin.scheme != "https" or not origin.hostname or origin.username or origin.password:
        raise AIProviderError("OPENAI_BASE_URL must be an HTTPS endpoint without embedded credentials")
    return AsyncOpenAI(api_key=key, base_url=base_url,
                       timeout=30.0, max_retries=1)


@dataclass
class ImageContent:
    image_base64: str

    def part(self):
        value = self.image_base64
        if value.startswith("data:"):
            value = value.split(",", 1)[-1]
        if len(value) > 12_000_000:
            raise AIProviderError("AI image is too large")
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise AIProviderError("Invalid base64 image") from None
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif raw.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif raw.startswith((b"GIF87a", b"GIF89a")):
            mime = "image/gif"
        elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise AIProviderError("Unsupported image format")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{value}"}}


@dataclass
class UserMessage:
    text: str
    file_contents: list[ImageContent] = field(default_factory=list)


class LlmChat:
    """Preserves existing route prompts; history belongs only to this instance."""
    def __init__(self, *, api_key=None, session_id=None, system_message=""):
        self.system = system_message
        self.model = "gpt-5.2"
        self.max_tokens = 4096
        self.history = []

    def with_model(self, provider, model):
        if provider != "openai":
            raise AIProviderError("Unsupported AI provider")
        self.model = model
        return self

    def with_max_tokens(self, limit):
        self.max_tokens = max(1, min(int(limit), 16384))
        return self

    async def send_message(self, message):
        content = [{"type": "text", "text": message.text}]
        content.extend(image.part() for image in message.file_contents)
        messages = [{"role": "system", "content": self.system}, *self.history[-16:],
                    {"role": "user", "content": content}]
        try:
            async with _client() as client:
                response = await client.chat.completions.create(
                    model=os.environ.get("NUA_AI_MODEL") or self.model, messages=messages,
                    max_completion_tokens=self.max_tokens, store=False)
        except APIError as error:
            raise AIProviderError(f"AI provider request failed (status {getattr(error, 'status_code', None) or 'unavailable'})") from None
        if not response.choices or not response.choices[0].message.content:
            raise AIProviderError("AI provider returned no usable content")
        answer = response.choices[0].message.content
        self.history.extend([messages[-1], {"role": "assistant", "content": answer}])
        self.history = self.history[-16:]
        return answer


class OpenAIAudio:
    def __init__(self, api_key=None):
        pass

    async def audio_to_text(self, *, content, mime_type="audio/webm", language="en"):
        extensions = {"audio/webm": "webm", "audio/mpeg": "mp3", "audio/mp3": "mp3",
                      "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a",
                      "audio/ogg": "ogg", "audio/flac": "flac"}
        mime_type = mime_type.split(";", 1)[0].strip().lower()
        if mime_type not in extensions or not content or len(content) > 20_000_000:
            raise AIProviderError("Unsupported or oversized audio")
        try:
            async with _client() as client:
                response = await client.audio.transcriptions.create(
                    model=os.environ.get("NUA_TRANSCRIPTION_MODEL") or "whisper-1",
                    file=(f"recording.{extensions[mime_type]}", content, mime_type), language=language)
        except APIError as error:
            raise AIProviderError(f"Transcription provider request failed (status {getattr(error, 'status_code', None) or 'unavailable'})") from None
        if not response.text.strip():
            raise AIProviderError("Transcription returned no text")
        return response.text
