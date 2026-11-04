"""Text to speech with Piper, running in-process. piper-tts is imported lazily (it is an optional dependency).

Measured on the demo laptop: a voice loads in about 2.5 s once, then the first audio of a sentence takes about
0.04 s and a whole short sentence about 0.15 s. Audio is raw 16-bit mono PCM; the browser plays it as it arrives.

English (PIPER_VOICE) is required. With VOICE_MULTILINGUAL on, Spanish (PIPER_VOICE_ES, es_MX) and Portuguese
(PIPER_VOICE_PT, pt_BR) and Hindi (PIPER_VOICE_HI, hi_IN) voices are loaded too, in parallel at startup and cached, never per sentence. A missing or
broken extra voice does not stop the app or English calls: it is recorded in `problems` so the page can say so.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

from ..config import ROOT_DIR
from . import agent_config as cfg
from .llm import VoiceConfigError

DEFAULT_RATE = 22050
# A short word in each language for the one-off warm-up synthesis a freshly loaded voice needs.
_WARMUP_TEXT = {"en": "Hello.", "es": "Hola.", "pt": "Olá.", "hi": "नमस्ते।"}
# Voices known to work, used in setup messages (see docs/VOICE.md for licences).
_SUGGESTED_VOICE = {"en": "en_US-lessac-medium", "es": "es_MX-ald-medium", "pt": "pt_BR-faber-medium", "hi": "hi_IN-pratham-medium"}


class VoiceUnavailable(RuntimeError):
    """No voice is loaded for the requested language."""


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT_DIR / path


def _load(path: Path, language: str) -> Any:
    try:
        from piper import PiperVoice  # lazy
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise VoiceConfigError('piper-tts is not installed. Run: pip install -e "backend[voice]" (Python 3.11-3.13)') from exc
    voice = PiperVoice.load(str(path))
    # The very first synthesis pays a one-off cost (about 3 s measured). Pay it here, during warm-up, so the first
    # sentence of the first call is not delayed by it.
    list(voice.synthesize(_WARMUP_TEXT.get(language, "Hello.")))
    return voice


class PiperSpeaker:
    def __init__(self, voice_path: str | None = None, voice: Any | None = None, voices: dict[str, Any] | None = None) -> None:
        """voice is a ready English voice object and voices a ready {language: voice} map (both for tests);
        otherwise English is loaded from voice_path or PIPER_VOICE, and extra languages from their own settings."""
        self.problems: dict[str, str] = {}
        self._voices: dict[str, Any] = {}
        from_environment = voice is None and voice_path is None
        if voice is None:
            raw = (voice_path or os.environ.get(cfg.ENV_PIPER_VOICE, "")).strip()
            if not raw:
                raise VoiceConfigError(f"Set {cfg.ENV_PIPER_VOICE} to the path of a downloaded Piper voice (.onnx).")
            path = _resolve(raw)
            if not path.is_file():
                raise VoiceConfigError(
                    f"Piper voice not found at {path}. Download one with: python -m piper.download_voices {_SUGGESTED_VOICE['en']}"
                )
            voice = _load(path, "en")
        self._voices["en"] = voice
        if voices:
            self._voices.update(voices)
        elif from_environment and cfg.multilingual_enabled():
            self._load_extra_languages()
        self._locks = {language: threading.Lock() for language in self._voices}  # one synthesis at a time per voice

    def _load_extra_languages(self) -> None:
        wanted: dict[str, Path] = {}
        for language in ("es", "pt", "hi"):
            setting = cfg.ENV_PIPER_VOICES[language]
            raw = os.environ.get(setting, "").strip()
            if not raw:
                self.problems[language] = f"Set {setting} to a {cfg.LOCALES[language]} Piper voice to hear Cosmo in {cfg.LANGUAGE_NAMES[language]}."
                continue
            path = _resolve(raw)
            if not path.is_file():
                self.problems[language] = (
                    f"The {cfg.LANGUAGE_NAMES[language]} voice was not found at {path}. "
                    f"Download one with: python -m piper.download_voices {_SUGGESTED_VOICE[language]}"
                )
                continue
            wanted[language] = path

        def load(item: tuple[str, Path]) -> tuple[str, Any, str | None]:
            language, path = item
            try:
                return language, _load(path, language), None
            except Exception as exc:  # noqa: BLE001 - a corrupt or unsupported voice must not stop English calls
                return language, None, f"The {cfg.LANGUAGE_NAMES[language]} voice could not be loaded: {exc}"

        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="piper-load") as pool:
            for language, loaded, problem in pool.map(load, wanted.items()):
                if loaded is not None:
                    self._voices[language] = loaded
                else:
                    self.problems[language] = problem or "voice unavailable"

    def available(self, language: str = cfg.DEFAULT_LANGUAGE) -> bool:
        return language in self._voices

    def languages(self) -> dict[str, bool]:
        """Which supported languages have a loaded voice."""
        return {language: language in self._voices for language in cfg.LANGUAGES}

    def synthesize(self, text: str, language: str = cfg.DEFAULT_LANGUAGE) -> Iterator[tuple[bytes, int]]:
        """Yield (raw PCM bytes, sample rate) for the text, spoken by the language's voice."""
        voice = self._voices.get(language)
        if voice is None:
            raise VoiceUnavailable(f"No {cfg.LANGUAGE_NAMES.get(language, language)} voice is loaded.")
        with self._locks[language]:
            chunks = list(voice.synthesize(text))
        fallback = getattr(getattr(voice, "config", None), "sample_rate", DEFAULT_RATE)
        for chunk in chunks:
            yield chunk.audio_int16_bytes, getattr(chunk, "sample_rate", None) or fallback
