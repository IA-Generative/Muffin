# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
# libreoffice (writer only is enough): converts the edited ODT draft to the PDF preview the user
# validates (#169) - the same package worker/document_process already installs for liteparse.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app
USER worker
ENV PATH="/app/.venv/bin:$PATH"
# Read-only root filesystems (Helm) leave only /tmp writable: LibreOffice's profile and the
# conversion's temporary files must live there.
ENV HOME=/tmp
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD celery -A app.celery_app inspect ping -d celery@$$HOSTNAME || exit 1
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]
