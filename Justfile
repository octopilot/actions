# Install dependencies
install:
    pip install -e ./common
    pip install pytest pytest-cov ruff pyre-check

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

# Run type checking
check-types:
    pyre
