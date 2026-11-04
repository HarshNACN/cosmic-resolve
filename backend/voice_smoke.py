"""Pre-demo check for the voice call: runs a scripted call against the RUNNING backend and times every turn.

    python backend/voice_smoke.py                        # backend on http://127.0.0.1:8000
    python backend/voice_smoke.py --base http://localhost:5173/api   # through the Vite proxy, as the browser does
    python backend/voice_smoke.py --approve              # also approve the case, so the call hears the outcome

It speaks to the agent with Piper-generated audio (no microphone needed), so it checks the real chain: Groq speech to
text, Claude, Piper, the case hand-off and (with --approve) the checkpoint. --approve needs CHECKPOINT_WRITES_ENABLED
set in the backend's shell and executes the mock write actions. Exits 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

from cosmic_resolve.config import ROOT_DIR  # noqa: E402  (also loads .env)
from cosmic_resolve.voice import agent_config as cfg  # noqa: E402

CALL = [  # Jon Park's lost smart plug: the PRD's demo case 1
    ("pick the order", "The smart plug."),
    ("describe the issue", "It never arrived, and the tracking says it was lost in transit."),
    ("confirm", "Yes, that's right."),
]
FIRST_AUDIO_TARGET_SECONDS = 1.5

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def load_voice():
    import os

    from piper import PiperVoice

    raw = os.environ.get(cfg.ENV_PIPER_VOICE, "").strip()
    path = Path(raw) if raw else None
    if path is not None and not path.is_absolute():
        path = ROOT_DIR / path
    if path is None or not path.is_file():
        sys.exit(f"Set {cfg.ENV_PIPER_VOICE} to an installed Piper voice first (see docs/VOICE.md).")
    return PiperVoice.load(str(path))


def speech(voice, text: str) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return buffer.getvalue()


def timed(http: httpx.Client, method: str, url: str, **kwargs) -> dict:
    """Send a streaming request; report when each kind of event first arrived."""
    started = time.perf_counter()
    marks: dict[str, float] = {}
    lines: list[str] = []
    errors: list[str] = []
    case_id = None
    with http.stream(method, url, **kwargs) as response:
        if response.status_code != 200:
            return {"status": response.status_code, "detail": response.read().decode()[:200]}
        for raw in response.iter_lines():
            if not raw.strip():
                continue
            event = json.loads(raw)
            marks.setdefault(event["type"], time.perf_counter() - started)
            if event["type"] == "agent_sentence":
                lines.append(event["text"])
            elif event["type"] == "error":
                errors.append(event["message"])
            elif event["type"] == "case_created":
                case_id = event["case_id"]
    return {"status": 200, "marks": marks, "lines": lines, "errors": errors, "case_id": case_id,
            "total": time.perf_counter() - started}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="backend address (default %(default)s)")
    parser.add_argument("--caller", default="C-002", help="customer ID to call as (default %(default)s)")
    parser.add_argument("--approve", action="store_true", help="also approve the case and check the spoken outcome")
    args = parser.parse_args()

    voice = load_voice()
    with httpx.Client(timeout=90) as http:
        try:
            started = time.perf_counter()
            status = http.post(f"{args.base}/voice/warmup").json()
        except httpx.HTTPError as exc:
            sys.exit(f"Cannot reach the backend at {args.base}: {exc}. Is it running?")
        print(f"Setup ({time.perf_counter() - started:.1f}s; the first call after a backend start is the slowest)")
        check(status["stt"], "speech to text is configured")
        check(status["llm"], "the conversation model is configured")
        check(status["tts"], "the voice is configured")
        for problem in status["problems"]:
            print(f"      {problem}")
        if failures:
            return 1

        session = http.post(f"{args.base}/voice/sessions", json={"customer_id": args.caller})
        check(session.status_code == 200, f"a session opens for {args.caller}", session.text[:100] if session.status_code != 200 else "")
        if session.status_code != 200:
            return 1
        sid = session.json()["session_id"]

        print("The call (seconds from sending to first audio)")
        greeting = timed(http, "POST", f"{args.base}/voice/sessions/{sid}/speak", json={"kind": "greeting"})
        check("audio" in greeting.get("marks", {}), "the greeting is spoken", f"{greeting.get('marks', {}).get('audio', float('nan')):.2f}s")

        case_id = None
        for label, utterance in CALL:
            result = timed(http, "POST", f"{args.base}/voice/sessions/{sid}/turn",
                           files={"audio": ("speech.wav", speech(voice, utterance), "audio/wav")})
            first = result.get("marks", {}).get("audio")
            check(result["status"] == 200 and not result.get("errors") and first is not None, label,
                  f"first audio {first:.2f}s" if first is not None else str(result.get("errors") or result.get("detail")))
            if first is not None:
                check(first <= FIRST_AUDIO_TARGET_SECONDS, f"  {label}: fast enough (target {FIRST_AUDIO_TARGET_SECONDS}s)", f"{first:.2f}s")
            for line in result.get("lines", []):
                print(f"        agent: {line}")
            case_id = result.get("case_id") or case_id
        check(case_id is not None, "the confirmed call became a case", str(case_id))
        if case_id is None:
            return 1

        proposal = http.post(f"{args.base}/cases/{case_id}/propose").json()
        check(proposal["status"] == "AWAITING_APPROVAL", "the case can be proposed", f"{proposal['proposal']['decision']} ${proposal['proposal']['amount']}")

        if args.approve:
            decision = http.post(f"{args.base}/cases/{case_id}/decision", json={
                "action": "APPROVE", "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "voice_smoke"})
            check(decision.status_code == 200, "the checkpoint approves it", decision.text[:120] if decision.status_code != 200 else "")
            outcome = http.get(f"{args.base}/voice/sessions/{sid}").json()["outcome"]
            check(outcome is not None and outcome["status"] == "APPROVED", "the call learns the outcome", (outcome or {}).get("text", "")[:80])
            spoken = timed(http, "POST", f"{args.base}/voice/sessions/{sid}/speak", json={"kind": "outcome"})
            check("audio" in spoken.get("marks", {}), "the outcome is spoken", f"{spoken.get('marks', {}).get('audio', float('nan')):.2f}s")
        else:
            print("  (run with --approve to also test the checkpoint and the spoken outcome)")

    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
