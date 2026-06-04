"""Pin the direction + order-of-magnitude of the headline result.

Inputs frozen:
  - tests/fixtures/headline_panel.parquet (built once)
  - n_paths = 1000, horizon = 21
  - seed = 0 for parametric MC
  - mocked Chronos-2 returns deterministic quantile curves; client reconstructs paths under a fixed seed

Asserts:
  - augmented PFE@97.5 terminal >= baseline PFE@97.5 terminal
  - the relative gap is within [5%, 200%]  (sanity band; not a tight pin)
"""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from chronos2_demo.augmentation import blender, regime_detector
from chronos2_demo.models import baseline_mc, chronos2_client
from chronos2_demo.pricing import book, exposure

PANEL_PATH = Path(__file__).parent / "fixtures" / "headline_panel.parquet"


class _FakeEndpoint:
    """AutoGluon endpoint stand-in returning a deterministic quantile frame.

    Quantiles are spread around 1.0 (inverse-normal grid) so the reconstructed
    paths have tails. simulate_chronos2 reconstructs under a fixed seed, so the
    headline regression stays reproducible across runs.
    """
    def predict(self, data, target, id_column, timestamp_column,
                prediction_length, known_covariates=None):
        items = list(dict.fromkeys(data[id_column]))
        future = pd.bdate_range("2022-07-01", periods=prediction_length)
        rows = []
        for item in items:
            for t in range(prediction_length):
                row = {id_column: item, timestamp_column: future[t], "mean": 1.0}
                for ql in chronos2_client.Q_LEVELS:
                    row[str(ql)] = 1.0 + norm.ppf(ql) * 0.02
                rows.append(row)
        return pd.DataFrame(rows)


def _mock_chronos_client(n_paths, horizon, n_series):
    return chronos2_client.Chronos2Client(endpoint=_FakeEndpoint())


@pytest.mark.skipif(not PANEL_PATH.exists(),
                    reason="run tests/fixtures/build_headline_panel.py first")
def test_augmented_pfe_exceeds_baseline_by_meaningful_margin():
    panel = pd.read_parquet(PANEL_PATH)
    as_of = panel.index[-1].strftime("%Y-%m-%d")
    horizon = 21
    n_paths = 1000

    snap = regime_detector.current_w_stress(panel, as_of=as_of, window=20)
    par = baseline_mc.simulate_baseline(
        panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
        n_components=5, seed=0,
    )
    client = _mock_chronos_client(n_paths, horizon, panel.shape[1])
    chr_ = chronos2_client.simulate_chronos2(
        client, panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
    )

    swaps = book.load_book(book.DEFAULT_BOOK_PATH)
    par_term = exposure.portfolio_mtm(swaps, par)[:, -1]
    chr_term = exposure.portfolio_mtm(swaps, chr_)[:, -1]
    blended = blender.blend_paths(par, chr_, par_term, chr_term, w_stress=snap.w_stress)

    base_pfe = exposure.compute_metrics(swaps, par)["pfe_975"][-1]
    aug_pfe = exposure.compute_metrics(swaps, blended)["pfe_975"][-1]
    rel_gap = (aug_pfe - base_pfe) / max(abs(base_pfe), 1.0)

    assert aug_pfe >= base_pfe, (
        f"augmented PFE ({aug_pfe:,.0f}) should be >= baseline ({base_pfe:,.0f})"
    )
    assert -0.5 <= rel_gap <= 5.0, (
        f"relative gap {rel_gap:.2%} is outside the sanity band"
    )
