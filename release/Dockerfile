# Build from repo root: docker build -f release/Dockerfile .
# This ensures common/ is available. For GitHub-hosted usage, use the image built by CI (see .github/workflows/ci.yml).

FROM python:3.12-slim

WORKDIR /action

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git config --system --add safe.directory /github/workspace

COPY common /action/common
COPY release/requirements.txt /action/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && pip install /action/common

COPY release/main.py /action/main.py

ENV PYTHONPATH=/action

ENTRYPOINT ["python", "/action/main.py"]
