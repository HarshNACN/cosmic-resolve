# cosmic-resolve

APEX Cohort 3 Hackathon – Cosmic Resolve

## Repository Structure

```
cosmic-resolve/
├── backend/              # Python FastAPI backend
│   ├── cosmic_resolve/   # Main Python package
│   ├── api.py           # FastAPI application entry point (uvicorn api:app)
│   └── pyproject.toml   # Python project configuration
├── landing/             # Landing page at "/" (React + Vite, dev port 5173; the single local address)
├── frontend/            # Internal case workbench at /internal/ (dev port 5175)
├── customer-frontend/   # Customer support portal at /support/ (dev port 5174)
├── data/                # Synthetic/mocked Cosmic Mart data fixtures
├── evals/               # Evaluation assets and test cases
├── tests/               # Integration and unit tests
├── docs/                # Documentation and reference materials
├── CLAUDE.md            # Project guidelines and architecture
├── README.md            # This file
├── .gitignore           # Git ignore rules
└── .env.example         # Environment variables template
```

## Technology Stack

- **Backend:** FastAPI (Python)
- **Frontend:** React + Vite
- **Model Provider:** AWS Bedrock (Claude)
- **Development:** Claude Code

## Project Status

Working offline loop plus a live Bedrock provider (Claude Sonnet 5.5). Every write is mock-only and approval-gated.

**Implemented:**
- Deterministic read tools and approval-gated write tools over JSON fixtures (`backend/cosmic_resolve/tools.py`)
- Proposal validator: clause citation, $200 escalation threshold, goodwill caps (`validators.py`)
- End-to-end loop: propose, validate, human checkpoint, gated writes, trace (`workflow.py`)
- Two providers: offline rule-based, and Bedrock (`model_provider.py`, `bedrock_provider.py`)
- JSONL trace logging (`tracing.py`)
- Pytest suite (49 tests, no network needed)

**Not yet implemented:** real evaluation harness (T20), full 30-case eval set (T19), FastAPI endpoints and trace API, React frontend, expanded fixtures (T08).

## Getting Started

- To test the system, follow **[docs/TESTING.md](docs/TESTING.md)**.
- Tool contracts: [docs/tools.md](docs/tools.md). Project guidelines: `CLAUDE.md`.
- AWS/Bedrock setup values: `.env.example`.
