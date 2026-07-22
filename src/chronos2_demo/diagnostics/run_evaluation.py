from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from chronos2_demo.augmentation.blender import blend_paths, compute_weights
from chronos2_demo.diagnostics.coverage import band_coverage, regime_conditional_coverage
from chronos2_demo.execution import scenario_role
from chronos2_demo.pricing.exposure import compute_metrics, portfolio_mtm
from chronos2_demo.types import PathSet


BookParts = tuple[Sequence[object], Sequence[object], Sequence[object]]


def _mtm(book: BookParts, paths: PathSet) -> np.ndarray:
    swaps, equity_forwards, cds_protection = book
    return portfolio_mtm(
        swaps, paths, equity_forwards=equity_forwards, cds_protection=cds_protection
    )


def _metrics(book: BookParts, paths: PathSet, alpha: float) -> dict[str, object]:
    swaps, equity_forwards, cds_protection = book
    values = compute_metrics(
        swaps,
        paths,
        q=alpha,
        equity_forwards=equity_forwards,
        cds_protection=cds_protection,
    )
    terminal = {
        "date": values["dates"][-1].strftime("%Y-%m-%d"),
        "ee": float(values["ee"][-1]),
        "pfe_975": float(values["pfe_975"][-1]),
        "es_975": float(values["es_975"][-1]),
    }
    return {"profiles": values, "terminal": terminal}


def _weighted(paths: PathSet, weights: np.ndarray, source: str | None = None) -> PathSet:
    normalized = np.asarray(weights, dtype=float)
    normalized /= normalized.sum()
    return PathSet(
        paths=paths.paths,
        weights=normalized,
        series=list(paths.series),
        dates=paths.dates,
        source=source or paths.source,
    )


def _component_role(paths: PathSet) -> str:
    role = scenario_role(paths.source)
    return "baseline_component" if role == "baseline" else "chronos_component"


def compute_attribution(
    book: BookParts,
    parametric: PathSet,
    chronos: PathSet,
    *,
    w_stress: float,
    alpha: float = 0.975,
) -> dict[str, dict[str, object]]:
    uniform_parametric = _weighted(parametric, np.ones(parametric.n_paths))
    uniform_chronos = _weighted(chronos, np.ones(chronos.n_paths))
    pnl_parametric = _mtm(book, uniform_parametric)[:, -1]
    pnl_chronos = _mtm(book, uniform_chronos)[:, -1]
    weights_parametric, weights_chronos = compute_weights(
        pnl_parametric, pnl_chronos, w_stress=w_stress
    )
    reweighted_parametric = _weighted(parametric, weights_parametric)
    reweighted_chronos = _weighted(chronos, weights_chronos)
    final_blend = blend_paths(
        uniform_parametric,
        uniform_chronos,
        pnl_parametric,
        pnl_chronos,
        w_stress=w_stress,
    )
    distributions = {
        "uniform_parametric": uniform_parametric,
        "uniform_chronos": uniform_chronos,
        "reweighted_parametric": reweighted_parametric,
        "reweighted_chronos": reweighted_chronos,
        "final_blend": final_blend,
    }
    roles = {
        "uniform_parametric": scenario_role(uniform_parametric.source),
        "uniform_chronos": scenario_role(uniform_chronos.source),
        "reweighted_parametric": _component_role(reweighted_parametric),
        "reweighted_chronos": _component_role(reweighted_chronos),
        "final_blend": scenario_role(final_blend.source),
    }
    report = {
        name: {"terminal": _metrics(book, paths, alpha)["terminal"]}
        for name, paths in distributions.items()
    }
    baseline_pfe = float(report["uniform_parametric"]["terminal"]["pfe_975"])
    for name, values in report.items():
        terminal = values["terminal"]
        delta = float(terminal["pfe_975"]) - baseline_pfe
        values["scenario_role"] = roles[name]
        values["delta_pfe_975"] = delta
        values["delta_pfe_975_pct"] = (
            None if baseline_pfe == 0.0 else delta / baseline_pfe * 100.0
        )
    return report


def _coverage_ready(distributions: Mapping[str, PathSet], realized: pd.DataFrame) -> str | None:
    if not distributions:
        return "no model distributions were supplied"
    reference = next(iter(distributions.values()))
    if len(realized) != reference.horizon:
        return f"realized horizon has {len(realized)} of {reference.horizon} required observations"
    if not realized.index.equals(reference.dates):
        return "realized dates do not match the forecast horizon"
    if list(realized.columns) != reference.series:
        return "realized series do not match the modeled panel"
    if realized.isna().any(axis=None):
        return "realized horizon contains missing market observations"
    return None


def compute_portfolio_coverage(
    book: BookParts,
    distributions: Mapping[str, PathSet],
    realized_panel: pd.DataFrame,
    *,
    alpha: float = 0.975,
) -> dict[str, object]:
    reason = _coverage_ready(distributions, realized_panel)
    if reason:
        return {"available": False, "reason": reason}
    realized_path = PathSet(
        paths=realized_panel.to_numpy(dtype=float)[None, :, :],
        weights=np.array([1.0]),
        series=list(realized_panel.columns),
        dates=realized_panel.index,
        source="parametric",
    )
    realized_exposure = np.maximum(_mtm(book, realized_path)[0], 0.0)
    results: dict[str, object] = {}
    for name, paths in distributions.items():
        pfe = np.asarray(_metrics(book, paths, alpha)["profiles"]["pfe_975"], dtype=float)
        breach = realized_exposure > pfe
        magnitude = np.where(breach, realized_exposure - pfe, 0.0)
        results[name] = {
            "coverage": float((~breach).mean()),
            "nominal": alpha,
            "distance_from_nominal": float(abs((~breach).mean() - alpha)),
            "breach_count": int(breach.sum()),
            "average_breach": float(magnitude[breach].mean()) if breach.any() else 0.0,
            "maximum_breach": float(magnitude.max()),
        }
    return {"available": True, "results": results}


def compute_factor_coverage(
    distributions: Mapping[str, PathSet],
    realized_panel: pd.DataFrame,
    realized_regimes: pd.DataFrame,
    *,
    regime_threshold: float,
) -> dict[str, object]:
    reason = _coverage_ready(distributions, realized_panel)
    if reason:
        return {"available": False, "reason": reason}
    if "w_stress" not in realized_regimes or not realized_regimes.index.equals(
        realized_panel.index
    ):
        return {
            "available": False,
            "reason": "realized regimes do not match the forecast horizon",
        }
    results: dict[str, object] = {}

    def json_series(values: pd.Series) -> dict[str, float | None]:
        return {
            key: None if pd.isna(value) else float(value)
            for key, value in values.items()
        }

    for name, paths in distributions.items():
        per_series = band_coverage(paths, realized_panel, q_low=0.025, q_high=0.975)
        conditional = regime_conditional_coverage(
            paths,
            realized_panel,
            realized_regimes["w_stress"],
            q_low=0.025,
            q_high=0.975,
            stress_threshold=regime_threshold,
        )
        overall = float(per_series.mean())
        results[name] = {
            "coverage": overall,
            "nominal": 0.95,
            "distance_from_nominal": abs(overall - 0.95),
            "per_series": json_series(per_series),
            "calm": json_series(conditional["calm"]),
            "stress": json_series(conditional["stress"]),
        }
    return {"available": True, "results": results}
