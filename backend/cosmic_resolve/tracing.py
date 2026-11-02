from __future__ import annotations

from pathlib import Path

from .config import SETTINGS
from .models import TraceEvent


def append_trace_event(
    event_type: str,
    message: str,
    details: dict | None = None,
    trace_path: Path | None = None,
) -> TraceEvent:
    trace_file = trace_path or SETTINGS.trace_path
    trace_file.parent.mkdir(parents=True, exist_ok=True)

    event = TraceEvent.now(event_type=event_type, message=message, details=details or {})
    with trace_file.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json())
        handle.write("\n")
    return event
