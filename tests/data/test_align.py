import numpy as np
import pandas as pd
import pytest
from chronos2_demo.data import align


def _series(dates, values, name):
    return pd.Series(values, index=pd.to_datetime(dates), name=name)


def test_align_panel_inner_joins_business_days():
    a = _series(["2022-01-03", "2022-01-04", "2022-01-05"], [1, 2, 3], "A")
    b = _series(["2022-01-04", "2022-01-05", "2022-01-06"], [10, 20, 30], "B")
    panel = align.align_panel([a, b])
    assert list(panel.columns) == ["A", "B"]
    assert list(panel.index.strftime("%Y-%m-%d")) == ["2022-01-04", "2022-01-05"]


def test_align_panel_drops_nan_rows():
    a = _series(["2022-01-03", "2022-01-04"], [1, np.nan], "A")
    b = _series(["2022-01-03", "2022-01-04"], [10, 20], "B")
    panel = align.align_panel([a, b])
    assert len(panel) == 1


def test_align_panel_rejects_duplicate_columns():
    a = _series(["2022-01-03"], [1], "A")
    b = _series(["2022-01-03"], [2], "A")
    with pytest.raises(ValueError, match="duplicate"):
        align.align_panel([a, b])


def test_slice_lookback_returns_n_business_days_before_as_of():
    panel = pd.DataFrame(
        {"A": range(10)},
        index=pd.bdate_range("2022-01-03", periods=10),
    )
    out = align.slice_lookback(panel, as_of="2022-01-12", lookback_days=5)
    assert len(out) == 5
    assert out.index[-1] == pd.Timestamp("2022-01-12")
