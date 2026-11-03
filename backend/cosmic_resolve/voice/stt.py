"""Speech to text through Groq's OpenAI-compatible Whisper endpoint. httpx is imported lazily.

Measured on the demo laptop: about 0.19 s for a 4-5 second clip. Free-tier limits are per organization (reported as
20 requests/minute and 2,000/day for whisper-large-v3-turbo; verify in the Groq console). The key is read from the
environment only and is never logged or returned to the browser.
"""
from __future__ import annotations

import os
import re
from typing import Any

from . import agent_config as cfg
from .llm import VoiceConfigError

TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Whisper is known to invent short phrases from silence or noise. A clip that yields only one of these is treated as nothing.
_NOISE_PHRASES = {
    "thank you", "thanks", "thanks for watching", "thank you for watching", "you", "bye", "okay", "mm", "hmm", "uh", "um",
}


class TranscriptionError(RuntimeError):
    """The speech service failed or refused (network, rate limit, bad audio)."""


def is_probably_noise(text: str) -> bool:
    cleaned = re.sub(r"[^a-z' ]", "", text.lower()).strip()
    return len(cleaned) < 2 or cleaned in _NOISE_PHRASES


class GroqTranscriber:
    def __init__(self, api_key: str | None = None, model: str | None = None, client: Any | None = None) -> None:
        self.api_key = api_key or os.environ.get(cfg.ENV_GROQ_KEY, "").strip()
        self.model = model or os.environ.get(cfg.ENV_STT_MODEL, "").strip()
        missing = [name for name, value in ((cfg.ENV_GROQ_KEY, self.api_key), (cfg.ENV_STT_MODEL, self.model)) if not value]
        if missing:
            raise VoiceConfigError("Set " + " and ".join(missing) + " to use speech to text.")
        if client is None:
            try:
                import httpx  # lazy
            except ImportError as exc:  # pragma: no cover - depends on the install
                raise VoiceConfigError('httpx is not installed. Run: pip install -e "backend[voice]"') from exc
            client = httpx.Client(timeout=20)  # one client so the TLS connection is reused between turns
        self._client = client

    def transcribe(self, audio: bytes, filename: str = "speech.webm", content_type: str = "audio/webm") -> str:
        try:
            response = self._client.post(
                TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (filename, audio, content_type)},
                data={"model": self.model, "response_format": "json", "language": "en", "temperature": "0"},
            )
        except Exception as exc:  # noqa: BLE001 - connection, timeout
            raise TranscriptionError("Could not reach the speech service.") from exc
        if response.status_code == 429:
            raise TranscriptionError("The speech service is busy. Please try again in a moment.")
        if response.status_code != 200:
            raise TranscriptionError(f"The speech service returned an error ({response.status_code}).")
        try:
            return str(response.json().get("text", "")).strip()
        except ValueError as exc:
            raise TranscriptionError("The speech service returned an unreadable reply.") from exc
