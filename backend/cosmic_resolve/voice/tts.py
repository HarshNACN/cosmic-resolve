"""Text to speech with Piper, running in-process. piper-tts is imported lazily (it is an optional dependency).

Measured on the demo laptop: the voice loads in about 2.5 s once, then the first audio of a sentence takes about
0.04 s and a whole short sentence about 0.15 s. Audio is raw 16-bit mono PCM; the browser plays it as it arrives.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Iterator

from ..config import ROOT_DIR
from . import agent_config as cfg
from .llm import VoiceConfigError

DEFAULT_RATE = 22050


class PiperSpeaker:
    def __init__(self, voice_path: str | None = None, voice: Any | None = None) -> None:
        # A ready voice object can be injected (tests); otherwise load the file named by PIPER_VOICE.
        if voice is None:
            raw = (voice_path or os.environ.get(cfg.ENV_PIPER_VOICE, "")).strip()
            if not raw:
                raise VoiceConfigError(f"Set {cfg.ENV_PIPER_VOICE} to the path of a downloaded Piper voice (.onnx).")
            path = Path(raw)
            if not path.is_absolute():
                path = ROOT_DIR / path
            if not path.is_file():
                raise VoiceConfigError(
                    f"Piper voice not found at {path}. Download one with: python -m piper.download_voices en_US-lessac-medium"
                )
            try:
                from piper import PiperVoice  # lazy
            except ImportError as exc:  # pragma: no cover - depends on the install
                raise VoiceConfigError('piper-tts is not installed. Run: pip install -e "backend[voice]" (Python 3.11-3.13)') from exc
            voice = PiperVoice.load(str(path))
            # The very first synthesis pays a one-off cost (about 3 s measured). Pay it here, during warm-up, so the
            # greeting of the first call is not delayed by it.
            list(voice.synthesize("Hello."))
        self._voice = voice
        self._lock = threading.Lock()  # one synthesis at a time; each sentence takes well under a second

    def synthesize(self, text: str) -> Iterator[tuple[bytes, int]]:
        """Yield (raw PCM bytes, sample rate) for the text."""
        with self._lock:
            chunks = list(self._voice.synthesize(text))
        fallback = getattr(getattr(self._voice, "config", None), "sample_rate", DEFAULT_RATE)
        for chunk in chunks:
            yield chunk.audio_int16_bytes, getattr(chunk, "sample_rate", None) or fallback
