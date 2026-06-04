import json
import pytest
from pathlib import Path
from chronos2_demo.pricing import book as bk


def test_xccy_swap_schema_required_fields(tmp_path):
    swap = {
        "id": "xccy_001",
        "pay_ccy": "EUR",
        "pay_tenor": "5Y",
        "pay_notional": 10_000_000,
        "receive_ccy": "USD",
        "receive_tenor": "5Y",
        "receive_notional": 10_800_000,
        "spot_at_inception_quote_per_base": 1.08,
        "trade_date": "2022-01-03",
        "maturity_date": "2027-01-03",
    }
    parsed = bk.XCCYSwap.from_dict(swap)
    assert parsed.id == "xccy_001"
    assert parsed.pay_ccy == "EUR"
    assert parsed.receive_ccy == "USD"


def test_load_book_reads_json_into_typed_swaps():
    payload = {"swaps": [
        {"id": "a", "pay_ccy": "EUR", "pay_tenor": "5Y", "pay_notional": 1.0,
         "receive_ccy": "USD", "receive_tenor": "5Y", "receive_notional": 1.08,
         "spot_at_inception_quote_per_base": 1.08,
         "trade_date": "2022-01-03", "maturity_date": "2027-01-03"},
        {"id": "b", "pay_ccy": "JPY", "pay_tenor": "10Y", "pay_notional": 1_000_000.0,
         "receive_ccy": "USD", "receive_tenor": "10Y", "receive_notional": 9000.0,
         "spot_at_inception_quote_per_base": 0.009,
         "trade_date": "2022-01-03", "maturity_date": "2032-01-03"},
    ]}
    path = Path("/tmp/_test_book.json")
    path.write_text(json.dumps(payload))
    swaps = bk.load_book(path)
    assert len(swaps) == 2
    assert swaps[0].id == "a"
    assert swaps[1].pay_ccy == "JPY"


def test_default_demo_book_loads():
    swaps = bk.load_book(bk.DEFAULT_BOOK_PATH)
    assert len(swaps) >= 8
    ccy_pairs = {(s.pay_ccy, s.receive_ccy) for s in swaps}
    assert ("EUR", "USD") in ccy_pairs
    assert ("JPY", "USD") in ccy_pairs


def test_load_book_parses_cross_asset_instruments():
    from chronos2_demo.pricing import book as bk
    swaps, equities, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    assert len(swaps) >= 8
    assert len(equities) >= 1
    assert len(cds) >= 1
    assert equities[0].index in {"SPX", "NIKKEI225"}
    assert cds[0].spread_series in {"US_IG_OAS", "US_HY_OAS"}
