# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app

# Pre-install DuckDB extensions during build (FS is writable here).
# At runtime with readOnlyRootFilesystem, LOAD reads pre-installed extensions
# without needing to write to the home directory.
# HOME=/tmp ensures DuckDB uses a writable dir if INSTALL is needed at runtime.
ENV HOME=/tmp
RUN /app/.venv/bin/python -c "import duckdb; c = duckdb.connect(); c.execute('INSTALL httpfs')"

USER worker
ENV PATH="/app/.venv/bin:$PATH"
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD celery -A app.celery_app inspect ping -d celery@$$HOSTNAME || exit 1
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]
