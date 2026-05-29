import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.plotting import regime_ribbon as p


def test_regime_ribbon_renders_with_w_stress_line_and_threshold_shading():
    idx = pd.bdate_range("2022-01-03", periods=100)
    w = pd.Series(np.linspace(0.1, 0.9, 100), index=idx, name="w_stress")
    fig = p.plot_regime_ribbon(w, threshold=0.7, title="regime")
    ax = fig.axes[0]
    assert ax.get_title() == "regime"
    assert any(l.get_label() == "w_stress" for l in ax.get_lines())
    # Threshold line drawn somewhere as a second line.
    assert sum(1 for l in ax.get_lines()) >= 2


def test_regime_ribbon_shades_stress_windows():
    idx = pd.bdate_range("2022-01-03", periods=50)
    arr = np.array([0.2] * 20 + [0.9] * 15 + [0.2] * 15)
    w = pd.Series(arr, index=idx, name="w_stress")
    fig = p.plot_regime_ribbon(w, threshold=0.7, title="x")
    ax = fig.axes[0]
    from matplotlib.patches import Rectangle
    fills = [c for c in ax.patches if isinstance(c, Rectangle)]
    assert len(fills) >= 1


def test_regime_ribbon_rejects_unindexed_input():
    arr = np.linspace(0, 1, 50)
    with pytest.raises(TypeError):
        p.plot_regime_ribbon(arr, threshold=0.7, title="x")
