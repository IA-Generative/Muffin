# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 1000 muffin
WORKDIR /app
COPY --from=builder --chown=muffin:muffin /app/.venv /app/.venv
COPY --from=builder --chown=muffin:muffin /app/app /app/app
# Needed at runtime, not just build time: `alembic upgrade head` runs against
# the deployed image (docker compose exec / an init container), so the
# migration scripts and alembic.ini have to travel with it.
COPY --chown=muffin:muffin migrations ./migrations
COPY --chown=muffin:muffin alembic.ini ./
USER muffin
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health',timeout=5).status==200 else 1)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
