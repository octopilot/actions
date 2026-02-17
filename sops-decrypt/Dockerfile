FROM python:3.12-slim

WORKDIR /action

# Install git and curl/wget for downloading sops
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git config --system --add safe.directory /github/workspace

# Install SOPS
# Using v3.9.0 as a stable recent version
ARG SOPS_VERSION=v3.9.0
RUN curl -L -o /usr/local/bin/sops https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}.linux.amd64 && \
    chmod +x /usr/local/bin/sops

# Copy common module
COPY common /action/common

# Install dependencies and common module
RUN pip install PyYAML && pip install /action/common

# Copy script
COPY sops-decrypt/sops_decrypt.py /action/sops_decrypt.py

# Set PYTHONPATH
ENV PYTHONPATH=/action

ENTRYPOINT ["python", "/action/sops_decrypt.py"]
