import numpy as np
import pandas as pd
import pytest
from chronos2_demo.models import chronos2_client as c2


def _panel():
    idx = pd.bdate_range("2022-01-03", periods=20)
    return pd.DataFrame(
        np.arange(20 * 3).reshape(20, 3) + 1.0,
        index=idx,
        columns=["A", "B", "C"],
    )


def test_build_request_frame_long_format():
    panel = _panel()
    frame, known = c2.build_request_frame(panel, horizon=10, covariates=None,
                                          conditioning=None)
    # Long format: 20 rows x 3 series = 60 rows; required columns present.
    assert set(["item_id", "timestamp", "target"]).issubset(frame.columns)
    assert len(frame) == 60
    assert sorted(frame["item_id"].unique()) == ["A", "B", "C"]
    a_rows = frame[frame["item_id"] == "A"].sort_values("timestamp")
    assert a_rows["target"].tolist() == panel["A"].tolist()
    assert known is None


def test_build_request_frame_includes_covariates():
    panel = _panel()
    cov = pd.DataFrame(np.zeros((20, 2)) + 0.5, index=panel.index,
                       columns=["VIX", "MOVE"])
    frame, known = c2.build_request_frame(panel, horizon=10, covariates=cov,
                                          conditioning=None)
    assert "VIX" in frame.columns and "MOVE" in frame.columns
    assert (frame["VIX"] == 0.5).all()


def test_build_request_frame_rejects_misaligned_covariates():
    panel = _panel()
    cov = pd.DataFrame(np.zeros((19, 2)), index=panel.index[:19],
                       columns=["VIX", "MOVE"])
    with pytest.raises(ValueError, match="align"):
        c2.build_request_frame(panel, horizon=10, covariates=cov,
                               conditioning=None)


def test_build_request_frame_encodes_conditioning_as_known_covariate():
    panel = _panel()
    cond = c2.Conditioning(series_shifts={"A": 0.1}, n_anchor_days=3)
    frame, known = c2.build_request_frame(panel, horizon=10, covariates=None,
                                          conditioning=cond)
    # Known-covariate frame carries the per-series anchor over the horizon.
    assert known is not None
    a_future = known[known["item_id"] == "A"]
    assert len(a_future) == 10
    assert (a_future["anchor"].head(3) == 0.1).all()
    assert (a_future["anchor"].iloc[3:] == 0.0).all()


def test_build_request_frame_anchor_present_in_history_when_conditioning():
    # Chronos-2 rejects requests whose future covariates are not a subset of
    # the past covariates, so a conditional request must carry `anchor` (as
    # zeros -- no shift in the past) in the history frame too.
    panel = _panel()
    cov = pd.DataFrame(np.zeros((20, 2)) + 0.5, index=panel.index,
                       columns=["VIX", "MOVE"])
    cond = c2.Conditioning(series_shifts={"A": 0.1}, n_anchor_days=3)
    frame, known = c2.build_request_frame(panel, horizon=10, covariates=cov,
                                          conditioning=cond)
    past_covariates = set(frame.columns) - {"item_id", "timestamp", "target"}
    future_covariates = set(known.columns) - {"item_id", "timestamp"}
    assert future_covariates <= past_covariates
    assert (frame["anchor"] == 0.0).all()


def test_decode_response_returns_quantile_block():
    # AutoGluon long-format quantile frame: 2 series x horizon 4.
    rows = []
    ts = pd.bdate_range("2022-02-01", periods=4)
    for s, item in enumerate(["A", "B"]):
        for t in range(4):
            row = {"item_id": item, "timestamp": ts[t], "mean": float(s)}
            for ql in c2.Q_LEVELS:
                row[str(ql)] = float(s) + ql
            rows.append(row)
    frame = pd.DataFrame(rows)
    q_levels, Q = c2.decode_response(frame, series=["A", "B"])
    assert q_levels == c2.Q_LEVELS
    assert Q.shape == (2, 4, len(c2.Q_LEVELS))
    j90 = c2.Q_LEVELS.index(0.9)
    assert np.allclose(Q[1, :, j90], 1.9)


def test_decode_response_rejects_missing_quantile_columns():
    frame = pd.DataFrame({"item_id": ["A"], "timestamp": [pd.Timestamp("2022-02-01")],
                          "mean": [1.0]})
    with pytest.raises(KeyError):
        c2.decode_response(frame, series=["A"])
