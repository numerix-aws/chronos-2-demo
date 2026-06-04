"""Chronos-2 deploy/teardown via AutoGluon Cloud.

The real amazon/chronos-2 model is deployed with
autogluon.cloud.TimeSeriesFoundationModel(model_id="chronos-2"). Serverless is
the demo default (CPU, scales to zero between demos). All AutoGluon-touching
calls go through injected factories so the config/orchestration shaping is
testable without importing autogluon-cloud or calling AWS. The real factories
(which import autogluon.cloud) are resolved only on the live path.
"""
from __future__ import annotations
from typing import Any, Callable, Optional

DEFAULT_MODEL_ID = "chronos-2"
DEFAULT_INSTANCE_TYPE = "ml.g5.xlarge"   # used only for mode="realtime"
DEFAULT_ENDPOINT_NAME = "chronos2-demo-ep"
DEFAULT_MODE = "serverless"


def build_deploy_kwargs(
    mode: str = DEFAULT_MODE,
    instance_type: str = DEFAULT_INSTANCE_TYPE,
) -> dict[str, Any]:
    """Shape the kwargs passed to AutoGluon's deploy() for the given mode."""
    if mode == "serverless":
        return {"inference_mode": "serverless"}
    if mode == "realtime":
        return {"instance_type": instance_type}
    raise ValueError(f"unknown mode {mode!r} (expected 'serverless' or 'realtime')")


def _default_model_factory(**kwargs: Any) -> Any:  # pragma: no cover - real path
    from autogluon.cloud import TimeSeriesFoundationModel
    return TimeSeriesFoundationModel(**kwargs)


def _default_endpoint_factory(**kwargs: Any) -> Any:  # pragma: no cover - real path
    from autogluon.cloud import TimeSeriesEndpoint
    return TimeSeriesEndpoint(**kwargs)


def deploy_demo_endpoint(
    endpoint_name: str = DEFAULT_ENDPOINT_NAME,
    mode: str = DEFAULT_MODE,
    instance_type: str = DEFAULT_INSTANCE_TYPE,
    cache_uri: Optional[str] = None,
    model_factory: Optional[Callable[..., Any]] = None,
) -> str:
    """Deploy the Chronos-2 endpoint via AutoGluon Cloud; return its name.

    Serverless requires the artifact be pre-cached to S3 (cache_uri); realtime
    deploys the model directly on a GPU instance. `model_factory` is injected
    in tests; defaults to autogluon.cloud.TimeSeriesFoundationModel.
    """
    model_factory = model_factory or _default_model_factory
    model = model_factory(model_id=DEFAULT_MODEL_ID)
    deploy_kwargs = build_deploy_kwargs(mode=mode, instance_type=instance_type)
    if mode == "serverless":
        target = model.cache_model_artifact(cache_uri)
    else:
        target = model
    endpoint = target.deploy(endpoint_name=endpoint_name, **deploy_kwargs)
    return endpoint.endpoint_name


def delete_demo_endpoint(
    endpoint_name: str = DEFAULT_ENDPOINT_NAME,
    endpoint_factory: Optional[Callable[..., Any]] = None,
) -> None:
    """Attach to the named endpoint and delete it."""
    endpoint_factory = endpoint_factory or (
        lambda endpoint_name: _default_endpoint_factory(endpoint_name=endpoint_name)
    )
    endpoint = endpoint_factory(endpoint_name=endpoint_name)
    endpoint.delete_endpoint()


def open_endpoint(
    endpoint_name: str = DEFAULT_ENDPOINT_NAME,
    endpoint_factory: Optional[Callable[..., Any]] = None,
) -> Any:
    """Return a live AutoGluon endpoint handle for an existing endpoint.

    This is the single place the Chronos2Client's injected `endpoint` comes
    from in production (deploy script + Fargate run_chronos2 task). It exposes
    `.predict(data, target, id_column, timestamp_column, prediction_length,
    known_covariates)`.
    """
    endpoint_factory = endpoint_factory or _default_endpoint_factory
    return endpoint_factory(endpoint_name=endpoint_name)
