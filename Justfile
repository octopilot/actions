# Install dependencies
install:
    pip install -e ./common
    pip install pytest pytest-cov ruff

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
    PYTHONPATH=common pytest tests/ -v
