"""Run headline calibration through the canonical quantitative pipeline."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import uuid

import pandas as pd

from chronos2_demo import config
from chronos2_demo.augmentation import blender
from chronos2_demo.data import regimes as data_regimes
from chronos2_demo.diagnostics.run_evaluation import (
    compute_attribution,
    compute_factor_coverage,
    compute_portfolio_coverage,
)
from chronos2_demo.execution import aligned_run_inputs
from chronos2_demo.infra import sagemaker_endpoint
from chronos2_demo.models import baseline_mc, chronos2_client
from chronos2_demo.pricing import book as bk, exposure
from chronos2_demo.run_spec import (
    Clarification,
    canonical_run_payload,
    compile_run_spec,
)


OUT = config.REPO_ROOT / "docs" / "results" / "headline_calibration.json"
PROFILE_PROMPTS = {
    "stage_safe_headline_v1": "Run the stage-safe headline demo.",
}
REQUIRED_PROVENANCE_KEYS = frozenset({
    "market_snapshot_id",
    "market_sha256",
    "covariate_snapshot_id",
    "covariate_sha256",
    "chronos_endpoint",
    "chronos_model_version",
    "baseline_image_digest",
    "chronos_image_digest",
    "agent_image_digest",
    "book_version",
    "blend_version",
    "pricing_version",
    "tool_bundle_version",
    "strands_version",
})
CANONICAL_BOOK_ID = "cross_asset_demo_v1"


def _validate_provenance(provenance: object) -> dict[str, str]:
    if not isinstance(provenance, dict):
        raise ValueError("deployment provenance must be a JSON object")
    missing = sorted(REQUIRED_PROVENANCE_KEYS - provenance.keys())
    invalid = sorted(
        key
        for key, value in provenance.items()
        if not isinstance(key, str)
        or not isinstance(value, str)
        or not value.strip()
    )
    if missing or invalid:
        raise ValueError(
            f"deployment provenance is incomplete or empty: "
            f"missing={missing}, invalid={invalid}"
        )
    return dict(provenance)


def _normalized_market_panel(panel: pd.DataFrame) -> pd.DataFrame:
    normalized = panel.copy()
    normalized.index = pd.DatetimeIndex(
        pd.to_datetime(normalized.index)
    ).normalize()
    if normalized.index.has_duplicates:
        raise ValueError("market snapshot index contains duplicate dates")
    return normalized.sort_index()


def _verify_complete_held_out_dates(
    future_panel: pd.DataFrame,
    distributions: dict[str, object],
    *,
    horizon: int,
) -> None:
    if len(future_panel) != horizon:
        return
    for role, paths in distributions.items():
        if not future_panel.index.equals(pd.DatetimeIndex(paths.dates)):
            raise ValueError(
                f"complete held-out dates do not match {role} forecast dates"
            )


def run_calibration(
    *,
    prompt: str,
    provenance: dict[str, str],
    panel: pd.DataFrame,
    covariates: pd.DataFrame,
    endpoint: object,
    execution_id: str,
) -> dict[str, object]:
    provenance = _validate_provenance(provenance)
    spec = compile_run_spec(
        prompt, provenance=provenance, execution_id=execution_id
    )
    if isinstance(spec, Clarification):
        raise ValueError(spec.message)
    if (
        spec.book_id != provenance["book_version"]
        or provenance["book_version"] != CANONICAL_BOOK_ID
    ):
        raise ValueError(
            "RunSpec book identity does not authorize the canonical book"
        )
    panel = _normalized_market_panel(panel)
    inputs = aligned_run_inputs(
        panel,
        covariates,
        as_of_date=spec.as_of_date,
        lookback_days=spec.lookback_days,
    )
    parametric = baseline_mc.simulate_baseline(
        inputs.panel,
        as_of=spec.as_of_date,
        horizon=spec.horizon,
        n_paths=spec.n_paths,
        n_components=spec.baseline_components,
        seed=spec.baseline_seed,
    )
    conditioning = None
    if spec.conditioning:
        conditioning = chronos2_client.Conditioning(
            series_shifts={
                key: float(value)
                for key, value in spec.conditioning["series_shifts"].items()
            },
            n_anchor_days=int(spec.conditioning["n_anchor_days"]),
        )
    chronos = chronos2_client.simulate_chronos2(
        chronos2_client.Chronos2Client(endpoint=endpoint),
        panel=inputs.panel,
        as_of=spec.as_of_date,
        horizon=spec.horizon,
        n_paths=spec.n_paths,
        lookback_days=spec.lookback_days,
        covariates=inputs.covariates,
        conditioning=conditioning,
        seed=spec.chronos_seed,
    )
    book = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    swaps, equity_forwards, cds_protection = book
    parametric_pnl = exposure.portfolio_mtm(
        swaps,
        parametric,
        equity_forwards=equity_forwards,
        cds_protection=cds_protection,
    )[:, -1]
    chronos_pnl = exposure.portfolio_mtm(
        swaps,
        chronos,
        equity_forwards=equity_forwards,
        cds_protection=cds_protection,
    )[:, -1]
    augmented = blender.blend_paths(
        parametric,
        chronos,
        parametric_pnl,
        chronos_pnl,
        w_stress=spec.w_stress,
    )
    distributions = {
        "baseline": parametric,
        "chronos_only": chronos,
        "augmented": augmented,
    }
    as_of = pd.Timestamp(spec.as_of_date).normalize()
    future_panel = panel.loc[panel.index > as_of].head(spec.horizon).copy()
    _verify_complete_held_out_dates(
        future_panel,
        distributions,
        horizon=spec.horizon,
    )
    full_regimes = pd.DataFrame({
        "w_stress": data_regimes.w_stress_series(panel),
        "regime": data_regimes.label_regimes(
            panel, threshold=spec.regime_threshold
        ),
    })
    future_regimes = full_regimes.reindex(future_panel.index)
    terminal_metrics = {}
    for role, paths in distributions.items():
        values = exposure.compute_metrics(
            swaps,
            paths,
            q=0.975,
            equity_forwards=equity_forwards,
            cds_protection=cds_protection,
        )
        terminal_metrics[role] = {
            "date": values["dates"][-1].strftime("%Y-%m-%d"),
            "ee": float(values["ee"][-1]),
            "pfe_975": float(values["pfe_975"][-1]),
            "es_975": float(values["es_975"][-1]),
        }
    run_spec = canonical_run_payload(spec)
    run_spec.update({
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
    })
    return {
        "run_spec": run_spec,
        "inputs": {
            "panel_rows": len(inputs.panel),
            "covariate_rows": len(inputs.covariates),
        },
        "terminal_metrics": terminal_metrics,
        "diagnostics": {
            "attribution": compute_attribution(
                book, parametric, chronos, w_stress=spec.w_stress
            ),
            "portfolio_coverage": compute_portfolio_coverage(
                book, distributions, future_panel
            ),
            "factor_coverage": compute_factor_coverage(
                distributions,
                future_panel,
                future_regimes,
                regime_threshold=spec.regime_threshold,
            ),
        },
    }


def _load_provenance(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text())
    return _validate_provenance(payload)


def _load_verified_parquet(
    path: Path,
    *,
    expected_hash: str,
    label: str,
) -> pd.DataFrame:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError(f"{label} snapshot content hash mismatch")
    try:
        return pd.read_parquet(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError(f"{label} snapshot parquet decode failed: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    request = parser.add_mutually_exclusive_group(required=True)
    request.add_argument("--profile", choices=sorted(PROFILE_PROMPTS))
    request.add_argument("--prompt")
    parser.add_argument("--execution-id")
    parser.add_argument("--provenance-file", type=Path, required=True)
    args = parser.parse_args(argv)

    provenance = _load_provenance(args.provenance_file)
    panel = _load_verified_parquet(
        config.DATA_CURATED / "panel.parquet",
        expected_hash=provenance["market_sha256"],
        label="market",
    )
    covariates = _load_verified_parquet(
        config.DATA_CURATED / "covariates.parquet",
        expected_hash=provenance["covariate_sha256"],
        label="covariate",
    )
    endpoint = sagemaker_endpoint.open_endpoint(provenance["chronos_endpoint"])
    artifact = run_calibration(
        prompt=args.prompt or PROFILE_PROMPTS[args.profile],
        provenance=provenance,
        panel=panel,
        covariates=covariates,
        endpoint=endpoint,
        execution_id=args.execution_id or uuid.uuid4().hex,
    )
    encoded = json.dumps(
        artifact,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    OUT.write_text(encoded + "\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
