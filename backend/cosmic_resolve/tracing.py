from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config
from .config import SETTINGS
from .models import TraceEvent


def append_trace_event(
    event_type: str,
    message: str,
    details: dict | None = None,
    trace_path: Path | None = None,
) -> TraceEvent:
    # On Vercel, /tmp is ephemeral and per-instance, so tracing is best-effort: a write failure is
    # dropped rather than failing the request. Locally a write failure still raises, as before.
    trace_file = trace_path or SETTINGS.trace_path
    event = TraceEvent.now(event_type=event_type, message=message, details=details or {})
    try:
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        with trace_file.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
    except OSError:
        if not config.ON_VERCEL:
            raise
    return event


def append_case_event(case_id: str, event_type: str, message: str, **details: Any) -> TraceEvent:
    """Trace event for one case. The case ID is stored in details so read_trace_events can filter on it."""
    return append_trace_event(event_type, message, {"case_id": case_id, **details})


def read_trace_events(
    case_id: str | None = None,
    limit: int | None = None,
    trace_path: Path | None = None,
) -> list[TraceEvent]:
    """Read events in write order, optionally only those for one case. limit keeps the most recent N."""
    trace_file = trace_path or SETTINGS.trace_path
    try:
        if not trace_file.exists():
            return []
        with trace_file.open(encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        # Missing or unreadable /tmp storage on Vercel means "no trace", not a server error.
        if config.ON_VERCEL:
            return []
        raise
    events: list[TraceEvent] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        event = TraceEvent(**json.loads(line))
        if case_id is None or event.details.get("case_id") == case_id:
            events.append(event)
    return events[-limit:] if limit else events
