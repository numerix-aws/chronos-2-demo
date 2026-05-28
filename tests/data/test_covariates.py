import pandas as pd
from unittest.mock import patch
from chronos2_demo.data import covariates


@patch("chronos2_demo.data.covariates._fetch_one")
def test_load_covariates_returns_aligned_frame(mock_fetch):
    idx = pd.bdate_range("2022-01-03", periods=10)
    mock_fetch.side_effect = [
        pd.Series(range(10), index=idx, name="VIX"),
        pd.Series(range(10), index=idx, name="MOVE"),
        pd.Series(range(10), index=idx, name="WTI"),
    ]
    df = covariates.load_covariates()
    assert list(df.columns) == ["MOVE", "VIX", "WTI"]  # alphabetical
    assert len(df) == 10
