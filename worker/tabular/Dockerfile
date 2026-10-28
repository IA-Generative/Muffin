# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
# pip is a build tool: the runtime image never installs anything, and the pip bundled with the base
# image carries known CVEs. Removed rather than upgraded, so there is nothing left to keep patched.
RUN python -m pip uninstall -y pip
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app

USER worker
ENV PATH="/app/.venv/bin:$PATH"
# HOME is /tmp, the one writable place on a read-only root filesystem. DuckDB loads no extension (they are neither
# installed nor autoloaded: the engine turns that off) and each query works in a private folder made under it.
ENV HOME=/tmp
ENV QUERY_WORK_DIR=/tmp
# matplotlib keeps its font cache and its config in a writable folder, and draws without a display.
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV MPLBACKEND=Agg
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD celery -A app.celery_app inspect ping -d celery@$$HOSTNAME || exit 1
# One query at a time per process, each bounded by QUERY_MEMORY_LIMIT (plus its spill, in /tmp).
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info", "-Q", "tabular_sql", "-c", "2"]
