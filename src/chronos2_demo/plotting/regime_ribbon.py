"""Regime ribbon strip — w_stress over time with threshold shading."""
from __future__ import annotations
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_regime_ribbon(
    w_stress: pd.Series,
    threshold: float,
    title: str,
) -> "plt.Figure":
    if not isinstance(w_stress, pd.Series):
        raise TypeError("w_stress must be a pandas Series indexed by date")
    fig, ax = plt.subplots(figsize=(8, 1.6))
    ax.plot(w_stress.index, w_stress.values, color="tab:purple", label="w_stress")
    ax.axhline(threshold, color="black", linestyle="--", linewidth=0.8,
               label=f"threshold={threshold}")
    # Shade contiguous stress runs.
    above = (w_stress.values >= threshold).astype(int)
    if above.any():
        boundaries = np.diff(np.concatenate([[0], above, [0]]))
        starts = np.where(boundaries == 1)[0]
        ends = np.where(boundaries == -1)[0]
        for s, e in zip(starts, ends):
            ax.axvspan(w_stress.index[s], w_stress.index[min(e, len(w_stress) - 1)],
                       color="tab:red", alpha=0.15)
    ax.set_ylim(0, 1)
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
