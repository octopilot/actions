FROM python:3.12-slim

WORKDIR /action

# Install git
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copy common module
COPY common /action/common

# Install dependencies and common module
RUN pip install requests pynacl && pip install /action/common

# Copy script
COPY rotate-secret/rotate_secret.py /action/rotate_secret.py

# Set PYTHONPATH
ENV PYTHONPATH=/action

ENTRYPOINT ["python", "/action/rotate_secret.py"]
