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


def _fake_json_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_fred_series_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_json_response({
        "observations": [
            {"date": "2022-01-03", "value": "1.63"},
            {"date": "2022-01-04", "value": "1.66"},
            {"date": "2022-01-05", "value": "."},
        ]
    })
    s = fetch.fetch_fred_series("DGS10", api_key="fake")
    assert s.index[0] == pd.Timestamp("2022-01-03")
    assert s.iloc[0] == pytest.approx(1.63)
    assert len(s) == 2  # "." row dropped
    # uses the keyed JSON endpoint, passes api_key + observation_start
    args, kwargs = mock_get.call_args
    assert args[0] == fetch.FRED_CSV_URL
    assert kwargs["params"]["api_key"] == "fake"
    assert kwargs["params"]["file_type"] == "json"
    assert kwargs["params"]["observation_start"] == "2015-01-01"


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_ecb_fx_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_csv_response(
        "TIME_PERIOD,OBS_VALUE\n2022-01-03,1.1308\n2022-01-04,1.1290\n"
    )
    s = fetch.fetch_ecb_fx("EUR", "USD")
    assert len(s) == 2
    assert s.iloc[0] == pytest.approx(1.1308)
    assert mock_get.call_args.args[0].startswith(
        "https://data-api.ecb.europa.eu/service/data/EXR"
    )


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
