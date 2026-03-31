FROM python:3.14-slim

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install runtime + scraping dependencies (no dev extras)
RUN uv sync --frozen --no-dev --extra scraping

# Copy source code and install the project
COPY src/ src/
RUN uv pip install --no-deps .

# Data directory (mount point for SQLite volume)
RUN mkdir -p data

CMD ["uv", "run", "python", "-m", "unstructured_mapping.cli.scheduler"]
