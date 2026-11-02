from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
EVALS_DIR = ROOT_DIR / "evals"
TRACE_DIR = ROOT_DIR / "traces"
DEFAULT_TRACE_PATH = TRACE_DIR / "mock_actions.jsonl"


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_dir: Path = Field(default_factory=lambda: DATA_DIR)
    evals_dir: Path = Field(default_factory=lambda: EVALS_DIR)
    trace_path: Path = Field(default_factory=lambda: DEFAULT_TRACE_PATH)
    default_market: str = "US"
    default_category: str = "GADGETS"
    default_case_type: str = "DAMAGED_ON_ARRIVAL"


SETTINGS = Settings()
