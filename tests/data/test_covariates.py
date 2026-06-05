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


def test_fetch_one_move_uses_yahoo(monkeypatch):
    from chronos2_demo.data import covariates, fetch
    calls = {}
    monkeypatch.setattr(fetch, "fetch_yahoo_series",
                        lambda sym: _named(sym))
    monkeypatch.setattr(fetch, "fetch_fred_series",
                        lambda series_id, api_key: _named(series_id))

    def _named(name):
        import pandas as pd
        return pd.Series([1.0], index=pd.to_datetime(["2022-01-03"]), name=name)

    move = covariates._fetch_one("MOVE", api_key="k")
    vix = covariates._fetch_one("VIX", api_key="k")
    assert move.name == "MOVE"      # came from Yahoo ^MOVE, renamed
    assert vix.name == "VIX"        # came from FRED VIXCLS, renamed
