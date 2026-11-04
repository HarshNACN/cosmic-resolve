"""Measure the voice pipeline per language. Run by hand, never by the test suite:

    python -m cosmic_resolve.voice.benchmark [--runs 8] [--no-llm] [--no-stt]

For each language it times, over several runs, the same three stages a spoken turn goes through:
    stt   Groq Whisper on a clip (Piper-generated speech, so the audio is clean and the numbers are a best case)
    llm   Bedrock Claude, time to the first complete sentence
    tts   Piper, time to the first audio chunk
and their sum, "first audio", which is what the caller waits for after they stop speaking. Piper is measured cold
(first synthesis after load) and warmed. Stages that are not configured are skipped and reported as such. The
numbers are printed, not stored: quote them with the date, the network and the machine they came from.
"""
from __future__ import annotations

import argparse
import io
import os
import statistics
import time
import wave
from typing import Any, Callable

from . import agent_config as cfg

# What a caller might say first in each language, and the sentence Cosmo might answer with.
UTTERANCES = {
    "en": "Hello, my smart plug never arrived and tracking says it was lost.",
    "es": "Hola, mi enchufe inteligente nunca llegó y el seguimiento dice que se perdió.",
    "pt": "Olá, minha tomada inteligente nunca chegou e o rastreamento diz que foi perdida.",
}
REPLIES = {"en": "I am so sorry that happened.", "es": "Lamento mucho lo que pasó.", "pt": "Sinto muito pelo que aconteceu."}


def summarize(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {"median": statistics.median(ordered), "p95": p95, "worst": ordered[-1], "n": float(len(ordered))}


def _timed(call: Callable[[], Any]) -> float:
    start = time.perf_counter()
    call()
    return time.perf_counter() - start


def _wav(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def _first_chunk(speaker: Any, text: str, language: str) -> float:
    start = time.perf_counter()
    next(iter(speaker.synthesize(text, language)))
    return time.perf_counter() - start


def run(runs: int, with_stt: bool, with_llm: bool) -> dict[str, Any]:
    os.environ.setdefault(cfg.ENV_MULTILINGUAL, "true")
    from .tts import PiperSpeaker

    report: dict[str, Any] = {"runs": runs, "languages": {}, "skipped": {}}
    started = time.perf_counter()
    speaker = PiperSpeaker()
    report["voice_load_seconds"] = time.perf_counter() - started
    report["voices"] = speaker.languages()
    report["voice_problems"] = dict(speaker.problems)

    stt = llm = None
    if with_stt:
        try:
            from .stt import GroqTranscriber

            stt = GroqTranscriber()
        except Exception as exc:  # noqa: BLE001
            report["skipped"]["stt"] = str(exc)
    if with_llm:
        try:
            from .llm import BedrockDialogueLLM

            llm = BedrockDialogueLLM()
            next(iter(llm.speak({"expecting": "DESCRIBE", "orders": [], "selected_order": None}, "Hello")), None)  # fails fast without credentials
        except Exception as exc:  # noqa: BLE001
            report["skipped"]["llm"] = str(exc)

    for language in cfg.LANGUAGES:
        if not speaker.available(language):
            report["languages"][language] = {"skipped": "no voice loaded"}
            continue
        row: dict[str, Any] = {}
        row["tts_first_chunk_warm"] = summarize([_first_chunk(speaker, REPLIES[language], language) for _ in range(runs)])

        clip = None
        if stt is not None:
            pcm, rate = b"", 22050
            for chunk, rate in speaker.synthesize(UTTERANCES[language], language):
                pcm += chunk
            clip = _wav(pcm, rate)
            row["stt"] = summarize([_timed(lambda: stt.transcribe_detailed(clip, "clip.wav", "audio/wav", hint="en")) for _ in range(runs)])

        if llm is not None:
            view = {"expecting": "DESCRIBE", "orders": [], "selected_order": None, "language": language}

            def first_sentence() -> None:
                next(iter(llm.speak(view, UTTERANCES[language])), None)

            row["llm_first_sentence"] = summarize([_timed(first_sentence) for _ in range(runs)])

        parts = [row[key]["median"] for key in ("stt", "llm_first_sentence", "tts_first_chunk_warm") if key in row]
        if len(parts) == 3:
            row["first_audio_median_estimate"] = sum(parts)
            row["first_audio_within_1_5s"] = sum(parts) <= 1.5
        report["languages"][language] = row
    return report


def _print(report: dict[str, Any]) -> None:
    print(f"Voices loaded in {report['voice_load_seconds']:.1f} s: {report['voices']}")
    for name, why in {**report["voice_problems"], **report["skipped"]}.items():
        print(f"  note ({name}): {why}")
    for language, row in report["languages"].items():
        print(f"\n[{language}]")
        for key, value in row.items():
            if isinstance(value, dict):
                print(f"  {key:24s} median {value['median']:.3f}s  p95 {value['p95']:.3f}s  worst {value['worst']:.3f}s  (n={int(value['n'])})")
            else:
                print(f"  {key:24s} {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--no-stt", action="store_true", help="skip the Groq Whisper stage")
    parser.add_argument("--no-llm", action="store_true", help="skip the Bedrock stage")
    args = parser.parse_args()
    _print(run(max(2, args.runs), not args.no_stt, not args.no_llm))


if __name__ == "__main__":
    main()
