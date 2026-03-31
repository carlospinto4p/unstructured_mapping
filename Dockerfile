FROM python:3.14-slim

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install runtime dependencies only (no dev extras)
RUN uv sync --frozen --no-dev

# Copy source code
COPY src/ src/

# Data directory (mount point for SQLite volume)
RUN mkdir -p data

CMD ["uv", "run", "python", "-m", "unstructured_mapping.cli.scheduler"]
