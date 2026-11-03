from __future__ import annotations

import json
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


def read_trace_events(
    case_id: str | None = None,
    limit: int | None = None,
    trace_path: Path | None = None,
) -> list[TraceEvent]:
    """Read events in write order, optionally only those for one case. limit keeps the most recent N."""
    trace_file = trace_path or SETTINGS.trace_path
    if not trace_file.exists():
        return []
    events: list[TraceEvent] = []
    with trace_file.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            event = TraceEvent(**json.loads(line))
            if case_id is None or event.details.get("case_id") == case_id:
                events.append(event)
    return events[-limit:] if limit else events
