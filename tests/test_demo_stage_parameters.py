import re
from pathlib import Path

import pandas as pd

from chronos2_demo import config
from chronos2_demo.models import baseline_mc
from chronos2_demo.pricing import book, exposure


SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "demo" / "demo-first-presenter-script.md"


def _prompt_value(prompt: str, name: str) -> str:
    match = re.search(rf"{name}=([0-9-]+)", prompt)
    assert match, f"missing {name} in demo prompt"
    return match.group(1)


def test_stage_safe_demo_prompt_has_nonzero_baseline_pfe():
    prompt = SCRIPT.read_text()
    as_of = _prompt_value(prompt, "as_of_date")
    horizon = int(_prompt_value(prompt, "horizon"))
    n_paths = int(_prompt_value(prompt, "n_paths"))

    panel = pd.read_parquet(config.DATA_CURATED / "panel.parquet")
    pathset = baseline_mc.simulate_baseline(
        panel,
        as_of=as_of,
        horizon=horizon,
        n_paths=n_paths,
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
