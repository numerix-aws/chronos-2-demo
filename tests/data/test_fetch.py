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
