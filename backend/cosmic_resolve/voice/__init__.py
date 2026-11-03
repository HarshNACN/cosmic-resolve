"""Customer voice intake: a spoken conversation that hands a confirmed case to the existing resolution loop.

Everything here is a channel in front of the existing flow. The conversation never decides an outcome; the
resolution still comes from the deterministic provider and a human approves it at the checkpoint.
Optional dependencies (httpx, piper-tts) are imported lazily so the rest of the backend never needs them.
"""
