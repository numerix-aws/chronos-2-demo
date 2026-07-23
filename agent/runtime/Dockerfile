FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY agent/runtime/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY agent/runtime/agent.py /app/agent.py
COPY agent/runtime/events.py /app/events.py
COPY agent/runtime/workflow.py /app/workflow.py
COPY agent/system_prompt.md /app/system_prompt.md
RUN mkdir -p /app/chronos2_demo
COPY src/chronos2_demo/__init__.py /app/chronos2_demo/__init__.py
COPY src/chronos2_demo/run_spec.py /app/chronos2_demo/run_spec.py

EXPOSE 8080
CMD ["python", "/app/agent.py"]
