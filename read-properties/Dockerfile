FROM python:3.12-slim

WORKDIR /action

# Install git
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git config --global --add safe.directory /github/workspace

# Copy common module
COPY common /action/common

# Install common module
RUN pip install /action/common

# Copy script
COPY read-properties/read_properties.py /action/read_properties.py

# Set PYTHONPATH
ENV PYTHONPATH=/action

ENTRYPOINT ["python", "/action/read_properties.py"]
