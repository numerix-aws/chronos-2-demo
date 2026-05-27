"""Repo-wide paths and demo constants. Single source of truth."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_RAW = DATA_DIR / "raw"
DATA_CURATED = DATA_DIR / "curated"

FX_PAIRS = ["USDEUR", "USDJPY", "USDGBP", "USDCHF", "USDCAD"]
RATES_CCYS = ["USD", "EUR", "JPY", "GBP"]
RATES_TENORS = ["2Y", "5Y", "10Y"]
COVARIATES = ["VIX", "MOVE", "WTI"]

# Specific stress windows used in the demo. Pin these so the headline is reproducible.
STRESS_WINDOWS = [
    {"name": "2011_eur_sovereign", "start": "2011-07-01", "end": "2012-01-31"},
    {"name": "2015_chf_unpeg",     "start": "2015-01-01", "end": "2015-03-31"},
    {"name": "2020_covid",         "start": "2020-02-15", "end": "2020-05-31"},
    {"name": "2022_rate_hike",     "start": "2022-03-01", "end": "2022-11-30"},
]

DEFAULT_AS_OF = "2022-06-30"
DEFAULT_HORIZON_DAYS = 252
DEFAULT_N_PATHS = 5_000
DEFAULT_LOOKBACK_DAYS = 504  # ~2y
