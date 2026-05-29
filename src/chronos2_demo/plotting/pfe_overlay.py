"""PFE overlay: baseline vs augmented across horizon, with gap shading.

Inputs are the dicts returned by `pricing.exposure.compute_metrics`:
  {"ee": ndarray, "pfe_975": ndarray, "es_975": ndarray, "dates": DatetimeIndex}
"""
from __future__ import annotations
import matplotlib.pyplot as plt
import pandas as pd


def plot_pfe_overlay(
    baseline: dict,
    augmented: dict,
    title: str,
    metric: str = "pfe_975",
) -> "plt.Figure":
    if not pd.DatetimeIndex(baseline["dates"]).equals(pd.DatetimeIndex(augmented["dates"])):
        raise ValueError("baseline and augmented dates must align")
    dates = pd.DatetimeIndex(baseline["dates"])
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(dates, baseline[metric], label="baseline", color="tab:blue")
    ax.plot(dates, augmented[metric], label="augmented", color="tab:orange")
    ax.fill_between(dates, baseline[metric], augmented[metric],
                    color="tab:orange", alpha=0.15)
    ax.set_title(title)
    ax.set_xlabel("date")
    ax.set_ylabel(metric)
    ax.legend(loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
