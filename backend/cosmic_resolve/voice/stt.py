"""Speech to text through Groq's OpenAI-compatible Whisper endpoint. httpx is imported lazily.

Measured on the demo laptop: about 0.19 s for a 4-5 second clip. Free-tier limits are per organization (reported as
20 requests/minute and 2,000/day for whisper-large-v3-turbo; verify in the Groq console). The key is read from the
environment only and is never logged or returned to the browser.

With VOICE_MULTILINGUAL on, no language is forced: Whisper auto-detects and reports it (verbose_json returns the
spelled-out name, for example "Spanish"). Measured: full sentences are detected correctly and auto-detect adds no
measurable time, but one-word answers are not ("Sí" -> English, Danish or "See you"; "Sim" -> Russian). So a clip
whose language is unsupported, or that is only one or two words and disagrees with the call's current language, is
transcribed a second time with the current language as a hint (about 0.2 s, only in those uncertain cases).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from . import agent_config as cfg
from .languages import fold, normalize_language
from .llm import VoiceConfigError

TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Whisper is known to invent short phrases from silence or noise. A clip that yields only one of these is treated as nothing.
_NOISE_PHRASES = {
    "thank you", "thanks", "thanks for watching", "thank you for watching", "you", "bye", "okay", "mm", "hmm", "uh", "um",
    "gracias", "muchas gracias", "gracias por ver el video", "subtitulos realizados por la comunidad de amaraorg",
    "obrigado", "obrigada", "tchau", "legendas pela comunidade amaraorg",
}
SHORT_CLIP_WORDS = 2


class TranscriptionError(RuntimeError):
    """The speech service failed or refused (network, rate limit, bad audio)."""


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str | None  # en, es or pt; None when unknown or unsupported (and always None with multilingual off)
    hinted: bool = False  # True when the text came from the retry that forced the call's current language


def is_probably_noise(text: str) -> bool:
    cleaned = re.sub(r"[^a-z' ]", "", fold(text)).strip()
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

    def _post(self, audio: bytes, filename: str, content_type: str, fields: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._client.post(
                TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (filename, audio, content_type)},
                data={"model": self.model, "temperature": "0", **fields},
            )
        except Exception as exc:  # noqa: BLE001 - connection, timeout
            raise TranscriptionError("Could not reach the speech service.") from exc
        if response.status_code == 429:
            raise TranscriptionError("The speech service is busy. Please try again in a moment.")
        if response.status_code != 200:
            raise TranscriptionError(f"The speech service returned an error ({response.status_code}).")
        try:
            body = response.json()
        except ValueError as exc:
            raise TranscriptionError("The speech service returned an unreadable reply.") from exc
        return body if isinstance(body, dict) else {}

    def transcribe_detailed(
        self, audio: bytes, filename: str = "speech.webm", content_type: str = "audio/webm", hint: str | None = None
    ) -> Transcription:
        """The text and, with multilingual calls on, the detected language. hint is the call's current language."""
        if not cfg.multilingual_enabled():
            body = self._post(audio, filename, content_type, {"response_format": "json", "language": "en"})
            return Transcription(str(body.get("text", "")).strip(), None)

        body = self._post(audio, filename, content_type, {"response_format": "verbose_json"})
        text = str(body.get("text", "")).strip()
        detected = normalize_language(body.get("language"))
        short = len(text.split()) <= SHORT_CLIP_WORDS
        # Retry with the call's language when the detected one is unsupported, or when a short clip disagrees with a
        # Spanish/Portuguese call (where one-word answers get mis-heard as English). Never re-force English over a
        # short clip detected as Spanish or Portuguese: that is probably a real "sí" or "sim".
        if hint in cfg.LANGUAGES and (detected is None or (short and detected != hint and hint != cfg.DEFAULT_LANGUAGE)):
            retry = self._post(audio, filename, content_type, {"response_format": "json", "language": hint})
            return Transcription(str(retry.get("text", "")).strip(), hint, hinted=True)
        return Transcription(text, detected)

    def transcribe(self, audio: bytes, filename: str = "speech.webm", content_type: str = "audio/webm") -> str:
        return self.transcribe_detailed(audio, filename, content_type).text
