"""Joint path-sample fan chart for a single series."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
from chronos2_demo.types import PathSet


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def plot_path_fan(
    pathset: PathSet,
    series: str,
    n_path_samples: int,
    title: str,
    q_low: float = 0.05,
    q_high: float = 0.95,
) -> "plt.Figure":
    if series not in pathset.series:
        raise KeyError(f"unknown series {series!r}")
    j = pathset.series.index(series)
    paths_s = pathset.paths[:, :, j]  # (n_paths, horizon)
    horizon = paths_s.shape[1]

    n_show = min(n_path_samples, paths_s.shape[0])
    sample_idx = np.linspace(0, paths_s.shape[0] - 1, n_show).astype(int)

    lo = np.array([_weighted_quantile(paths_s[:, t], pathset.weights, q_low)
                   for t in range(horizon)])
    hi = np.array([_weighted_quantile(paths_s[:, t], pathset.weights, q_high)
                   for t in range(horizon)])

    fig, ax = plt.subplots(figsize=(8, 4))
    for i in sample_idx:
        ax.plot(pathset.dates, paths_s[i], color="gray", alpha=0.25,
                linewidth=0.5, label="_path")
    ax.fill_between(pathset.dates, lo, hi, color="tab:blue", alpha=0.2,
                    label=f"[{int(q_low*100)}%, {int(q_high*100)}%]")
    ax.set_title(title)
    ax.set_xlabel("date")
    ax.set_ylabel(series)
    ax.legend(loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
