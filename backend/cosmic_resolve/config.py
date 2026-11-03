from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# Load <repo>/.env (git-ignored) if present. Variables already set in the shell win.
load_dotenv(ROOT_DIR / ".env", override=False)
DATA_DIR = ROOT_DIR / "data"
EVALS_DIR = ROOT_DIR / "evals"
TRACE_DIR = ROOT_DIR / "traces"
DEFAULT_TRACE_PATH = TRACE_DIR / "mock_actions.jsonl"

# Flat human-approval threshold for all loyalty tiers (PRD decision #1).
ESCALATION_THRESHOLD_USD = 200.0

# Maximum GOODWILL_CREDIT per loyalty tier, enforced in code (PRD decision #2).
# Illustrative placeholders until the Data lead's policy book (T09) sets the final caps.
GOODWILL_CAPS_USD: dict[str, float] = {
    "BRONZE": 5.0,
    "SILVER": 10.0,
    "GOLD": 20.0,
    "PLATINUM": 40.0,
}


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_dir: Path = Field(default_factory=lambda: DATA_DIR)
    evals_dir: Path = Field(default_factory=lambda: EVALS_DIR)
    trace_path: Path = Field(default_factory=lambda: DEFAULT_TRACE_PATH)
    default_market: str = "US"
    default_category: str = "GADGETS"
    default_case_type: str = "DAMAGED_ON_ARRIVAL"


SETTINGS = Settings()
