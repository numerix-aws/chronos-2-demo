import numpy as np
import pandas as pd
import pytest
from chronos2_demo.pricing import instruments as ins


def _levels():
    idx = pd.bdate_range("2022-07-01", periods=3)
    return pd.DataFrame(
        {"SPX": [4000.0, 4100.0, 3900.0],
         "USDJPY": [0.0072, 0.0072, 0.0072],
         "NIKKEI225": [28000.0, 28000.0, 28000.0],
         "US_IG_OAS": [1.20, 1.30, 1.50]},  # percent
        index=idx,
    )


def test_equity_forward_usd_quoted_pnl():
    lv = _levels()
    # K defaults to first level (4000); long 10 units.
    mtm = ins.value_equity_forward_path(
        ins.EquityForward(id="e1", index="SPX", quote_ccy="USD", strike=None,
                          notional=10.0, direction=1),
        lv, {"USD": None, "JPY": "USDJPY"},
    )
    assert mtm[0] == pytest.approx(0.0)
    assert mtm[1] == pytest.approx(10.0 * (4100.0 - 4000.0))
    assert mtm[2] == pytest.approx(10.0 * (3900.0 - 4000.0))


def test_equity_forward_fx_converts_when_not_usd():
    lv = _levels()
    mtm = ins.value_equity_forward_path(
        ins.EquityForward(id="e2", index="NIKKEI225", quote_ccy="JPY", strike=27000.0,
                          notional=2.0, direction=1),
        lv, {"USD": None, "JPY": "USDJPY"},
    )
    # (28000 - 27000) * 2 units * 0.0072 USD/JPY, constant across steps.
    assert mtm[0] == pytest.approx(2.0 * (28000.0 - 27000.0) * 0.0072)


def test_cds_protection_gains_as_spread_widens():
    lv = _levels()
    mtm = ins.value_cds_protection_path(
        ins.CDSProtection(id="c1", spread_series="US_IG_OAS", notional=1_000_000.0,
                          rpv01=4.5, direction=1),
        lv,
    )
    assert mtm[0] == pytest.approx(0.0)
    # (1.50% - 1.20%) / 100 * 1e6 * 4.5
    assert mtm[2] == pytest.approx((1.50 - 1.20) / 100.0 * 1_000_000.0 * 4.5)
    assert mtm[2] > mtm[1] > mtm[0]
