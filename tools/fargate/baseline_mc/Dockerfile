FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY tools/fargate/baseline_mc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# chronos2_demo source + the lambda shared shim
COPY src/chronos2_demo /app/chronos2_demo
COPY tools/lambda/shared /app/tools/lambda_/shared
COPY tools/__init__.py /app/tools/__init__.py
RUN mkdir -p /app/tools/lambda_ && touch /app/tools/lambda_/__init__.py

COPY tools/fargate/baseline_mc/entrypoint.py /app/entrypoint.py

ENV PYTHONPATH=/app

CMD ["python", "/app/entrypoint.py"]
