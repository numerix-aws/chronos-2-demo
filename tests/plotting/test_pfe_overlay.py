import matplotlib
matplotlib.use("Agg")  # headless
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.plotting import pfe_overlay as p


def _metrics(horizon=21, base=1.0, scale=1.0):
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    return {
        "ee":      np.linspace(0, 1, horizon) * base * scale,
        "pfe_975": np.linspace(0, 3, horizon) * base * scale,
        "es_975":  np.linspace(0, 4, horizon) * base * scale,
        "dates":   dates,
    }


def test_plot_pfe_overlay_returns_figure_with_two_lines():
    fig = p.plot_pfe_overlay(
        baseline=_metrics(scale=1.0),
        augmented=_metrics(scale=1.4),
        title="PFE overlay",
    )
    ax = fig.axes[0]
    labels = [l.get_label() for l in ax.get_lines()]
    assert "baseline" in labels
    assert "augmented" in labels
    assert ax.get_title() == "PFE overlay"


def test_plot_pfe_overlay_shades_gap_between_curves():
    fig = p.plot_pfe_overlay(
        baseline=_metrics(scale=1.0),
        augmented=_metrics(scale=1.4),
        title="x",
    )
    ax = fig.axes[0]
    # fill_between produces a PolyCollection
    from matplotlib.collections import PolyCollection
    has_fill = any(isinstance(c, PolyCollection) for c in ax.collections)
    assert has_fill


def test_plot_pfe_overlay_rejects_misaligned_dates():
    bad_metrics = _metrics(horizon=21)
    bad_metrics["dates"] = pd.bdate_range("2023-01-01", periods=21)
    with pytest.raises(ValueError, match="align"):
        p.plot_pfe_overlay(baseline=_metrics(), augmented=bad_metrics, title="x")
