import numpy as np
import pytest
from chronos2_demo.augmentation import blender as bl


def test_compute_weights_uniform_when_w_stress_zero():
    n = 1000
    pnl = np.random.default_rng(0).normal(size=n)
    w_par, w_chr = bl.compute_weights(pnl_parametric=pnl, pnl_chronos2=pnl,
                                      w_stress=0.0, body_chronos_share=0.1,
                                      tail_quantile=0.05)
    # In calm regimes: parametric ~ 0.9 in body and ~1.0 in tail; Chronos2 mirrors.
    assert np.isclose(w_par.sum() + w_chr.sum(), 2.0)  # one per engine
    assert (w_par > 0).all() and (w_chr >= 0).all()


def test_compute_weights_tail_swings_toward_chronos2_in_stress():
    rng = np.random.default_rng(0)
    n = 4000
    pnl = rng.normal(size=n)
    w_par_calm, w_chr_calm = bl.compute_weights(pnl, pnl, w_stress=0.0,
                                                body_chronos_share=0.1,
                                                tail_quantile=0.05)
    w_par_stress, w_chr_stress = bl.compute_weights(pnl, pnl, w_stress=1.0,
                                                    body_chronos_share=0.1,
                                                    tail_quantile=0.05)
    tail_mask = (pnl <= np.quantile(pnl, 0.05)) | (pnl >= np.quantile(pnl, 0.95))
    # Stress -> chronos2 weight in tail dominates parametric in tail.
    assert w_chr_stress[tail_mask].sum() > w_par_stress[tail_mask].sum() * 5
    # Calm -> opposite.
    assert w_par_calm[tail_mask].sum() > w_chr_calm[tail_mask].sum() * 5


def test_compute_weights_each_set_sums_to_one():
    rng = np.random.default_rng(0)
    pnl_par = rng.normal(size=2000)
    pnl_chr = rng.normal(size=2000)
    for w_stress in (0.0, 0.3, 0.7, 1.0):
        w_par, w_chr = bl.compute_weights(pnl_par, pnl_chr, w_stress=w_stress,
                                          body_chronos_share=0.1,
                                          tail_quantile=0.05)
        assert np.isclose(w_par.sum(), 1.0)
        assert np.isclose(w_chr.sum(), 1.0)


def test_compute_weights_rejects_invalid_inputs():
    pnl = np.zeros(10)
    with pytest.raises(ValueError):
        bl.compute_weights(pnl, pnl, w_stress=1.5,
                           body_chronos_share=0.1, tail_quantile=0.05)
    with pytest.raises(ValueError):
        bl.compute_weights(pnl, pnl, w_stress=0.5,
                           body_chronos_share=-0.1, tail_quantile=0.05)
    with pytest.raises(ValueError):
        bl.compute_weights(pnl, pnl, w_stress=0.5,
                           body_chronos_share=0.1, tail_quantile=0.6)
