from pathlib import Path

import pandas as pd

from chronos2_demo import config
from chronos2_demo.models import baseline_mc
from chronos2_demo.pricing import book, exposure


SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "demo" / "demo-script.md"


def test_stage_safe_demo_prompt_has_nonzero_baseline_pfe():
    prompt = SCRIPT.read_text()
    assert "September 30, 2022" in prompt
    assert "one trading year into the future" in prompt
    assert "500 scenarios with each engine" in prompt

    panel = pd.read_parquet(config.DATA_CURATED / "panel.parquet")
    pathset = baseline_mc.simulate_baseline(
        panel,
        as_of="2022-09-30",
        horizon=252,
        n_paths=500,
        n_components=5,
        seed=0,
    )
    swaps, equities, cds = book.load_cross_asset_book(book.DEFAULT_BOOK_PATH)
    pfe = exposure.compute_metrics(
        swaps,
        pathset,
        equity_forwards=equities,
        cds_protection=cds,
    )["pfe_975"]

    assert pfe[-1] > 0.0
