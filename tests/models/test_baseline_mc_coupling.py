import numpy as np
import pandas as pd
from chronos2_demo.models import baseline_mc


def test_simulated_cross_correlation_matches_empirical_sign():
    """When two series are positively correlated in history, simulated
    log-returns should also be positively correlated on average."""
    rng = np.random.default_rng(123)
    n = 800
    common = rng.normal(0, 0.01, size=n).cumsum()
    a = common + rng.normal(0, 0.001, size=n).cumsum()
    b = common + rng.normal(0, 0.001, size=n).cumsum()
    c = -common + rng.normal(0, 0.001, size=n).cumsum()
    panel = pd.DataFrame({"A": np.exp(a/100), "B": np.exp(b/100), "C": np.exp(c/100)},
                         index=pd.bdate_range("2020-01-02", periods=n))

    ps = baseline_mc.simulate_baseline(panel, "2022-01-03", 252, 2000, 3, seed=5)
    log_rets = np.diff(np.log(ps.paths), axis=1)  # (N, H-1, n_series)
    # Average correlation across paths.
    flat = log_rets.reshape(-1, log_rets.shape[-1])
    corr = np.corrcoef(flat.T)
    assert corr[0, 1] > 0.5    # A,B positively correlated
    assert corr[0, 2] < -0.3   # A,C negatively correlated
