# CLAUDE.md

This repository is a starter implementation for the Cosmic Resolve hackathon prototype.

## Mission

Create a small, deterministic, testable base architecture that models the trust boundaries described in the PRD:

- deterministic read tools backed by JSON fixtures,
- policy-cited resolution proposals,
- explicit approval gating for every write,
- trace logging for auditability,
- evaluation cases and fixtures,
- clear validation logic.

## Guardrails

- No live AWS or Bedrock calls in the starter repo.
- No hardcoded secrets or model IDs in source.
- Keep the architecture simple and understandable for a hackathon team.
- Do not build the final live UI or loop yet.
- Prefer deterministic code and explicit validation over cleverness.
