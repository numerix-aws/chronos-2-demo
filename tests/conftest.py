"""Shared pytest fixtures for the chronos2_demo package."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def rng():
    """Deterministic RNG for reproducible tests."""
    return np.random.default_rng(seed=42)


@pytest.fixture
def fake_panel(rng):
    """Small joint FX+rates panel: 5 series, 250 daily obs."""
    dates = pd.bdate_range("2022-01-03", periods=250)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    data = rng.normal(0, 0.005, size=(250, 5)).cumsum(axis=0)
    return pd.DataFrame(data, index=dates, columns=cols)
