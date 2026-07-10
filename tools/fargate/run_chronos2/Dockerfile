FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app
COPY tools/fargate/run_chronos2/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Plan A package + shared tool helpers.
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir -e .
COPY tools /app/tools
# tools/lambda_/ in the repo is an empty test-time shim (conftest aliases it to
# tools/lambda/); overlay the real shared package so
# `tools.lambda_.shared.s3_io` resolves at runtime (mirrors baseline_mc).
COPY tools/lambda/shared /app/tools/lambda_/shared

COPY tools/fargate/run_chronos2/entrypoint.py /app/entrypoint.py
ENV PYTHONPATH=/app
CMD ["python", "/app/entrypoint.py"]
