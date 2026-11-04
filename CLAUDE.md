# CLAUDE.md

This repository is the Cosmic Resolve hackathon prototype.

## Mission

Create a small, deterministic, testable base architecture that models the trust boundaries described in the PRD:

- deterministic read tools backed by JSON fixtures,
- policy-cited resolution proposals,
- explicit approval gating for every write,
- trace logging for auditability,
- evaluation cases and fixtures,
- clear validation logic.

## Guardrails

- Tests never make live AWS or Bedrock calls. Live runs happen only through the eval scripts.
- No hardcoded secrets or model IDs in source.
- Keep the architecture simple and understandable for a hackathon team.
- The model-driven agent loop is in scope. Build it and test it offline with scripted providers.
- Do not build the final live UI yet.
- Prefer deterministic code and explicit validation over cleverness.
