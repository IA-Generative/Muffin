# Scaffold only - not implemented yet. Mirrors worker/document_process's
# structure so both workers are built and deployed the same way once this
# one has real tasks.

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
USER worker
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-c", "print('agent_execution worker is not implemented yet')"]
