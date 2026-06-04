FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app
COPY tools/fargate/run_chronos2/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Plan A package + shared tool helpers.
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir -e .
COPY tools /app/tools

COPY tools/fargate/run_chronos2/entrypoint.py /app/entrypoint.py
ENV PYTHONPATH=/app
CMD ["python", "/app/entrypoint.py"]
