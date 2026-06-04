import io
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest
from chronos2_demo.data import fetch


def _fake_csv_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_fred_series_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_csv_response(
        "DATE,DGS10\n2022-01-03,1.63\n2022-01-04,1.66\n2022-01-05,.\n"
    )
    s = fetch.fetch_fred_series("DGS10", api_key="fake")
    assert s.index[0] == pd.Timestamp("2022-01-03")
    assert s.iloc[0] == pytest.approx(1.63)
    assert len(s) == 2  # missing "." rows dropped


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_ecb_fx_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_csv_response(
        "TIME_PERIOD,OBS_VALUE\n2022-01-03,1.1308\n2022-01-04,1.1290\n"
    )
    s = fetch.fetch_ecb_fx("EUR", "USD")
    assert len(s) == 2
    assert s.iloc[0] == pytest.approx(1.1308)


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_propagates_http_errors(mock_get):
    resp = MagicMock()
    resp.raise_for_status.side_effect = RuntimeError("boom")
    mock_get.return_value = resp
    with pytest.raises(RuntimeError):
        fetch.fetch_fred_series("DGS10", api_key="fake")


def test_fetch_credit_oas_maps_names_to_fred_ids(monkeypatch):
    from chronos2_demo.data import fetch
    captured = {}

    def fake_fred(series_id, api_key):
        captured["id"] = series_id
        import pandas as pd
        return pd.Series([1.2, 1.3], index=pd.to_datetime(["2022-06-01", "2022-06-02"]),
                         name=series_id)

    monkeypatch.setattr(fetch, "fetch_fred_series", fake_fred)
    s = fetch.fetch_credit_oas("US_IG_OAS", api_key="k")
    assert captured["id"] == "BAMLC0A0CM"
    assert s.name == "US_IG_OAS"
