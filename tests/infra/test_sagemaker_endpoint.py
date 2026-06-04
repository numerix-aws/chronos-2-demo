from unittest.mock import MagicMock
import pytest
from chronos2_demo.infra import sagemaker_endpoint as se


def test_deploy_kwargs_serverless_default():
    kw = se.build_deploy_kwargs()
    assert kw["inference_mode"] == "serverless"
    # serverless is CPU/auto-managed: no instance_type forced.
    assert "instance_type" not in kw


def test_deploy_kwargs_realtime_sets_instance_type():
    kw = se.build_deploy_kwargs(mode="realtime", instance_type="ml.g5.xlarge")
    assert kw["instance_type"] == "ml.g5.xlarge"
    assert "inference_mode" not in kw  # realtime is the SDK default mode


def test_deploy_demo_endpoint_serverless_caches_then_deploys():
    fake_endpoint = MagicMock()
    fake_endpoint.endpoint_name = "chronos2-demo-ep"
    cached = MagicMock()
    cached.deploy.return_value = fake_endpoint
    model = MagicMock()
    model.cache_model_artifact.return_value = cached
    factory = MagicMock(return_value=model)

    name = se.deploy_demo_endpoint(
        endpoint_name="chronos2-demo-ep",
        cache_uri="s3://bkt/fm-cache",
        model_factory=factory,
    )

    assert name == "chronos2-demo-ep"
    factory.assert_called_once_with(model_id="chronos-2")
    model.cache_model_artifact.assert_called_once_with("s3://bkt/fm-cache")
    assert cached.deploy.call_args.kwargs["inference_mode"] == "serverless"


def test_deploy_demo_endpoint_realtime_skips_cache():
    fake_endpoint = MagicMock()
    fake_endpoint.endpoint_name = "chronos2-demo-ep"
    model = MagicMock()
    model.deploy.return_value = fake_endpoint
    factory = MagicMock(return_value=model)

    name = se.deploy_demo_endpoint(
        endpoint_name="chronos2-demo-ep", mode="realtime",
        instance_type="ml.g5.xlarge", model_factory=factory)

    assert name == "chronos2-demo-ep"
    model.cache_model_artifact.assert_not_called()
    assert model.deploy.call_args.kwargs["instance_type"] == "ml.g5.xlarge"


def test_delete_demo_endpoint_calls_endpoint_delete():
    ep = MagicMock()
    se.delete_demo_endpoint(endpoint_name="chronos2-demo-ep",
                            endpoint_factory=lambda endpoint_name: ep)
    ep.delete_endpoint.assert_called_once()


def test_open_endpoint_attaches_by_name():
    ep = MagicMock()
    factory = MagicMock(return_value=ep)
    got = se.open_endpoint("chronos2-demo-ep", endpoint_factory=factory)
    assert got is ep
    factory.assert_called_once_with(endpoint_name="chronos2-demo-ep")
