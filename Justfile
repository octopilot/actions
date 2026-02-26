# Install dependencies
install:
    pip install -e ./common
    pip install pytest pytest-cov ruff pyre-check requests PyNaCl google-cloud-container

# Run linting
lint:
    ruff check .

# Run formatting
format:
    ruff format .

# Check formatting without modifying
check-format:
    ruff format --check .

# Run tests
test:
    pytest tests/ -v --tb=short --cov=common --cov-report=term-missing
# Run type checking
check-types:
    pyre
