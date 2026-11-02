# cosmic-resolve

APEX Cohort 3 Hackathon – Cosmic Resolve

## Repository Structure

```
cosmic-resolve/
├── backend/              # Python FastAPI backend
│   ├── cosmic_resolve/   # Main Python package
│   ├── app.py           # FastAPI application entry point
│   └── pyproject.toml   # Python project configuration
├── frontend/            # React + Vite frontend (placeholder)
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

This is a Day 1 scaffolding repository aligned with T05 requirements.

**Currently available (scaffolding/starter code):**
- Clean directory structure for backend and frontend separation
- Synthetic data fixtures (JSON: customers, orders, products, shipments, policies, etc.)
- Starter models and validation logic
- Starter trace logging
- Pytest-based test suite (not currently runnable without dependency install)

**Planned - not yet implemented:**
- FastAPI endpoints in backend/
- React + Vite frontend in frontend/
- Evaluation framework
- AI agent implementation
- AWS Bedrock integration
- Live policy decision engine

**Note:** No dependencies installed. No live API calls. No UI. Frontend is an empty placeholder.

## Getting Started

Refer to `CLAUDE.md` for detailed project guidelines and architecture decisions.
