from chronos2_demo import config


def test_data_paths_are_relative_to_repo():
    assert config.DATA_RAW.name == "raw"
    assert config.DATA_CURATED.name == "curated"
    assert config.DATA_RAW.parent.name == "data"


def test_factor_universe_listed():
    fx = set(config.FX_PAIRS)
    assert {"USDEUR", "USDJPY", "USDGBP", "USDCHF", "USDCAD"} == fx
    rates_keys = set(config.RATES_TENORS)
    assert {"2Y", "5Y", "10Y"} == rates_keys
    rates_ccys = set(config.RATES_CCYS)
    assert {"USD", "EUR", "JPY", "GBP"} == rates_ccys


def test_covariates_listed():
    assert set(config.COVARIATES) == {"VIX", "MOVE", "WTI"}


def test_stress_windows_present():
    names = {w["name"] for w in config.STRESS_WINDOWS}
    assert "2022_rate_hike" in names
    assert "2020_covid" in names


def test_equity_and_credit_factor_universe():
    from chronos2_demo import config
    assert config.EQUITY_INDICES == ["SPX", "NIKKEI225"]
    assert config.CREDIT_SPREADS == ["US_IG_OAS", "US_HY_OAS"]
    # No overlap with FX / rates / covariates.
    overlap = set(config.EQUITY_INDICES + config.CREDIT_SPREADS) & (
        set(config.FX_PAIRS) | set(config.COVARIATES)
    )
    assert overlap == set()
