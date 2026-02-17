FROM python:3.12-slim

WORKDIR /action

# Install git (often needed for setuptools_scm or just general utility)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git config --system --add safe.directory /github/workspace

# Copy common module
COPY common /action/common

# Install common module (dependencies will be installed automatically)
RUN pip install /action/common

# Copy the script
COPY bump-version/bump_version.py /action/bump_version.py

# Set PYTHONPATH to include common if needed, though pip install should handle it
ENV PYTHONPATH=/action

# Set entrypoint
ENTRYPOINT ["python", "/action/bump_version.py"]
