import numpy as np
import pandas as pd
from chronos2_demo.models import baseline_mc


def _flat_panel(n=600, k=4, seed=0):
    rng = np.random.default_rng(seed)
    raw = rng.normal(0, 0.005, size=(n, k)).cumsum(axis=0) + 1.0
    return pd.DataFrame(raw, columns=[f"S{i}" for i in range(k)],
                        index=pd.bdate_range("2020-01-02", periods=n))


def test_factor_dynamics_estimates_phi_in_unit_interval():
    panel = _flat_panel()
    pca = baseline_mc.fit_pca(panel, n_components=3)
    dyn = baseline_mc.fit_factor_dynamics(panel, pca)
    assert dyn.phi.shape == (3,)
    assert (np.abs(dyn.phi) < 1.0).all()
    assert (dyn.sigma > 0).all()


def test_sample_factor_paths_shape_and_finiteness():
    panel = _flat_panel()
    pca = baseline_mc.fit_pca(panel, n_components=3)
    dyn = baseline_mc.fit_factor_dynamics(panel, pca)
    paths = baseline_mc._sample_factor_paths(
        dyn, n_paths=100, horizon=63, rng=np.random.default_rng(7)
    )
    assert paths.shape == (100, 63, 3)
    assert np.isfinite(paths).all()


def test_sample_factor_paths_variance_grows_with_horizon():
    panel = _flat_panel()
    pca = baseline_mc.fit_pca(panel, n_components=3)
    dyn = baseline_mc.fit_factor_dynamics(panel, pca)
    paths = baseline_mc._sample_factor_paths(
        dyn, n_paths=2000, horizon=252, rng=np.random.default_rng(11)
    )
    # _sample_factor_paths returns stationary AR(1) increments; variance grows
    # with horizon only after cumulation (as simulate_baseline does in level space).
    cum = np.cumsum(paths, axis=1)
    var_t10 = cum[:, 10, :].var(axis=0).sum()
    var_t250 = cum[:, 250, :].var(axis=0).sum()
    assert var_t250 > var_t10 * 5
