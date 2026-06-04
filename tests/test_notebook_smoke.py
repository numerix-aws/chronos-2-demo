"""End-to-end smoke test exercising the same call sequence as the headline notebook.

The notebook itself is committed but not executed in CI. This test mirrors the
notebook's logic against synthetic data so refactors break the test before
they break the demo.
"""
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.augmentation import blender, regime_detector
from chronos2_demo.data import regimes
from chronos2_demo.models import baseline_mc, chronos2_client
from chronos2_demo.pricing import book, exposure


def _synthetic_panel(n=600, seed=0):
    rng = np.random.default_rng(seed)
    cols = ["USDEUR", "USDJPY", "USDGBP",
            "USD_2Y", "USD_5Y", "USD_10Y",
            "EUR_2Y", "EUR_5Y", "EUR_10Y",
            "JPY_2Y", "JPY_5Y", "JPY_10Y",
            "GBP_2Y", "GBP_5Y", "GBP_10Y"]
    base = np.array([1.08, 0.0088, 1.35,
                     0.020, 0.025, 0.030,
                     0.000, 0.005, 0.010,
                     0.000, 0.000, 0.001,
                     0.010, 0.015, 0.020])
    raw = base + rng.normal(0, 0.001, size=(n, len(cols))).cumsum(axis=0) * 0.001
    return pd.DataFrame(raw, columns=cols,
                        index=pd.bdate_range("2020-01-02", periods=n))


class _FakeEndpoint:
    """AutoGluon endpoint stand-in: returns a long-format quantile DataFrame."""
    def predict(self, data, target, id_column, timestamp_column,
                prediction_length, known_covariates=None):
        items = list(dict.fromkeys(data[id_column]))
        future = pd.bdate_range("2022-07-01", periods=prediction_length)
        rows = []
        for item in items:
            for t in range(prediction_length):
                row = {id_column: item, timestamp_column: future[t], "mean": 1.0}
                for ql in chronos2_client.Q_LEVELS:
                    row[str(ql)] = 1.0 + (ql - 0.5) * 0.02
                rows.append(row)
        return pd.DataFrame(rows)


def _mock_chronos_client(n_paths, horizon, n_series):
    # The endpoint returns per-series quantiles; the client reconstructs paths.
    return chronos2_client.Chronos2Client(endpoint=_FakeEndpoint())


def test_full_pipeline_runs_end_to_end():
    panel = _synthetic_panel()
    as_of = "2022-01-03"
    horizon = 21
    n_paths = 100

    # 1. Regime snapshot at as_of.
    snap = regime_detector.current_w_stress(panel, as_of=as_of, window=20)
    assert 0.0 <= snap.w_stress <= 1.0

    # 2. Baseline parametric MC.
    par_paths = baseline_mc.simulate_baseline(
        panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
        n_components=3, seed=0,
    )
    assert par_paths.source == "parametric"
    assert par_paths.paths.shape == (n_paths, horizon, panel.shape[1])

    # 3. Chronos-2 (mocked endpoint).
    client = _mock_chronos_client(n_paths, horizon, panel.shape[1])
    chr_paths = chronos2_client.simulate_chronos2(
        client, panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
    )
    assert chr_paths.source == "chronos2"

    # 4. Compute portfolio MtM-driven tail score per engine for blending.
    book_swaps = book.load_book(book.DEFAULT_BOOK_PATH)
    par_mtm = exposure.portfolio_mtm(book_swaps, par_paths)
    chr_mtm = exposure.portfolio_mtm(book_swaps, chr_paths)
    par_terminal = par_mtm[:, -1]
    chr_terminal = chr_mtm[:, -1]

    # 5. Blend.
    blended = blender.blend_paths(
        par_paths, chr_paths, par_terminal, chr_terminal,
        w_stress=snap.w_stress,
    )
    assert blended.source == "blended"

    # 6. Compute baseline + augmented metrics.
    baseline_metrics = exposure.compute_metrics(book_swaps, par_paths)
    augmented_metrics = exposure.compute_metrics(book_swaps, blended)
    for m in (baseline_metrics, augmented_metrics):
        assert "ee" in m and "pfe_975" in m and "es_975" in m
        assert m["ee"].shape == (horizon,)
        assert m["pfe_975"].shape == (horizon,)
