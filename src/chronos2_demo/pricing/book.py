"""Sample XCCY swap book schema + loader.

Schema is intentionally minimal:
- pay leg in pay_ccy, fixed-notional, single-tenor proxy at the swap rate.
- receive leg mirror in receive_ccy.
- spot_at_inception captures the FX peg locking par on day 0.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

from chronos2_demo import config

DEFAULT_BOOK_PATH = config.REPO_ROOT / "data" / "sample_book.json"


@dataclass(frozen=True)
class XCCYSwap:
    id: str
    pay_ccy: str
    pay_tenor: str
    pay_notional: float
    receive_ccy: str
    receive_tenor: str
    receive_notional: float
    spot_at_inception_quote_per_base: float
    trade_date: str
    maturity_date: str

    @classmethod
    def from_dict(cls, d: dict) -> "XCCYSwap":
        return cls(**d)


def load_book(path: Path | str = DEFAULT_BOOK_PATH) -> list[XCCYSwap]:
    payload = json.loads(Path(path).read_text())
    return [XCCYSwap.from_dict(s) for s in payload["swaps"]]
