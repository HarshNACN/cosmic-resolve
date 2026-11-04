"""Development-only diagnostics for the voice call. Off unless VOICE_DEBUG is set to true; never logs keys or audio.

    VOICE_DEBUG=true python -m uvicorn api:app --port 8000

prints one JSON line per event to stderr, prefixed [voice-debug]: the language the session is using before a spoken turn,
the language hint and fields sent to Groq, what Groq reported (language and raw text), the final transcript that goes to
the page, and the language after the turn. Transcripts are customer words, so keep this off outside local debugging.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

ENV_DEBUG = "VOICE_DEBUG"
_TRUE = {"1", "true", "yes", "on"}
_NEVER = {"api_key", "authorization", "key", "audio", "file"}  # belt and braces: these field names are never printed


def enabled() -> bool:
    return os.environ.get(ENV_DEBUG, "").strip().lower() in _TRUE


def log(event: str, **fields: Any) -> None:
    if not enabled():
        return
    safe = {name: value for name, value in fields.items() if name.lower() not in _NEVER}
    print("[voice-debug] " + json.dumps({"event": event, **safe}, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
